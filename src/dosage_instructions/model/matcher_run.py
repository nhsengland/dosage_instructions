import re

from pyspark.sql import functions as F

import spacy
from spacy.language import Language
from spacy.matcher import Matcher
from spacy.util import compile_infix_regex

from dosage_instructions.model.matcher_classes import (
    element_types,
    create_extract_all_udf,
)
from dosage_instructions.model.element_order_rules import validate_dosage_elements
from dosage_instructions.model.cross_column_validity_rules import (
    apply_cross_column_rules,
)
import dosage_instructions.model.constants as myconstants
from dosage_instructions.model.functions import (
    reg_extract_and_tag_element,
)
from dosage_instructions.model.preprocessing import preprocess_dosage

# ---------------------------------------------------------------------------
# spaCy pipeline component — must be registered at module level
# ---------------------------------------------------------------------------


@Language.component("norm_from_lemma")
def norm_from_lemma(doc):
    """Copy lemma → norm so matcher patterns can use NORM uniformly.

    spaCy's en_core_web_sm applies American-English normalisation to certain
    words (e.g. "litres" → norm="liters", "millilitres" → norm="milliliters").
    Our matcher patterns are built from British-English lemmas (e.g. "litre"),
    matching on NORM. Without this fix, "litres" (norm="liters") would never
    match a pattern expecting NORM="litre".

    We overwrite norm with lemma for ALL tokens EXCEPT those registered via
    nlp.tokenizer.add_special_case (e.g. "tablet(s)" → NORM="tablet"). Those
    special cases intentionally set NORM to a singular form and must not be
    overwritten — we detect them by the presence of "(" in the token text,
    since all our special cases are "(s)" suffixed forms.
    """
    for token in doc:
        if "(" not in token.text:
            token.norm_ = token.lemma_
    return doc


# ---------------------------------------------------------------------------
# Pipeline step functions
# ---------------------------------------------------------------------------


def _setup_spacy_matcher():
    """Load spaCy, configure tokenizer, register element extractors.

    Returns (nlp, matcher, elements) ready for UDF creation.
    """
    nlp = spacy.load("en_core_web_sm")
    # pinned: en_core_web_sm==3.8.0, spacy==3.8.14 — do not upgrade without re-validating lemmatisation/POS
    infixes = nlp.Defaults.infixes + [r"\/", r"\-", r"(?<=[0-9])(?=[a-zA-Z])"]
    infix_regex = compile_infix_regex(infixes)
    nlp.tokenizer.infix_finditer = infix_regex.finditer

    # Register "(s)" forms as single tokens so spaCy doesn't split on the parenthesis.
    # NORM is set to the singular base so NORM-based matching works uniformly.
    # Sites (eye, nostril, etc.) are intentionally excluded — "eye(s)" has clinical meaning.
    for word in myconstants.PARENTHETICAL_S_WORDS:
        nlp.tokenizer.add_special_case(
            f"{word}(s)", [{"ORTH": f"{word}(s)", "NORM": word}]
        )

    # Copy lemma → norm for all tokens not already given a NORM via special case.
    # This lets us use NORM uniformly in matcher patterns (handles tablet/tablets/tablet(s)).
    nlp.add_pipe("norm_from_lemma", after="lemmatizer")

    matcher = Matcher(nlp.vocab)
    elements = [element_type(nlp, matcher) for element_type in element_types]

    return nlp, matcher, elements


def _run_spacy_extraction(df, nlp, matcher, elements, spark_context):
    """Run the spaCy matcher UDF and unpack extracted columns into DataFrame columns.

    Broadcasts the spaCy model and matcher to executors, runs the single-pass
    extraction UDF, then unpacks the returned struct into individual _clean,
    _captured, and sub-field columns for each element.
    """
    bc_nlp = spark_context.broadcast(nlp)
    bc_matcher = spark_context.broadcast(matcher)

    extract_udf = create_extract_all_udf(elements, bc_nlp, bc_matcher)
    df = df.withColumn("_extracted", extract_udf(F.col("dosage_elements")))

    df = df.withColumn("dosage_elements", F.col("_extracted.dosage_elements"))
    for element in elements:
        df = df.withColumn(
            f"{element.element_key}_clean",
            F.col(f"_extracted.{element.element_key}_clean"),
        )
        df = df.withColumn(
            f"{element.element_key}_captured",
            F.col(f"_extracted.{element.element_key}_captured"),
        )
        for split_field in element.element_split:
            df = df.withColumn(
                f"{element.element_key}_{split_field}",
                F.col(f"_extracted.{element.element_key}_{split_field}"),
            )
    df = df.drop("_extracted")

    return df


