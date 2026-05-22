"""
Full Spark pipeline tests (end-to-end).

Test cases are defined in dosage_repo/to_test.py under `full_text`.
Add new cases there — they'll be picked up automatically on next pytest run.

These tests run the complete extraction pipeline via run_extraction_pipeline():
  spaCy init → UDF extraction → regex extras → buckets → validation

The pipeline is run ONCE per batch (capture / exclude) via module-scoped fixtures
to avoid repeated spaCy + broadcast setup that exhausts executor memory.
"""

import sys
import os
import pytest

# sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dosage_instructions.to_test import full_text
from dosage_instructions.model.matcher_run import run_extraction_pipeline

# ─── Batched pipeline fixtures ────────────────────────────────────────────────


@pytest.fixture(scope="module")
def capture_results(spark):
    """Run pipeline once on all capture inputs, return {raw_input: Row}."""
    texts = list(full_text["capture"].keys())
    df = spark.createDataFrame([(t,) for t in texts], ["dosage"])
    result = run_extraction_pipeline(df)
    rows = result.collect()
    return {row["dosage"]: row for row in rows}


@pytest.fixture(scope="module")
def exclude_results(spark):
    """Run pipeline once on all exclude inputs, return {raw_input: Row}."""
    texts = full_text["exclude"]
    df = spark.createDataFrame([(t,) for t in texts], ["dosage"])
    result = run_extraction_pipeline(df)
    rows = result.collect()
    return {row["dosage"]: row for row in rows}


# ─── Data-driven: full_text from to_test.py ───────────────────────────────────


@pytest.mark.parametrize(
    "input_text,expected_buckets",
    full_text["capture"].items(),
    ids=list(full_text["capture"].keys()),
)
def test_buckets_capture(input_text, expected_buckets, capture_results):
    """Full pipeline should produce expected buckets string."""
    row = capture_results.get(input_text)
    if row is None:
        pytest.fail(
            f"\n  Input '{input_text}' not found in pipeline output. "
            f"Preprocessing may have changed dosage_lower."
        )
    if row["buckets"] != expected_buckets:
        from dosage_instructions.model.constants import bucket_order

        elements_found = []
        for elem in bucket_order:
            clean_col = f"{elem}_clean"
            captured_col = f"{elem}_captured"
            if clean_col in row.asDict() and row[clean_col]:
                captured = row[captured_col] if captured_col in row.asDict() else "?"
                elements_found.append(
                    f"    {elem}: '{row[clean_col]}' (captured: '{captured}')"
                )
        elements_str = "\n".join(elements_found) if elements_found else "    (none)"
        assert False, (
            f"\n  Input:    '{input_text}'"
            f"\n  Expected: '{expected_buckets}'"
            f"\n  Got:      '{row['buckets']}'"
            f"\n  Elements matched:\n{elements_str}"
        )


@pytest.mark.parametrize("input_text", full_text["exclude"], ids=full_text["exclude"])
def test_buckets_exclude(input_text, exclude_results):
    """These inputs should be flagged as excluded (not fully mapped)."""
    row = exclude_results.get(input_text)
    if row is None:
        pytest.fail(
            f"\n  Input '{input_text}' not found in pipeline output. "
            f"Preprocessing may have changed dosage_lower."
        )
    if row["mapped"] is not False and row["exclude"] is None:
        from dosage_instructions.model.constants import bucket_order

        elements_found = []
        for elem in bucket_order:
            clean_col = f"{elem}_clean"
            captured_col = f"{elem}_captured"
            if clean_col in row.asDict() and row[clean_col]:
                captured = row[captured_col] if captured_col in row.asDict() else "?"
                elements_found.append(
                    f"    {elem}: '{row[clean_col]}' (captured: '{captured}')"
                )
        elements_str = "\n".join(elements_found) if elements_found else "    (none)"
        assert False, (
            f"\n  Input:    '{input_text}'"
            f"\n  Expected: mapped=False or exclude is set"
            f"\n  Got:      mapped={row['mapped']}, exclude={row['exclude']}"
            f"\n  Buckets:  '{row['buckets']}'"
            f"\n  Elements matched:\n{elements_str}"
        )


# ─── Structural tests ─────────────────────────────────────────────────────────


class TestPipelineOutputStructure:
    """Verify the pipeline produces expected columns and types."""

    @pytest.fixture(scope="class")
    def pipeline_result(self, spark):
        df = spark.createDataFrame(
            [("take 2 tablets every day",)],
            ["dosage"],
        )
        return run_extraction_pipeline(df)

    def test_has_buckets_column(self, pipeline_result):
        assert "buckets" in pipeline_result.columns

    def test_has_dosage_elements_column(self, pipeline_result):
        assert "dosage_elements" in pipeline_result.columns

    def test_has_mapped_column(self, pipeline_result):
        assert "mapped" in pipeline_result.columns

    def test_has_exclude_column(self, pipeline_result):
        assert "exclude" in pipeline_result.columns

    def test_buckets_not_empty(self, pipeline_result):
        row = pipeline_result.select("buckets").collect()[0]
        assert row["buckets"] is not None
        assert len(row["buckets"]) > 0


class TestFullyMappedInput:
    """An input that is fully parsed should have mapped=True and empty spare."""

    @pytest.fixture(scope="class")
    def result_row(self, spark):
        df = spark.createDataFrame(
            [("take 2 tablets every day",)],
            ["dosage"],
        )
        result = run_extraction_pipeline(df)
        return result.collect()[0]

    def test_mapped_is_true(self, result_row):
        assert result_row["mapped"] is True

    def test_exclude_is_none(self, result_row):
        assert result_row["exclude"] is None

    def test_dosage_spare_is_empty(self, result_row):
        spare = result_row["dosage_spare"]
        assert spare is None or spare.strip() == ""


class TestEmptyInput:
    """Null or empty input should not crash the pipeline."""

    def test_empty_string(self, spark):
        df = spark.createDataFrame([("",)], ["dosage"])
        result = run_extraction_pipeline(df)
        row = result.select("buckets").collect()[0]
        assert row["buckets"] is not None

    def test_whitespace_only(self, spark):
        df = spark.createDataFrame([("   ",)], ["dosage"])
        result = run_extraction_pipeline(df)
        row = result.select("buckets").collect()[0]
        assert row["buckets"] is not None
