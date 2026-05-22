from transforms.api import transform, Input, Output, configure

from pyspark.sql import DataFrame

from dosage_instructions.data_enrichment.functions import refine_lookup_output_func


@configure(["DRIVER_MEMORY_LARGE", "EXECUTOR_MEMORY_LARGE", "NUM_EXECUTORS_64"])
@transform(
    transform_output=Output(
        "ri.foundry.main.dataset.c9461cdc-dc03-4ae0-b35b-93542ce28704"
    ),
    dosage_lookup=Input("ri.foundry.main.dataset.1a58c534-ab3e-4b7e-beea-93e47fe7321c"),
)
def compute(dosage_lookup, transform_output: DataFrame) -> DataFrame:

    df = dosage_lookup.dataframe()

    df_refined = refine_lookup_output_func(df)

    return transform_output.write_dataframe(df_refined)