def _has_col(df, col_name):
    """Spark Column expression: True if column has a non-null, non-empty value."""
    if col_name not in df.columns:
        return F.lit(False)
    col_type = dict(df.dtypes).get(col_name, "string")
    if "array" in col_type:
        return F.col(col_name).isNotNull() & (F.size(F.col(col_name)) > 0)
    return F.col(col_name).isNotNull() & (F.length(F.col(col_name)) > 0)


def _col_or_default(df, col_name, default_expr):
    """Return F.col(col_name) if it exists in df, otherwise default_expr."""
    return F.col(col_name) if col_name in df.columns else default_expr


def _infer_period_for_daily_when(df):
    """Infer period from "each/every <daily timing>" when no frequency is present.

    This is the when-element counterpart to PeriodElement's built-in
    frequency=IMPLIED_FREQUENCY — same rule, different trigger.
    See "Implied frequency rule" in constants.py for full explanation.

    When "each night", "every morning", etc. is captured as a when element but
    no frequency/period is present, we:
    1. Create periodElement (frequency=IMPLIED_FREQUENCY, period=IMPLIED_DAILY_PERIOD,
       periodUnit=IMPLIED_DAILY_UNIT)
    2. Strip "each/every" prefix from when text → "at <timing>"

    This makes the bucket match e.g. "1 tablet | once every day | at night".
    """
    _has_freq = (
        _has_col(df, "frequencyBare_frequency")
        | _has_col(df, "frequencyWithMethod_frequency")
        | _has_col(df, "periodElement_period_units")
    )

    # Use _captured (raw UDF output, never rewritten) not _clean
    _when_bare_matches = F.col("whenBare_captured").rlike(myconstants.DAILY_WHEN_RE)
    _infer_from_bare = _when_bare_matches & ~_has_freq

    _when_wm_matches = F.col("whenWithMethod_captured").rlike(myconstants.DAILY_WHEN_RE)
    _infer_from_wm = _when_wm_matches & ~_has_freq & ~_when_bare_matches

    _should_infer = _infer_from_bare | _infer_from_wm

    # ── Populate periodElement fields ────────────────────────────────────
    # NOTE: periodElement_frequency is written FIRST in a single withColumn
    # to avoid a Spark catalyst issue where chained withColumn calls referencing
    # the same column can pick up stale/overwritten values in the otherwise branch.
    df = df.withColumn(
        "periodElement_frequency",
        F.when(_should_infer, F.array(F.lit(myconstants.IMPLIED_FREQUENCY))).otherwise(
            _col_or_default(
                df, "periodElement_frequency", F.array(F.lit(None).cast("string"))
            )
        ),
    )
    df = df.withColumn(
        "periodElement_clean",
        F.when(
            _should_infer, F.lit(f"once every {myconstants.IMPLIED_DAILY_UNIT}")
        ).otherwise(
            _col_or_default(df, "periodElement_clean", F.lit(None).cast("string"))
        ),
    )
    df = df.withColumn(
        "periodElement_period",
        F.when(
            _should_infer, F.array(F.lit(myconstants.IMPLIED_DAILY_PERIOD))
        ).otherwise(
            _col_or_default(
                df, "periodElement_period", F.array(F.lit(None).cast("string"))
            )
        ),
    )
    df = df.withColumn(
        "periodElement_periodMax",
        F.when(_should_infer, F.array(F.lit(None).cast("string"))).otherwise(
            _col_or_default(
                df, "periodElement_periodMax", F.array(F.lit(None).cast("string"))
            )
        ),
    )
    df = df.withColumn(
        "periodElement_period_units",
        F.when(_should_infer, F.array(F.lit(myconstants.IMPLIED_DAILY_UNIT))).otherwise(
            _col_or_default(
                df, "periodElement_period_units", F.array(F.lit(None).cast("string"))
            )
        ),
    )

    # ── Ensure frequency=1 whenever periodElement exists but frequency is empty
    _pe_has_units = F.col("periodElement_period_units").isNotNull() & (
        F.size(F.col("periodElement_period_units")) > 0
    )
    _pe_freq_empty = F.col("periodElement_frequency").isNull() | (
        F.size(F.col("periodElement_frequency")) == 0
    )
    df = df.withColumn(
        "periodElement_frequency",
        F.when(
            _pe_has_units & _pe_freq_empty,
            F.array(F.lit(myconstants.IMPLIED_FREQUENCY)),
        ).otherwise(F.col("periodElement_frequency")),
    )

    # ── Strip "each/every" prefix from when text → "at <timing>" ─────────
    _each_every_re = r"^(each|every)\s+"
    df = df.withColumn(
        "whenBare_clean",
        F.when(
            _infer_from_bare,
            F.regexp_replace(F.col("whenBare_clean"), _each_every_re, "at "),
        ).otherwise(F.col("whenBare_clean")),
    )
    if "whenBare_when" in df.columns:
        df = df.withColumn(
            "whenBare_when",
            F.when(
                _infer_from_bare,
                F.transform(
                    F.col("whenBare_when"),
                    lambda x: F.regexp_replace(x, _each_every_re, "at "),
                ),
            ).otherwise(F.col("whenBare_when")),
        )
    df = df.withColumn(
        "whenWithMethod_clean",
        F.when(
            _infer_from_wm,
            F.regexp_replace(F.col("whenWithMethod_clean"), _each_every_re, "at "),
        ).otherwise(F.col("whenWithMethod_clean")),
    )
    if "whenWithMethod_when" in df.columns:
        df = df.withColumn(
            "whenWithMethod_when",
            F.when(
                _infer_from_wm,
                F.transform(
                    F.col("whenWithMethod_when"),
                    lambda x: F.regexp_replace(x, _each_every_re, "at "),
                ),
            ).otherwise(F.col("whenWithMethod_when")),
        )

    return df


