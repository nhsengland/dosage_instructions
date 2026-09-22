"""
Tests for preprocess_dosage function.

Verifies that raw dosage text is correctly normalised before extraction:
  - Lowercased
  - Latin abbreviations expanded
  - Number words converted to digits
  - Units of measure normalised
  - Isolated terms replaced (daily → every day, twice → 2 times, etc.)
  - Excluded rows flagged
  - Trimmed and trailing dots stripped
"""

import pytest

from dosage_instructions.model.preprocessing import (
    preprocess_dosage,
    replace_preprocess,
    exclude_rows,
    add_dots_to_latin,
)
from dosage_instructions.model.constants import (
    latin_dict,
    replace_isolated_terms,
    exclude_list,
)
from dosage_instructions.to_test import preprocess_tests


class TestLowercasing:

    def test_uppercase_lowered(self, spark):
        df = spark.createDataFrame([("TAKE TWO TABLETS",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert result["dosage_lower"] == result["dosage_lower"].lower()

    def test_mixed_case(self, spark):
        df = spark.createDataFrame([("Take One Tablet Daily",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "Take" not in result["dosage_lower"]
        assert "One" not in result["dosage_lower"]


class TestLatinExpansion:

    def test_od_becomes_every_day(self, spark):
        df = spark.createDataFrame([("od",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "every day" in result["dosage_lower"]

    def test_bd_becomes_twice_daily(self, spark):
        df = spark.createDataFrame([("bd",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "2 times every day" in result["dosage_lower"]

    def test_tds_becomes_3_times_daily(self, spark):
        df = spark.createDataFrame([("tds",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "3 times every day" in result["dosage_lower"]

    def test_dotted_latin_ac(self, spark):
        df = spark.createDataFrame([("a.c.",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "before food" in result["dosage_lower"]

    def test_prn_becomes_when_required(self, spark):
        df = spark.createDataFrame([("prn",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "when required" in result["dosage_lower"]


class TestWordToDigitConversion:

    def test_one_becomes_1(self, spark):
        df = spark.createDataFrame([("one tablet",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "1" in result["dosage_lower"]

    def test_two_becomes_2(self, spark):
        df = spark.createDataFrame([("two tablets",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "2" in result["dosage_lower"]

    def test_ten_becomes_10(self, spark):
        df = spark.createDataFrame([("ten drops",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "10" in result["dosage_lower"]


class TestIsolatedTermReplacement:

    def test_daily_becomes_every_day(self, spark):
        df = spark.createDataFrame([("take one daily",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "every day" in result["dosage_lower"]

    def test_twice_becomes_2_times(self, spark):
        df = spark.createDataFrame([("twice a day",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "2 times" in result["dosage_lower"]

    def test_weekly_becomes_every_week(self, spark):
        df = spark.createDataFrame([("weekly",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "every week" in result["dosage_lower"]

    def test_half_becomes_0_5(self, spark):
        df = spark.createDataFrame([("half a tablet",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "0.5" in result["dosage_lower"]


class TestExcludeRows:

    def test_excluded_row_flagged(self, spark):
        df = spark.createDataFrame([("oneone",)], ["dosage"])
        result = preprocess_dosage(df)
        row = result.collect()[0]
        assert row["exclude"] is not None and row["exclude"] != ""

    def test_normal_row_not_excluded(self, spark):
        df = spark.createDataFrame([("take one tablet daily",)], ["dosage"])
        result = preprocess_dosage(df)
        row = result.collect()[0]
        assert row["exclude"] is None or row["exclude"] == ""


class TestTrimming:

    def test_leading_trailing_spaces_removed(self, spark):
        df = spark.createDataFrame([("  take one tablet  ",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert not result["dosage_lower"].startswith(" ")
        assert not result["dosage_lower"].endswith(" ")

    def test_trailing_dots_removed(self, spark):
        df = spark.createDataFrame([("take one tablet...",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert not result["dosage_lower"].endswith(".")


class TestFullPreprocessing:
    """End-to-end: raw text → fully preprocessed dosage_lower."""

    def test_combined_preprocessing(self, spark):
        df = spark.createDataFrame([("Take TWO Tablets Daily",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "take" in result["dosage_lower"]
        assert "2" in result["dosage_lower"]
        assert "every day" in result["dosage_lower"]

    def test_latin_with_dose(self, spark):
        df = spark.createDataFrame([("One tablet bd",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert "1 tablet" in result["dosage_lower"]
        assert "2 times every day" in result["dosage_lower"]

    def test_preserves_dosage_column(self, spark):
        df = spark.createDataFrame([("TAKE ONE",)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert result["dosage"] == "TAKE ONE"


# ─── DATA-DRIVEN TESTS (from to_test.py) ─────────────────────────────────────


class TestFullPreprocessingDataDriven:
    """End-to-end preprocessing: input → expected dosage_lower."""

    @pytest.mark.parametrize(
        "input_text,expected",
        list(preprocess_tests["full"].items()),
        ids=list(preprocess_tests["full"].keys()),
    )
    def test_full_preprocess(self, spark, input_text, expected):
        df = spark.createDataFrame([(input_text,)], ["dosage"])
        result = preprocess_dosage(df).collect()[0]
        assert result["dosage_lower"] == expected


class TestLowercasingDataDriven:
    """Lowercasing step only."""

    @pytest.mark.parametrize(
        "input_text,expected",
        list(preprocess_tests["lower"].items()),
        ids=list(preprocess_tests["lower"].keys()),
    )
    def test_lowercase(self, spark, input_text, expected):
        df = spark.createDataFrame([(input_text,)], ["dosage"])
        from pyspark.sql.functions import lower, col as col_

        result = df.withColumn("dosage_lower", lower(col_("dosage"))).collect()[0]
        assert result["dosage_lower"] == expected


class TestLatinExpansionDataDriven:
    """Latin abbreviation expansion step."""

    @pytest.mark.parametrize(
        "input_text,expected",
        list(preprocess_tests["latin"].items()),
        ids=list(preprocess_tests["latin"].keys()),
    )
    def test_latin(self, spark, input_text, expected):
        from pyspark.sql.functions import lower, col as col_

        df = spark.createDataFrame([(input_text,)], ["dosage"])
        df = df.withColumn("dosage_lower", lower(col_("dosage")))
        latin = add_dots_to_latin(latin_dict)
        df = replace_preprocess(latin, df, "dosage_lower", only_if_isolated=False)
        result = df.collect()[0]
        assert result["dosage_lower"] == expected


class TestWordsToDigitsDataDriven:
    """Word-to-digit conversion step (via Spark replace_preprocess)."""

    @pytest.mark.parametrize(
        "input_text,expected",
        list(preprocess_tests["words_to_digits"].items()),
        ids=list(preprocess_tests["words_to_digits"].keys()),
    )
    def test_words_to_digits(self, spark, input_text, expected):
        from pyspark.sql.functions import lower, col as col_
        from dosage_instructions.model.constants import WORD_TO_DIGIT

        df = spark.createDataFrame([(input_text,)], ["dosage"])
        df = df.withColumn("dosage_lower", lower(col_("dosage")))
        df = replace_preprocess(WORD_TO_DIGIT, df, "dosage_lower")
        result = df.collect()[0]
        assert result["dosage_lower"].strip() == expected


class TestIsolatedTermsDataDriven:
    """Isolated term replacement step."""

    @pytest.mark.parametrize(
        "input_text,expected",
        list(preprocess_tests["isolated_terms"].items()),
        ids=list(preprocess_tests["isolated_terms"].keys()),
    )
    def test_isolated_terms(self, spark, input_text, expected):
        from pyspark.sql.functions import lower, col as col_

        df = spark.createDataFrame([(input_text,)], ["dosage"])
        df = df.withColumn("dosage_lower", lower(col_("dosage")))
        df = replace_preprocess(replace_isolated_terms, df, "dosage_lower")
        result = df.collect()[0]
        assert result["dosage_lower"] == expected


class TestExcludeDataDriven:
    """Exclude rows step."""

    @pytest.mark.parametrize(
        "input_text,expected",
        list(preprocess_tests["exclude"].items()),
        ids=list(preprocess_tests["exclude"].keys()),
    )
    def test_exclude(self, spark, input_text, expected):
        from pyspark.sql.functions import lower, col as col_

        df = spark.createDataFrame([(input_text,)], ["dosage"])
        df = df.withColumn("dosage_lower", lower(col_("dosage")))
        df = exclude_rows(exclude_list, df, "dosage_lower")
        result = df.collect()[0]
        assert result["dosage_lower"] == expected
