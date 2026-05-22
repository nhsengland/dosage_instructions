from pyspark.sql import DataFrame

from dosage_instructions.model.config import config


def group_doses(df: DataFrame) -> DataFrame:
    """
    Groups the input DataFrame by dosage instruction, calculates the count of
    records for each instruction, and returns the result sorted by count in descending order.

    Steps:
        1. Group by the column 'dosage_instruction'.
        2. Compute a new column 'dosage_count' representing the number of occurrences per group.
        3. Sort the resulting DataFrame by 'dosage_count' in descending order.

    Parameters
    ----------
    df : pandas.DataFrame or pyspark.sql.DataFrame
        Input DataFrame containing at least a 'dosage_instruction' column.

    Returns
    -------
    pandas.DataFrame or pyspark.sql.DataFrame
        A DataFrame with columns:
            - dosage_instruction
            - dosage_count
        Sorted by dosage_count in descending order.
    """

    df_grouped = df.groupBy("dosage").count().withColumnRenamed("count", "dosage_count")

    return df_grouped.orderBy("dosage_count", ascending=False)


def map_doses_to_lookup(distinct_doses: DataFrame, lookup_df: DataFrame) -> DataFrame:
    """
    Joins the primary dataset to a lookup table, filters rows that are not yet mapped,
    and outputs only those unmapped records.

    Steps:
        1. Perform a join between `distinct_doses` and `lookup_df` on the dosage instruction.
        2. Identify rows where mapping information is missing (e.g., lookup columns are NULL).
        3. Return a DataFrame containing only these "not yet mapped" rows.

    Parameters
    ----------
    distinct_doses : pyspark.sql.DataFrame
        The main dataset containing records to be checked for mapping.
    lookup_df : pyspark.sql.DataFrame
        The lookup table that provides mapping information.

    Returns
    -------
    pyspark.sql.DataFrame
        A DataFrame of rows from `distinct_doses` that do not have a corresponding mapping
        in `lookup_df`. The schema matches `distinct_doses`.
    """

    lookup_is_empty = lookup_df.limit(1).count() == 0
    if config["rebuild_or_append_lookup"] == "append":
        if lookup_is_empty:
            df_merged = distinct_doses.join(lookup_df, on="dosage", how="left_anti")
            df_to_map = df_merged  # [df_merged["mapped"] == False]
        else:
            df_to_map = distinct_doses
    elif config["rebuild_or_append_lookup"] == "rebuild":
        df_to_map = distinct_doses
    else:
        raise AssertionError("Config must be set at append or restart")

    return df_to_map[["dosage", "dosage_count", "is_test"]]