def _build_normalise_expr(col_expr):
    """Build a chained CASE WHEN expression that normalises when text to canonical form.

    First matching rule in WHEN_NORMALISE_RULES wins, else the original value is kept.
    """
    expr = col_expr
    for pattern, canonical in reversed(myconstants.WHEN_NORMALISE_RULES):
        expr = F.when(
            col_expr.isNotNull()
            & (F.length(col_expr) > 0)
            & F.lower(col_expr).rlike(pattern),
            F.lit(canonical),
        ).otherwise(expr)
    return expr


def _normalise_when_text(df):
    """Normalise when text to canonical form per FHIR timing code.

    Multiple phrasings map to the same FHIR EventTiming code (e.g. "in the morning",
    "at morning", "on a morning" all → MORN). Normalising to a single canonical form
    ensures bucket uniqueness matches FHIR structure uniqueness.
    """
    # Normalise _clean columns (StringType)
    for col_name in ("whenBare_clean", "whenWithMethod_clean"):
        if col_name in df.columns:
            df = df.withColumn(col_name, _build_normalise_expr(F.col(col_name)))

    # Normalise _when sub-field arrays (used by FHIR builder)
    for col_name in ("whenBare_when", "whenWithMethod_when"):
        if col_name in df.columns:
            df = df.withColumn(
                col_name,
                F.when(
                    F.col(col_name).isNotNull() & (F.size(F.col(col_name)) > 0),
                    F.transform(F.col(col_name), lambda x: _build_normalise_expr(x)),
                ).otherwise(F.col(col_name)),
            )

    return df


