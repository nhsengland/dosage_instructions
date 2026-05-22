from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    concat,
    trim,
    length,
    when,
    lit,
    col as col_,
    regexp_replace,
    current_timestamp,
    coalesce,
)

import spacy
from spacy.matcher import Matcher
from spacy.util import compile_infix_regex

from dosage_instructions.model.matcher_classes import classes, create_extract_all_udf
from dosage_instructions.model.element_order_rules import validate_dosage_elements
from dosage_instructions.model.constants import (
    bucket_order,
    site_config,
    extras_b,
    extras,
    extrasPAUSE,
    extrasALTER,
    asNeededBoolean,
    route,
    odd_spellings,
)
from dosage_instructions.model.functions import (
    get_all_combinations,
    reg_extract_and_tag_element,
)
from dosage_instructions.model.preprocessing import preprocess_dosage


def run_extraction_pipeline(df, snapshot_ts=None):
    """
    Full extraction pipeline: preprocess (if needed) → spaCy → regex extras → buckets → validation.

    Input:  DataFrame with either:
            - `dosage` column (raw text) → will be preprocessed automatically
            - `dosage_lower` column (already preprocessed) → skips preprocessing
    Output: DataFrame with all _clean columns, sub-fields, buckets, exclude, mapped, etc.
    """
    # Tests call this directly with a raw `dosage` column (no dosage_lower).
    # In production, run_model preprocesses before grouping, so dosage_lower
    # already exists and this block is skipped.
    if "dosage_lower" not in df.columns:
        df = preprocess_dosage(df)

    if snapshot_ts is None:
        snapshot_ts = current_timestamp()

    nlp = spacy.load("en_core_web_sm")
    # pinned: en_core_web_sm==3.8.0, spacy==3.8.14 — do not upgrade without re-validating lemmatisation/POS
    infixes = nlp.Defaults.infixes + [r"\/", r"\-", r"(?<=[0-9])(?=[a-zA-Z])"]
    infix_regex = compile_infix_regex(infixes)
    nlp.tokenizer.infix_finditer = infix_regex.finditer

    matcher = Matcher(nlp.vocab)

    spark = SparkSession.builder.appName("element_matcher").getOrCreate()
    instances = [cls(nlp, matcher) for cls in classes]

    sc = spark.sparkContext.getOrCreate()
    bc_nlp = sc.broadcast(nlp)
    bc_matcher = sc.broadcast(matcher)

    df = df.cache()
    dosage_col_name = "dosage_elements"

    df_assessed = df.withColumn(dosage_col_name, df["dosage_lower"])

    df_assessed = reg_extract_and_tag_element(
        df_assessed,
        dosage_col_name,
        "extras_b_clean",
        extras_b,
    )

    extract_udf, extract_schema = create_extract_all_udf(instances, bc_nlp, bc_matcher)

    df_assessed = df_assessed.withColumn(
        "_extracted", extract_udf(col_(dosage_col_name))
    )

    df_assessed = df_assessed.withColumn(
        dosage_col_name, col_("_extracted.dosage_elements")
    )
    for instance in instances:
        df_assessed = df_assessed.withColumn(
            f"{instance.element_key}_clean",
            col_(f"_extracted.{instance.element_key}_clean"),
        )
        df_assessed = df_assessed.withColumn(
            f"{instance.element_key}_captured",
            col_(f"_extracted.{instance.element_key}_captured"),
        )
        for split_field in instance.element_split:
            df_assessed = df_assessed.withColumn(
                f"{instance.element_key}_{split_field}",
                col_(f"_extracted.{instance.element_key}_{split_field}"),
            )
    df_assessed = df_assessed.drop("_extracted")

    df_assessed = df_assessed.withColumn("buckets", lit(""))

    df_assessed = reg_extract_and_tag_element(
        df_assessed, dosage_col_name, "extras_clean", extras
    )
    df_assessed = reg_extract_and_tag_element(
        df_assessed, dosage_col_name, "extrasPAUSE_clean", extrasPAUSE
    )
    df_assessed = reg_extract_and_tag_element(
        df_assessed, dosage_col_name, "extrasALTER_clean", extrasALTER
    )
    df_assessed = reg_extract_and_tag_element(
        df_assessed,
        dosage_col_name,
        "asNeededBoolean_clean",
        asNeededBoolean,
    )
    df_assessed = reg_extract_and_tag_element(
        df_assessed, dosage_col_name, "route_clean", route
    )

    # -- part of scoping options which appear in data, may be useful again if trying to capture more
    # site_dict, site_options = get_all_combinations(
    #    site_config,
    #    odd_spellings=odd_spellings,
    #    how=["{prefix} {next_prefix} {option}{suffix}"],
    # )
    df_assessed = reg_extract_and_tag_element(
        df_assessed, dosage_col_name, "site_clean", site_config
    )

    _excluded = col_("exclude").isNotNull() & (trim(col_("exclude")) != "")
    _bare_offset = col_("whenBare_offsetMax").isNotNull()
    _wm_offset = col_("whenWithMethod_offsetMax").isNotNull()

    df_assessed = (
        df_assessed.withColumn(
            "extras_whenoffset",
            when(
                (_bare_offset | _wm_offset) & _excluded,
                coalesce(col_("whenBare_clean"), col_("whenWithMethod_clean")),
            ).otherwise(lit(None)),
        )
        .withColumn(
            "whenBare_clean",
            when(
                _bare_offset & _excluded,
                lit(None),
            ).otherwise(col_("whenBare_clean")),
        )
        .withColumn(
            "whenWithMethod_clean",
            when(
                _wm_offset & _excluded,
                lit(None),
            ).otherwise(col_("whenWithMethod_clean")),
        )
    )

    df_assessed.cache()
    df.unpersist()

    for colElement in bucket_order:
        col_clean = f"{colElement}_clean"
        df_assessed = df_assessed.withColumn(
            "buckets",
            trim(
                concat(
                    df_assessed["buckets"],
                    when(length(col_(col_clean)) > 0, lit(" - ")).otherwise(lit("")),
                    coalesce(df_assessed[col_clean].cast("string"), lit("")),
                )
            ),
        )
    df_assessed = df_assessed.withColumn(
        "buckets", regexp_replace("buckets", r"^- ", "")
    )

    df_assessed = df_assessed.withColumn(dosage_col_name, trim(col_(dosage_col_name)))

    df_assessed = validate_dosage_elements(df_assessed, "dosage_elements")

    df_assessed = df_assessed.withColumn("timestamp", current_timestamp())

    df_assessed = df_assessed.withColumn("space", lit(" ")).withColumn(
        "_snapshot_ts", snapshot_ts
    )

    return df_assessed
