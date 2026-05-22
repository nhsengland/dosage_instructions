from transforms.api import transform_df, Input, Output, configure

from pyspark.sql import DataFrame

from dosage_instructions.data_preparation.functions import group_doses


@configure(["DRIVER_MEMORY_LARGE", "EXECUTOR_MEMORY_LARGE", "NUM_EXECUTORS_64"])
@transform_df(
    Output("ri.foundry.main.dataset.c8566ac0-9db3-44a1-8ecb-502fdd243eb2"),
    original_records=Input(
        "ri.foundry.main.dataset.24191af4-e8d3-441e-83a8-c67789ef8603"
    ),
)
def compute(original_records: DataFrame) -> DataFrame:
    return group_doses(original_records)