def _extract_regex_elements(df):
    """Extract regex-based elements: extras, asNeeded, for, route, site.

    These elements use simple regex matching (not spaCy) and are extracted
    after the spaCy UDF has run, operating on the dosage_elements column.
    """
    dosage_col_name = "dosage_elements"

    df = reg_extract_and_tag_element(
        df, dosage_col_name, "extrasAsDirected_clean", myconstants.extras_asDirected
    )
    # Normalise generic forms (asd, ad) to "as directed" for consistent bucket/FHIR output.
    # "as directed by <professional>" forms keep their original text (text-only additionalInstruction).
    df = df.withColumn(
        "extrasAsDirected_clean",
        F.when(
            F.col("extrasAsDirected_clean").rlike(r"(?i)\bby\b"),
            F.col("extrasAsDirected_clean"),
        )
        .when(F.length(F.col("extrasAsDirected_clean")) > 0, F.lit("as directed"))
        .otherwise(F.col("extrasAsDirected_clean")),
    )
    df = reg_extract_and_tag_element(
        df, dosage_col_name, "extras_clean", myconstants.extras
    )
    df = reg_extract_and_tag_element(
        df, dosage_col_name, "extrasPAUSE_clean", myconstants.extrasPAUSE
    )
    df = reg_extract_and_tag_element(
        df, dosage_col_name, "extrasALTER_clean", myconstants.extrasALTER
    )

    # asNeededCodeableConcept: cross-product of asNeeded phrases × for_config
    asNeededCC = [
        aNB + " " + forE
        for forE in myconstants.for_config
        for aNB in myconstants.asNeededBoolean
    ]
    df = reg_extract_and_tag_element(
        df, dosage_col_name, "asNeededCodeableConcept_clean", asNeededCC
    )
    df = reg_extract_and_tag_element(
        df, dosage_col_name, "asNeededBoolean_clean", myconstants.asNeededBoolean
    )

    # Normalise asNeeded synonyms to canonical "as needed"
    df = df.withColumn(
        "asNeededBoolean_clean",
        F.when(
            F.length(F.col("asNeededBoolean_clean")) > 0, F.lit("as needed")
        ).otherwise(F.col("asNeededBoolean_clean")),
    )
    # Normalise synonym variants then strip the asNeeded prefix, leaving only the
    # indication phrase (e.g. "when required for pain" → "for pain").
    # The bucket builder prepends "as needed " so the bucket reads "as needed for pain".
    df = df.withColumn(
        "asNeededCodeableConcept_clean",
        F.regexp_replace(
            F.regexp_replace(
                F.col("asNeededCodeableConcept_clean"),
                myconstants.ASNEEDED_NORMALISE_PATTERN,
                "as needed",
            ),
            myconstants.ASNEEDED_STRIP_PATTERN,
            "",
        ),
    )
    # forElement (purpose/indication phrases)
    df = reg_extract_and_tag_element(
        df, dosage_col_name, "forElement_clean", myconstants.for_config
    )

    # Route: match base forms + adverbial forms, then map adverbials back to base
    route_adverbial_reverse = {
        v: k for k, v in myconstants.route_adverbial_mapping.items()
    }
    all_routes_to_match = myconstants.route + list(
        myconstants.route_adverbial_mapping.values()
    )
    df = reg_extract_and_tag_element(
        df, dosage_col_name, "route_clean", all_routes_to_match
    )
    df = df.withColumn("route_adverbial", F.col("route_clean"))
    mapping_expr = F.col("route_clean")
    for adverbial, base in route_adverbial_reverse.items():
        mapping_expr = F.when(F.col("route_clean") == adverbial, F.lit(base)).otherwise(
            mapping_expr
        )
    df = df.withColumn("route_clean", mapping_expr)

    # Site
    df = reg_extract_and_tag_element(
        df, dosage_col_name, "site_clean", myconstants.site_config
    )

    return df


def _normalise_clean_columns(df):
    """Normalise _clean columns to canonical display forms using source-of-truth dicts.

    Site: raw regex match (e.g. "to both eyes", "in the left eye") is normalised
    to the SITES descriptionDisplay (e.g. "Both eyes", "Left eye") by substring
    matching on the SITES keyword. Longest keyword first so "both eyes" wins
    over "eyes".
    """
    # ── site_clean → SITES descriptionDisplay ────────────────────────────
    if "site_clean" in df.columns:
        col_expr = F.col("site_clean")
        expr = col_expr
        # Sorted shortest-first so we apply in reverse → longest ends up outermost
        for keyword, (_, _, desc) in sorted(
            myconstants.SITES.items(), key=lambda kv: len(kv[0])
        ):
            expr = F.when(
                col_expr.isNotNull()
                & (F.length(col_expr) > 0)
                & F.lower(col_expr).contains(keyword),
                F.lit(desc),
            ).otherwise(expr)
        df = df.withColumn("site_clean", expr)

    return df


def _rescue_when_offsets(df):
    """Rescue excluded when-offset values to extras_whenoffset.

    When a when element has an offset (e.g. "30 minutes before food") AND
    the row is excluded, the when text is moved to extras_whenoffset so
    it can still appear as an additionalInstruction in the FHIR output.
    """
    if "exclude" not in df.columns:
        df = df.withColumn("exclude", F.lit(None).cast("string"))

    _excluded = F.col("exclude").isNotNull() & (F.trim(F.col("exclude")) != "")
    _bare_offset = F.col("whenBare_offsetMax").isNotNull()
    _wm_offset = F.col("whenWithMethod_offsetMax").isNotNull()

    df = (
        df.withColumn(
            "extras_whenoffset",
            F.when(
                (_bare_offset | _wm_offset) & _excluded,
                F.coalesce(F.col("whenBare_clean"), F.col("whenWithMethod_clean")),
            ).otherwise(F.lit(None)),
        )
        .withColumn(
            "whenBare_clean",
            F.when(_bare_offset & _excluded, F.lit(None)).otherwise(
                F.col("whenBare_clean")
            ),
        )
        .withColumn(
            "whenWithMethod_clean",
            F.when(_wm_offset & _excluded, F.lit(None)).otherwise(
                F.col("whenWithMethod_clean")
            ),
        )
    )

    return df


