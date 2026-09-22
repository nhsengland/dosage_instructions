from transforms.api import transform, Input, Output, configure

from pyspark.sql import functions as F

from dosage_instructions.model.functions import apply_row_selection
from dosage_instructions.model.matcher_run import run_extraction_pipeline
import dosage_instructions.model.constants as myconstants
from dosage_instructions.model.preprocessing import preprocess_dosage


@configure(["DRIVER_MEMORY_LARGE", "EXECUTOR_MEMORY_LARGE"])
@transform(
    lookup_output=Output(
        "ri.foundry.main.dataset.1a58c534-ab3e-4b7e-beea-93e47fe7321c"
    ),
    unioned_input=Input("ri.foundry.main.dataset.a3ab8f15-f4d2-416e-8c4e-2b0c3b4157aa"),
)
def compute(lookup_output, unioned_input, ctx):
    raw_input = unioned_input.dataframe()

    key_col = "dosage_lower"
    snapshot_ts = F.current_timestamp()

    # ------------ Preprocessing --------------

    preprocessed = preprocess_dosage(raw_input)

    # Group by dosage_lower only — is_test doesn't affect extraction.
    # Including is_test in the groupBy would create duplicate rows for
    # dosage texts that appear in both real and test data, causing the
    # rejoin below to produce a cross product (doubling output rows).
    df_grouped = preprocessed.groupBy("dosage_lower").agg(
        F.sum("dosage_count").alias("dosage_count"),
    )

    df_grouped = df_grouped.orderBy(F.col("dosage_count").desc())

    # ------------ Optional row selection --------------
    # Window partition by dosage_lower: keeps only groups whose
    # max(dosage_count) >= min_count (mirrors refined_lookup_filtered logic).

    df_grouped = apply_row_selection(df_grouped, myconstants.MIN_COUNT)

    # ------------ MODEL SECTION --------------

    df_assessed = run_extraction_pipeline(
        df_grouped, snapshot_ts, spark_context=ctx.spark_session.sparkContext
    )

    # ------------ Rejoin to full preprocessed data --------------

    # Drop columns from df_assessed that already exist in preprocessed to avoid clashes (except exclude)
    preprocessed = preprocessed.drop("exclude")
    preproc_cols = set(preprocessed.columns)
    cols_to_drop = [
        c for c in df_assessed.columns if c in preproc_cols and c != key_col
    ]
    df_assessed_clean = df_assessed.drop(*cols_to_drop)

    df_rejoined = preprocessed.join(df_assessed_clean, on=key_col, how="inner")

    # Sort test rows first for debugging visibility, then by frequency
    df_rejoined = df_rejoined.orderBy(
        F.col("is_test").desc_nulls_last(), F.col("dosage_count").desc()
    )

    return lookup_output.write_dataframe(df_rejoined)
