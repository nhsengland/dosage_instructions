"""
Regression test for doseRange_high population from dose_QuantityValueAndMaxOnly.

Bug: refine_lookup_output_func used `_arr_has(df, "doseRange_low")` to decide
whether doseRange element was the source. After the first withColumn overwrote
doseRange_low with the QVMO value, the condition resolved True for the second
withColumn (doseRange_high), causing it to read the original EMPTY doseRange_high
instead of dose_QuantityValueAndMaxOnly_valueMax.

Fix: Check doseRange_clean (StringType, never overwritten) instead.
"""

import pytest
from pyspark.sql import Row
from pyspark.sql.types import ArrayType, StringType, StructField, StructType

from dosage_instructions.data_enrichment.functions import refine_lookup_output_func


@pytest.fixture()
def qvmo_row(spark):
    """DataFrame simulating a lookup row where dose_QuantityValueAndMaxOnly matched (not doseRange)."""
    schema = StructType(
        [
            StructField("dosage", StringType(), True),
            StructField("mapped", StringType(), True),
            # doseRange element NOT matched — these are empty
            StructField("doseRange_clean", StringType(), True),
            StructField("doseRange_low", ArrayType(StringType()), True),
            StructField("doseRange_high", ArrayType(StringType()), True),
            StructField("doseRange_units", ArrayType(StringType()), True),
            StructField("doseRange_spoonsize", ArrayType(StringType()), True),
            # dose_QuantityValueAndMaxOnly matched
            StructField("dose_QuantityValueAndMaxOnly_clean", StringType(), True),
            StructField(
                "dose_QuantityValueAndMaxOnly_value", ArrayType(StringType()), True
            ),
            StructField(
                "dose_QuantityValueAndMaxOnly_valueMax", ArrayType(StringType()), True
            ),
            # Other required columns (empty/null)
            StructField("doseQuantity_clean", StringType(), True),
            StructField("doseQuantity_quantity", ArrayType(StringType()), True),
            StructField("doseQuantity_units", ArrayType(StringType()), True),
            StructField("doseQuantity_spoonsize", ArrayType(StringType()), True),
            StructField("dose_QuantityValueOnly_clean", StringType(), True),
            StructField("dose_QuantityValueOnly_value", ArrayType(StringType()), True),
            StructField("milligramValue_clean", StringType(), True),
            StructField("milligramValue_value", ArrayType(StringType()), True),
            StructField(
                "milligramValue_milligram_units", ArrayType(StringType()), True
            ),
            StructField("milligramMax_clean", StringType(), True),
            StructField("milligramMax_value", ArrayType(StringType()), True),
            StructField("milligramMax_valueMax", ArrayType(StringType()), True),
            StructField("milligramMax_milligram_units", ArrayType(StringType()), True),
        ]
    )
    data = [
        (
            "1-2 once every day",  # dosage
            "True",  # mapped
            None,  # doseRange_clean — NOT matched
            [],  # doseRange_low — empty
            [],  # doseRange_high — empty
            [],  # doseRange_units
            [],  # doseRange_spoonsize
            "1 to 2",  # dose_QuantityValueAndMaxOnly_clean
            ["1"],  # dose_QuantityValueAndMaxOnly_value
            ["2"],  # dose_QuantityValueAndMaxOnly_valueMax
            None,  # doseQuantity_clean
            [],  # doseQuantity_quantity
            [],  # doseQuantity_units
            [],  # doseQuantity_spoonsize
            None,  # dose_QuantityValueOnly_clean
            [],  # dose_QuantityValueOnly_value
            None,  # milligramValue_clean
            [],  # milligramValue_value
            [],  # milligramValue_milligram_units
            None,  # milligramMax_clean
            [],  # milligramMax_value
            [],  # milligramMax_valueMax
            [],  # milligramMax_milligram_units
        ),
    ]
    return spark.createDataFrame(data, schema)


def test_dose_range_high_populated_from_qvmo(spark, qvmo_row):
    """doseRange_high must be '2' when dose_QuantityValueAndMaxOnly is the source."""
    result = refine_lookup_output_func(qvmo_row)
    row = result.collect()[0]
    assert (
        row["doseRange_low"] == "1"
    ), f"Expected doseRange_low='1', got {row['doseRange_low']!r}"
    assert (
        row["doseRange_high"] == "2"
    ), f"Expected doseRange_high='2', got {row['doseRange_high']!r}"


def test_dose_range_low_populated_from_actual_dose_range(spark):
    """When doseRange element IS matched, its own low/high are preserved."""
    schema = StructType(
        [
            StructField("dosage", StringType(), True),
            StructField("mapped", StringType(), True),
            StructField("doseRange_clean", StringType(), True),
            StructField("doseRange_low", ArrayType(StringType()), True),
            StructField("doseRange_high", ArrayType(StringType()), True),
            StructField("doseRange_units", ArrayType(StringType()), True),
            StructField("doseRange_spoonsize", ArrayType(StringType()), True),
            StructField("dose_QuantityValueAndMaxOnly_clean", StringType(), True),
            StructField(
                "dose_QuantityValueAndMaxOnly_value", ArrayType(StringType()), True
            ),
            StructField(
                "dose_QuantityValueAndMaxOnly_valueMax", ArrayType(StringType()), True
            ),
            StructField("doseQuantity_clean", StringType(), True),
            StructField("doseQuantity_quantity", ArrayType(StringType()), True),
            StructField("doseQuantity_units", ArrayType(StringType()), True),
            StructField("doseQuantity_spoonsize", ArrayType(StringType()), True),
            StructField("dose_QuantityValueOnly_clean", StringType(), True),
            StructField("dose_QuantityValueOnly_value", ArrayType(StringType()), True),
            StructField("milligramValue_clean", StringType(), True),
            StructField("milligramValue_value", ArrayType(StringType()), True),
            StructField(
                "milligramValue_milligram_units", ArrayType(StringType()), True
            ),
            StructField("milligramMax_clean", StringType(), True),
            StructField("milligramMax_value", ArrayType(StringType()), True),
            StructField("milligramMax_valueMax", ArrayType(StringType()), True),
            StructField("milligramMax_milligram_units", ArrayType(StringType()), True),
        ]
    )
    data = [
        (
            "1-2 tablets every day",
            "True",
            "1 to 2 tablets",  # doseRange_clean — MATCHED
            ["1"],  # doseRange_low
            ["2"],  # doseRange_high
            ["tablet"],  # doseRange_units
            [],  # doseRange_spoonsize
            None,  # dose_QuantityValueAndMaxOnly_clean — NOT matched
            [],
            [],
            None,
            [],
            [],
            [],  # doseQuantity
            None,
            [],  # dose_QuantityValueOnly
            None,
            [],
            [],  # milligramValue
            None,
            [],
            [],
            [],  # milligramMax
        ),
    ]
    df = spark.createDataFrame(data, schema)
    result = refine_lookup_output_func(df)
    row = result.collect()[0]
    assert row["doseRange_low"] == "1"
    assert row["doseRange_high"] == "2"