def _build_buckets_and_validate(df, snapshot_ts):
    """Build bucket string, run validation rules, add metadata columns."""
    dosage_col_name = "dosage_elements"

    df.cache()

    # asNeededCodeableConcept_clean holds only the indication phrase (e.g. "for pain")
    # after the asNeeded prefix is stripped, so we prepend "as needed " for the bucket
    # so it reads naturally (e.g. "as needed for pain") while _clean stays short for FHIR.
    _BUCKET_PREFIX = {"asNeededCodeableConcept": "as needed "}

    df = df.withColumn("buckets", F.lit(""))
    for col_element in myconstants.bucket_order:
        col_clean = f"{col_element}_clean"
        prefix = _BUCKET_PREFIX.get(col_element, "")
        df = df.withColumn(
            "buckets",
            F.trim(
                F.concat(
                    df["buckets"],
                    F.when(F.length(F.col(col_clean)) > 0, F.lit(" | ")).otherwise(
                        F.lit("")
                    ),
                    F.when(F.length(F.col(col_clean)) > 0, F.lit(prefix)).otherwise(
                        F.lit("")
                    ),
                    F.coalesce(df[col_clean].cast("string"), F.lit("")),
                )
            ),
        )
    df = df.withColumn("buckets", F.regexp_replace("buckets", r"^\| ", ""))

    df = df.withColumn(dosage_col_name, F.trim(F.col(dosage_col_name)))

    df = validate_dosage_elements(df, dosage_col_name)
    df = apply_cross_column_rules(df)

    df = df.withColumn("timestamp", F.current_timestamp())
    df = df.withColumn("space", F.lit(" ")).withColumn("_snapshot_ts", snapshot_ts)

    return df


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_extraction_pipeline(df, snapshot_ts=None, spark_context=None):
    """Full extraction pipeline: preprocess → spaCy → regex extras → buckets → validation.

    Input:  DataFrame with either:
            - `dosage` column (raw text) → will be preprocessed automatically
            - `dosage_lower` column (already preprocessed) → skips preprocessing
    Output: DataFrame with all _clean columns, sub-fields, buckets, exclude, mapped, etc.

    Parameters
    ----------
    spark_context : pyspark.SparkContext, optional
        Used for broadcasting spaCy objects to executors. When called from a
        Foundry transform, pass ``ctx.spark_session.sparkContext``. Falls back
        to the active session's context when not supplied (e.g. in tests).
    """
    # Tests call this directly with a raw `dosage` column (no dosage_lower).
    # In production, run_model preprocesses before grouping, so dosage_lower
    # already exists and this block is skipped.
    if "dosage_lower" not in df.columns:
        df = preprocess_dosage(df)

    if snapshot_ts is None:
        snapshot_ts = F.current_timestamp()

    # Fall back to the active session's context when not injected (tests, ad-hoc usage).
    if spark_context is None:
        from pyspark.sql import SparkSession

        spark_context = SparkSession.builder.getOrCreate().sparkContext

    nlp, matcher, elements = _setup_spacy_matcher()

    # ── Pre-extraction setup (before spaCy UDF runs) ─────────────────────
    df = df.cache()
    df = df.withColumn("dosage_elements", df["dosage_lower"])

    # extras_b contains numbers so must be extracted before the spaCy matcher
    df = reg_extract_and_tag_element(
        df, "dosage_elements", "extras_b_clean", myconstants.extras_b
    )

    df = _run_spacy_extraction(df, nlp, matcher, elements, spark_context)

    df = _infer_period_for_daily_when(df)

    df = _normalise_when_text(df)

    df = _extract_regex_elements(df)

    df = _normalise_clean_columns(df)

    df = _rescue_when_offsets(df)

    df = _build_buckets_and_validate(df, snapshot_ts)

    return df
