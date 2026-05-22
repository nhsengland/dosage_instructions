from transforms.api import transform_df, Input, Output

from pyspark.sql.functions import lit
from pyspark.sql import DataFrame


@transform_df(
    Output("ri.foundry.main.dataset.a3ab8f15-f4d2-416e-8c4e-2b0c3b4157aa"),
    full_real_input=Input(
        "ri.foundry.main.dataset.c8566ac0-9db3-44a1-8ecb-502fdd243eb2"
    ),
    test40_input=Input("ri.foundry.main.dataset.f8da5b11-c101-4b2c-ba11-e9619cbf000e"),
)
def compute(full_real_input: DataFrame, test40_input: DataFrame) -> DataFrame:
    full_real_input = full_real_input.withColumn("is_test", lit(False))
    test40_input = test40_input.withColumn("is_test", lit(True))
    return test40_input.unionByName(full_real_input)
