from transforms.api import transform, Input, Output, configure

from pyspark.sql import DataFrame

import dosage_instructions.data_enrichment.functions as my_enrichment_functions


@configure(["DRIVER_MEMORY_LARGE", "EXECUTOR_MEMORY_LARGE", "NUM_EXECUTORS_64"])
@transform(
    transform_output=Output(
        "ri.foundry.main.dataset.ea624ad0-4666-4b49-adf5-f87c65ebb8e7"
    ),
    dosage_lookup=Input("ri.foundry.main.dataset.1a58c534-ab3e-4b7e-beea-93e47fe7321c"),
)
def compute(dosage_lookup, transform_output: DataFrame) -> DataFrame:

    df = dosage_lookup.dataframe()

    df_refined = my_enrichment_functions.refine_lookup_output_func(df)

    return transform_output.write_dataframe(df_refined)
