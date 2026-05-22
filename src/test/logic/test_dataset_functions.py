import pytest
from pyspark.sql import SparkSession
from pyspark.sql import Row

# Assume your function is named group_and_count_dosage
from dosage_instructions.data_preparation.functions import group_doses
from dosage_instructions.model.config import config


@pytest.fixture(scope="session")
def spark():
    return SparkSession.builder.appName("FoundryTest").getOrCreate()


def test_setup_group_doses(spark):
    # Arrange: Create sample input DataFrame
    data = [
        Row(dosage="Take once daily"),
        Row(dosage="Take twice daily"),
        Row(dosage="Take once daily"),
        Row(dosage="Take twice daily"),
        Row(dosage="Take twice daily"),
    ]
    df = spark.createDataFrame(data)

    # Act: Call the function
    result_df = group_doses(df)

    # Assert: Collect results and verify
    result = result_df.collect()
    # Convert to dict for easy checking
    result_dict = {
        row[config["dosage_col_name"]]: row["dosage_count"] for row in result
    }

    # Expected counts
    assert result_dict["Take twice daily"] == 3
    assert result_dict["Take once daily"] == 2

    # Check sorting: first row should have highest count
    assert result[0]["dosage_count"] >= result[1]["dosage_count"]
