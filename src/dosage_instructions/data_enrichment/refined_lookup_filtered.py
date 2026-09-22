from transforms.api import transform, Input, Output

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window

import dosage_instructions.model.constants as myconstants


@transform(
    transform_output=Output(
        "ri.foundry.main.dataset.e303b36c-3dfc-4c38-b0b9-3b9d919bb10c"
    ),
    refined_lookup=Input(
        "ri.foundry.main.dataset.ea624ad0-4666-4b49-adf5-f87c65ebb8e7"
    ),
)
def compute(refined_lookup, transform_output) -> DataFrame:
    """Filter refined lookup to dosage_lower groups with max(dosage_count) >= CUT_OFF_VALUE.

    This keeps only dosage instructions that appear frequently enough to be
    worth reviewing / validating, removing long-tail one-off entries.
    """
    df = refined_lookup.dataframe()
    df_mapped = df.filter(F.col("mapped"))

    # Window: partition by dosage_lower, compute max(dosage_count) per group
    w = Window.partitionBy("dosage_lower")
    df_mapped = df_mapped.withColumn(
        "max_dosage_count_per_dosage_lower", F.max("dosage_count").over(w)
    )

    # Keep only rows where the group max meets the cut-off
    df_filtered = df_mapped.filter(
        F.col("max_dosage_count_per_dosage_lower") >= myconstants.MIN_COUNT
    )

    # Drop the helper column — it's served its purpose
    df_filtered = df_filtered.drop("max_dosage_count_per_dosage_lower")

    return transform_output.write_dataframe(df_filtered)
