"""
Data quality checks for the final lookup output.

Validates that rows marked mapped=True do not contain terms that indicate
a bad parse or unsupported input slipping through.
"""

import pytest
from pyspark.sql.functions import col, lower

from dosage_instructions.model.matcher_run import run_extraction_pipeline
from dosage_instructions.model.matcher_classes import element_types

BLACKLISTED_TERMS = [
    "£",
    "monring",
    "supply",
    "oneTo",
    "oneTWO",
    "2times",
    "1,000",
    r"\d+.\d+.\d+",
    "tabet",
]

ELEMENT_KEYS = [et.element_key for et in element_types]


@pytest.fixture(scope="module")
def lookup_output(spark):
    """Run the full pipeline on the full_text capture cases + some edge cases."""
    from dosage_instructions.to_test import full_text

    all_inputs = list(full_text["capture"].keys()) + full_text.get("exclude", [])
    rows = [(text,) for text in all_inputs]
    df = spark.createDataFrame(rows, ["dosage"])
    return run_extraction_pipeline(df)


@pytest.mark.parametrize("term", BLACKLISTED_TERMS)
def test_mapped_rows_do_not_contain_blacklisted_term(lookup_output, term):
    """If mapped=True, the original dosage should not contain this term."""
    bad_rows = lookup_output.filter(col("mapped") == "true").filter(
        lower(col("dosage")).contains(term.lower())
    )
    count = bad_rows.count()
    assert count == 0, (
        f"{count} row(s) marked mapped=True contain '{term}'. "
        f"Examples: {[r['dosage'] for r in bad_rows.select('dosage').limit(5).collect()]}"
    )


@pytest.mark.parametrize("element_key", ELEMENT_KEYS)
def test_clean_and_captured_always_paired(lookup_output, element_key):
    """_clean and _captured must both be populated or both be null."""
    clean_col = f"{element_key}_clean"
    captured_col = f"{element_key}_captured"

    clean_without_captured = lookup_output.filter(col(clean_col).isNotNull()).filter(
        col(captured_col).isNull()
    )
    captured_without_clean = lookup_output.filter(col(captured_col).isNotNull()).filter(
        col(clean_col).isNull()
    )

    count_missing_captured = clean_without_captured.count()
    count_missing_clean = captured_without_clean.count()

    assert (
        count_missing_captured == 0
    ), f"{element_key}: {count_missing_captured} row(s) have _clean but no _captured"
    assert (
        count_missing_clean == 0
    ), f"{element_key}: {count_missing_clean} row(s) have _captured but no _clean"
