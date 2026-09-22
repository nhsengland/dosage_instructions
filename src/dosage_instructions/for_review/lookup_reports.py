import re

import spacy
from spacy.matcher import Matcher
from spacy.util import compile_infix_regex
from transforms.api import transform, Input, Output
from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType, StringType, StructType, StructField
from pyspark.sql.window import Window

from dosage_instructions.model.matcher_classes import element_types
from dosage_instructions.model.preprocessing import add_dots_to_latin
import dosage_instructions.model.constants as myconstants
from dosage_instructions.to_test import element_specific


def _readable_pattern(pattern):
    """Strips regex syntax to produce a human-readable form."""
    s = pattern
    s = re.sub(r"\(\?:", "", s)
    s = re.sub(r"[()]", "", s)
    s = re.sub(
        r"\\.([?+*])?",
        lambda m: m.group(0)[1] if m.group(0)[1] not in "?+*bsdwBS" else " ",
        s,
    )
    s = re.sub(r"\\[bBsdw]", "", s)
    s = re.sub(r"[?+*]", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def _token_to_friendly(token_dict):
    """Convert a single spaCy Matcher token dict to a readable string."""
    op = token_dict.get("OP", "")
    parts = []

    for key in ("LOWER", "TEXT", "LEMMA", "ORTH"):
        if key in token_dict:
            val = token_dict[key]
            if isinstance(val, str):
                parts.append(val)
            elif isinstance(val, dict):
                if "IN" in val:
                    items = val["IN"]
                    if len(items) <= 5:
                        parts.append("|".join(str(i) for i in items))
                    else:
                        parts.append(f"{items[0]}|{items[1]}|...({len(items)} options)")
                elif "REGEX" in val:
                    parts.append(val["REGEX"])
            break

    if "LIKE_NUM" in token_dict:
        parts.append("<number>")
    if "IS_SPACE" in token_dict:
        parts.append(" ")

    if not parts:
        parts.append(str(token_dict))

    text = " ".join(parts)
    if op == "?":
        return f"({text})?"
    elif op == "*":
        return f"({text})*"
    elif op == "+":
        return f"({text})+"
    return text


def _pattern_to_friendly(token_dicts):
    """Convert a full spaCy pattern (list of token dicts) to a readable string."""
    return " ".join(_token_to_friendly(t) for t in token_dicts)


SAMPLE_SIZE = 200

ELEMENT_KEYS = [et.element_key for et in element_types]

CONSTANTS_TO_REPORT = [
    name
    for name, obj in vars(myconstants).items()
    if not name.startswith("_") and isinstance(obj, (dict, list))
]


@transform(
    captured_clean_summary=Output(
        "ri.foundry.main.dataset.36ba5d39-5021-4b27-b51f-5a14377c7075"
    ),
    random_sample=Output(
        "ri.foundry.main.dataset.97919146-f859-40c2-b05b-50d52411cf43"
    ),
    stratified_by_frequency=Output(
        "ri.foundry.main.dataset.bf81bd85-54a0-434a-9bef-556396f39648"
    ),
    stratified_by_elements=Output(
        "ri.foundry.main.dataset.f42c4aec-8989-456f-a2d3-ebf848498272"
    ),
    element_orders_mapped=Output(
        "ri.foundry.main.dataset.54067fa0-50f7-4956-ad46-230d6e597b9d"
    ),
    all_patterns=Output("ri.foundry.main.dataset.78d9c297-7e0e-426c-8462-33060decf91d"),
    all_constants_output=Output(
        "ri.foundry.main.dataset.11e7093b-754e-41b3-bb13-156e640fab62"
    ),
    preprocessing_report=Output(
        "ri.foundry.main.dataset.98ff6a32-5063-4223-bcdd-581093246d9a"
    ),
    lookup_input=Input("ri.foundry.main.dataset.1a58c534-ab3e-4b7e-beea-93e47fe7321c"),
    refined_lookup_input=Input(
        "ri.foundry.main.dataset.ea624ad0-4666-4b49-adf5-f87c65ebb8e7"
    ),
)
def compute(
    lookup_input,
    refined_lookup_input,
    captured_clean_summary,
    random_sample,
    stratified_by_frequency,
    stratified_by_elements,
    element_orders_mapped,
    all_patterns,
    all_constants_output,
    preprocessing_report,
):
    df = lookup_input.dataframe()
    df_refined = refined_lookup_input.dataframe()
    spark = df.sparkSession

    # Use refined for sample outputs (includes fhir_json, consolidated dose cols);
    # use raw lookup for element-level reports (has individual _clean/_captured cols).
    mapped_df = df.filter(F.col("mapped") == "true")
    mapped_refined = df_refined.filter(F.col("mapped") == "true")

    # ── 1. captured_clean_summary ─────────────────────────────────────────────

    stacks = []
    for key in ELEMENT_KEYS:
        clean_col = f"{key}_clean"
        captured_col = f"{key}_captured"
        if clean_col in df.columns and captured_col in df.columns:
            subset = df.filter(F.col(clean_col).isNotNull()).select(
                F.lit(key).alias("element"),
                F.col(captured_col).alias("captured"),
                F.col(clean_col).alias("clean"),
                F.col("mapped"),
                F.col("dosage_count"),
                F.col("dosage_lower"),
            )
            stacks.append(subset)

    if stacks:
        unioned_with_dosage = stacks[0]
        for s in stacks[1:]:
            unioned_with_dosage = unioned_with_dosage.unionByName(s)

        # Join dosage_lower → fhir_json from refined before aggregating,
        # so fhir_json can be included as first() in the same groupBy —
        # no separate join needed and no risk of fan-out duplicates.
        unioned_with_fhir = unioned_with_dosage.join(
            df_refined.select("dosage_lower", "fhir_json"),
            on="dosage_lower",
            how="left",
        ).drop("dosage_lower")

        summary = (
            unioned_with_fhir.groupBy("element", "captured", "clean", "mapped")
            .agg(
                F.sum("dosage_count").alias("frequency"),
                F.first(F.col("fhir_json"), ignorenulls=True).alias(
                    "fhir_json_example"
                ),
            )
            .orderBy("element", F.desc("frequency"))
        )
    else:
        summary = spark.createDataFrame(
            [],
            "element string, captured string, clean string, mapped string, frequency long, fhir_json string",
        )

    captured_clean_summary.write_dataframe(summary)

    # ── 2. random_sample (from refined — includes fhir_json) ────────────────────

    sample_df = mapped_refined.orderBy(F.rand(seed=42)).limit(SAMPLE_SIZE)
    random_sample.write_dataframe(sample_df)

    # ── 3. stratified_sample_by_frequency (from refined) ──────────────────────

    banded = mapped_refined.withColumn(
        "frequency_band",
        F.when(F.col("dosage_count") <= 10, "1-10")
        .when(F.col("dosage_count") <= 100, "11-100")
        .when(F.col("dosage_count") <= 1000, "101-1000")
        .otherwise("1000+"),
    )

    w_freq = Window.partitionBy("frequency_band").orderBy(F.rand(seed=42))
    stratified_freq = (
        banded.withColumn("_rn", F.row_number().over(w_freq))
        .filter(F.col("_rn") <= SAMPLE_SIZE)
        .drop("_rn")
    )
    stratified_by_frequency.write_dataframe(stratified_freq)

    # ── 4. stratified_sample_by_elements (from refined) ───────────────────────
    # Sample equally from each element using the refined FHIR-aligned columns.
    # The refined output uses consolidated column names (e.g. doseRange_low instead
    # of individual element _clean cols), so we filter on non-null consolidated cols.

    # Map element keys to their corresponding refined column for filtering
    _ELEMENT_TO_REFINED_COL = {
        "methodDirect": "method_verb",
        "methodPassive": "method_verb",
        "rateRatio": "rateRatio_periodUnit",
        "rateRange": "rateRange_unit",
        "rateQuantity": "rateQuantity_unit",
        "durationValue": "duration_value",
        "durationMax": "duration_valueMax",
        "frequencyWithMethod": "frequency_value",
        "frequencyBare": "frequency_value",
        "timeOfDay": "timeOfDay_value",
        "dayOfWeek": "dayOfWeek_value",
        "maxDosePerPeriod": "maxDosePerPeriod_num_value",
        "maxDosePerAdministration": "maxDosePerAdministration_value",
        "maxDosePerLifetime": "maxDosePerLifetime_value",
        "periodElement": "period_value",
        "whenWithMethod": "when_value",
        "whenBare": "when_value",
        "boundsDuration": "boundsDuration_value",
        "boundsPeriod": "boundsPeriod_start",
        "boundsAPeriodStartEnd": "boundsPeriod_start",
        "event": "event_value",
        "count": "count_count",
        "doseRange": "doseRange_low",
        "doseQuantity": "doseQuantity_value",
        "doseXMilliValueOnly": "doseXMilli_value",
        "milligramMax": "milligram_valueMax",
        "milligramValue": "milligram_value",
        "dose_QuantityValueAndMaxOnly": "doseRange_low",
        "dose_QuantityValueOnly": "doseQuantity_value",
    }

    samples_per_element = max(1, SAMPLE_SIZE // len(ELEMENT_KEYS))
    element_samples = []

    seen_filter_cols = set()
    for element_key in ELEMENT_KEYS:
        filter_col = _ELEMENT_TO_REFINED_COL.get(element_key)
        if not filter_col or filter_col not in mapped_refined.columns:
            continue
        # Avoid duplicate samples when multiple elements map to same refined col
        if filter_col in seen_filter_cols:
            continue
        seen_filter_cols.add(filter_col)

        elem_df = mapped_refined.filter(F.col(filter_col).isNotNull())
        if elem_df.head(1):
            w_elem = Window.partitionBy().orderBy(F.rand(seed=42))
            sample = (
                elem_df.withColumn("_rn", F.row_number().over(w_elem))
                .filter(F.col("_rn") <= samples_per_element)
                .drop("_rn")
            )
            element_samples.append(sample)

    if element_samples:
        stratified_elem = element_samples[0]
        for sample in element_samples[1:]:
            stratified_elem = stratified_elem.unionByName(sample)
    else:
        stratified_elem = mapped_refined.limit(0)

    stratified_by_elements.write_dataframe(stratified_elem)

    # ── 5. element_orders_mapped (from refined) ─────────────────────────────────

    orders = (
        mapped_refined.groupBy("dosage_elements")
        .agg(
            F.first("buckets").alias("example_buckets"),
            F.first("dosage").alias("example_dosage"),
            F.sum("dosage_count").alias("total_count"),
        )
        .orderBy(F.desc("total_count"))
    )
    element_orders_mapped.write_dataframe(orders)

    # ── 6. all_patterns ───────────────────────────────────────────────────────

    nlp = spacy.load("en_core_web_sm")
    infixes = nlp.Defaults.infixes + [r"\/", r"\-", r"(?<=[0-9])(?=[a-zA-Z])"]
    infix_regex = compile_infix_regex(infixes)
    nlp.tokenizer.infix_finditer = infix_regex.finditer
    matcher = Matcher(nlp.vocab)

    pattern_rows = []
    for element_type in element_types:
        inst = element_type(nlp, matcher)

        test_cases = element_specific.get(inst.element_key, {})
        captures_str = ", ".join(test_cases.get("capture", {}).keys())
        ignores_str = ", ".join(test_cases.get("ignore", []))

        for pattern_label in inst.metadata.keys():
            pattern_name = pattern_label.replace(f"{inst.element_key}_", "")
            _, raw_patterns = matcher.get(pattern_label)
            friendly = _pattern_to_friendly(raw_patterns[0]) if raw_patterns else ""
            pattern_rows.append(
                (
                    inst.element_key,
                    pattern_name,
                    friendly,
                    captures_str,
                    ignores_str,
                )
            )

    patterns_schema = StructType(
        [
            StructField("element_key", StringType(), True),
            StructField("pattern_name", StringType(), True),
            StructField("pattern_description", StringType(), True),
            StructField("test_captures", StringType(), True),
            StructField("test_ignores", StringType(), True),
        ]
    )
    patterns_df = spark.createDataFrame(pattern_rows, schema=patterns_schema)
    all_patterns.write_dataframe(patterns_df)

    # ── 7. all_constants ──────────────────────────────────────────────────────

    constant_rows = []
    for name in CONSTANTS_TO_REPORT:
        obj = getattr(myconstants, name, None)
        if obj is None:
            continue
        if isinstance(obj, dict):
            for k, v in obj.items():
                constant_rows.append((name, str(k), str(v)))
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                constant_rows.append((name, str(i), str(item)))

    constants_schema = StructType(
        [
            StructField("constant_name", StringType(), True),
            StructField("key", StringType(), True),
            StructField("value", StringType(), True),
        ]
    )
    constants_df = spark.createDataFrame(constant_rows, schema=constants_schema)
    all_constants_output.write_dataframe(constants_df)

    # ── 8. preprocessing_report ───────────────────────────────────────────────

    patterns = []

    for regex_key, normalized in add_dots_to_latin(myconstants.latin_dict).items():
        patterns.append(
            (
                "latin_dotted",
                re.compile(rf"\b{regex_key}\b"),
                _readable_pattern(regex_key),
                normalized,
            )
        )

    for orig, normalized in myconstants.latin_dict.items():
        patterns.append(
            ("latin", re.compile(rf"\b{re.escape(orig)}\b"), orig, normalized)
        )

    for word, digit in myconstants.WORD_TO_DIGIT.items():
        patterns.append(
            ("words_to_digits", re.compile(rf"\b{re.escape(word)}\b"), word, digit)
        )

    for normalized, originals in myconstants.preprocess_units_of_measure.items():
        for orig in originals:
            patterns.append(
                (
                    "units_of_measure",
                    re.compile(rf"{orig}"),
                    _readable_pattern(orig),
                    normalized,
                )
            )

    for orig, normalized in myconstants.replace_isolated_terms.items():
        patterns.append(
            (
                "isolated_terms",
                re.compile(rf"\b{orig}\b"),
                _readable_pattern(orig),
                normalized,
            )
        )

    for orig, normalized in myconstants.normalise_date_separators.items():
        patterns.append(
            (
                "normalise_date_separators",
                re.compile(rf"{orig}"),
                _readable_pattern(orig),
                normalized,
            )
        )

    for orig, normalized in myconstants.normalise_number_ranges.items():
        patterns.append(
            (
                "normalise_number_ranges",
                re.compile(rf"{orig}"),
                _readable_pattern(orig),
                normalized,
            )
        )

    match_schema = ArrayType(
        StructType(
            [
                StructField("step", StringType()),
                StructField("original_form", StringType()),
                StructField("normalized_to", StringType()),
            ]
        )
    )

    def find_matches(text):
        if not text:
            return []
        text_lower = text.lower()
        matches = []
        for step, regex, orig, norm in patterns:
            if regex.search(text_lower):
                matches.append(
                    {"step": step, "original_form": orig, "normalized_to": norm}
                )
        return matches

    find_matches_udf = F.udf(find_matches, match_schema)

    df_matches = df.withColumn("_matches", find_matches_udf(F.col("dosage")))
    df_exploded = df_matches.select(F.explode("_matches").alias("m"))

    prep_report = (
        df_exploded.groupBy("m.step", "m.normalized_to", "m.original_form")
        .count()
        .withColumnRenamed("count", "row_count")
        .orderBy("step", "normalized_to", "row_count", ascending=[True, True, False])
    )

    preprocessing_report.write_dataframe(prep_report)
