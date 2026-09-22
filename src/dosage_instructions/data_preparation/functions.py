from pyspark.sql import DataFrame


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
