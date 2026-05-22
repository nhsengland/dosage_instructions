from transforms.api import transform, Input, Output, incremental, configure

from pyspark.sql.functions import (
    col as col_,
    current_timestamp,
    lit,
    count,
    sum as sum_,
)

from dosage_instructions.model.config import config
from dosage_instructions.model.matcher_classes import lookup_schema
from dosage_instructions.model.matcher_run import run_extraction_pipeline
from dosage_instructions.model.preprocessing import preprocess_dosage


@configure(["DRIVER_MEMORY_LARGE", "EXECUTOR_MEMORY_LARGE"])
@incremental()
@transform(
    lookup_output=Output(
        "ri.foundry.main.dataset.1a58c534-ab3e-4b7e-beea-93e47fe7321c"
    ),
    unioned_input=Input("ri.foundry.main.dataset.a3ab8f15-f4d2-416e-8c4e-2b0c3b4157aa"),
)
def compute(lookup_output, unioned_input, ctx):

    raw_input = unioned_input.dataframe("current")

    key_col = "dosage_lower"
    snapshot_ts = current_timestamp()

    # ------------ Preprocessing (replaces setup_preprep) --------------

    preprocessed = preprocess_dosage(raw_input)

    df_grouped = preprocessed.groupBy("dosage_lower", "is_test").agg(
        count("dosage_count").alias("dosage_frequency"),
        sum_("dosage_count").alias("dosage_count"),
    )

    # ------------ Anti-join section --------------
    # Only process doses that haven't been added to lookup yet

    try:
        lookup_output_previous = lookup_output.dataframe(
            "previous", schema=lookup_schema
        )
    except Exception:
        lookup_output_previous = ctx.spark_session.createDataFrame(
            [], schema=lookup_schema
        )

    if config.get("fresh_start", False):
        right_only = df_grouped
    else:
        # 1) Ensure join key types match
        left_key_type = dict(
            (f.name, f.dataType) for f in lookup_output_previous.schema.fields
        )[key_col]
        right_key_type = dict((f.name, f.dataType) for f in df_grouped.schema.fields)[
            key_col
        ]
        if str(left_key_type) != str(right_key_type):
            df_grouped = df_grouped.withColumn(
                key_col, col_(key_col).cast(left_key_type)
            )
    # 2) Find rows not yet in lookup
    right_only = df_grouped.alias("r").join(
        lookup_output_previous.select(key_col).dropDuplicates().alias("l"),
        on=key_col,
        how="left_anti",
    )

    # 3) Project into lookup schema
    def project_to_schema(df, target_schema):
        exprs = []
        df_cols = set(df.columns)
        for field in target_schema.fields:
            name = field.name
            if name in df_cols:
                exprs.append(col_(name).cast(field.dataType).alias(name))
            else:
                exprs.append(lit(None).cast(field.dataType).alias(name))
        return df.select(*exprs)

    # ------------ Top batch section --------------

    top_unmapped = right_only.orderBy(
        col_("is_test").desc_nulls_last(), col_("dosage_count").desc()
    ).limit(config["batch_size"])

    top_unmapped_doses = project_to_schema(top_unmapped, lookup_output_previous.schema)

    final = top_unmapped_doses.withColumn("_snapshot_ts", snapshot_ts)

    # ------------ MODEL SECTION --------------

    df_assessed = run_extraction_pipeline(final, snapshot_ts)

    # ------------ Rejoin to full preprocessed data --------------

    # Drop columns from df_assessed that already exist in preprocessed to avoid clashes
    preproc_cols = set(preprocessed.columns)
    cols_to_drop = [
        c for c in df_assessed.columns if c in preproc_cols and c != key_col
    ]
    df_assessed_clean = df_assessed.drop(*cols_to_drop)

    df_rejoined = preprocessed.join(df_assessed_clean, on=key_col, how="inner")

    return lookup_output.write_dataframe(df_rejoined)


"""
-----------WIPING THE LOOKUP TABLE FOR REFRESH -------------------

- DON'T delete the lookup table.
- This second transform, which is commented out resets the lookup table.
To do a full reset of the lookup, use comment out the first transform, and
uncomment this one.
Run build. This will wipe the lookup table. Then recomment the second transform,
uncomment the first transform and run again as normal (see above).

Note:
The lookup refresh method is a workaround due to foundry limitations - if foundry
is updated this workaround should be removed and replaced with:
- Output should take the input "mode"="overwrite",
- or the table itself can be rolled back to when it was empty.

-----------WIPING THE LOOKUP TABLE FOR REFRESH -------------------
"""
"""

@transform(
    lookup_output=Output(
        "ri.foundry.main.dataset.1a58c534-ab3e-4b7e-beea-93e47fe7321c"
    ),
)
def compute(lookup_output, ctx):
    empty_lookup = ctx.spark_session.createDataFrame([], schema=lookup_schema)

    return empty_lookup

"""
