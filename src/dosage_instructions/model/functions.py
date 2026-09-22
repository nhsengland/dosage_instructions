import re

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StringType
from pyspark.sql.window import Window


def remove_first_match(text: str, pattern: str, element_key: str) -> str:
    """
    Replaces the first element pattern found with the *element_name* for identifying and
    controlling sentence order of instruction
    """
    if text is None:
        return None
    return re.sub(pattern, f"*{element_key}*", text, count=1)


def reg_extract_and_tag_element(
    df: DataFrame, dosage_col_name: str, new_col_name: str, col_options: list[str]
) -> DataFrame:
    """
    Extracts the first match from the 'dosage' column using a regex pattern,
    stores it in a new column 'element_clean', and replaces the matched text
    in the original string with '*element_name*' for identification.
    """

    # Sort longest-first so more-specific patterns win over shorter substrings.
    # e.g. "for blood pressure control" must beat "for blood pressure",
    # "for your mood and sleep" must beat "for your mood".
    pattern = "|".join(sorted(col_options, key=len, reverse=True))
    element_key = new_col_name.removesuffix("_clean")

    # Define udf
    remove_first_match_udf = F.udf(
        lambda text: remove_first_match(text, pattern, element_key), StringType()
    )

    df = df.withColumn(
        new_col_name, F.regexp_extract(dosage_col_name, pattern, 0)
    ).withColumn(dosage_col_name, remove_first_match_udf(df[dosage_col_name]))

    return df


def get_all_combinations(
    items_dict: dict, odd_spellings: dict = {}, how: list = ["{prefix}{option}{suffix}"]
) -> tuple[dict, list]:
    """
    Run through and create all the combinations of these words together.
    E.g. "in both eyes" from how = [r"{prefix} {next_prefix} {options}{suffix}"]

    Input:
        items_dict: dictionary with keys options, prefix, next_prefix, suffix; each have a list of wording options
        odd_spellings: anything required but spelled slightly differently when extended.
            e.g. day becomes daily, not dayly.
        how: list of orders to try the words. Consider if next_prefix is needed and if spaces are required.
            when required separately, provide as different items in the list.
            e.g. ["{prefix}{option}", "{option}{suffix}"]
    """
    if "next_prefixes" not in items_dict:
        items_dict["next_prefixes"] = [""]

    if how:  # check this works for both together and separate then remove
        combination_dict = {}
        for option in items_dict["options"]:
            combination_dict[option] = []
            for i_how in how:
                combination_dict[option].extend(
                    [
                        i_how.format(
                            option=option,
                            prefix=prefix,
                            next_prefix=next_prefix,
                            suffix=suffix,
                        )
                        for prefix in items_dict["prefixes"]
                        for next_prefix in items_dict["next_prefixes"]
                        for suffix in items_dict["suffixes"]
                    ]
                )
            for correct, incorrect in odd_spellings.items():
                combination_dict[option] = [
                    re.sub(incorrect, correct, item).strip()
                    for item in combination_dict[option]
                ]
    combination_list = [
        phrase for phrases in combination_dict.values() for phrase in phrases
    ]

    return combination_dict, combination_list


def apply_row_selection(df: DataFrame, min_count: int | None) -> DataFrame:
    """
    Apply optional row-selection filter to a grouped dosage DataFrame.

    Uses a window partition by dosage_lower: computes max(dosage_count) per group
    and keeps only groups whose max meets the min_count threshold.

    Parameters
    ----------
    min_count : int or None
        Keep only dosage_lower groups whose max(dosage_count) >= this value.
        Set to None to disable filtering.
    """
    if min_count is not None:
        w = Window.partitionBy("dosage_lower")
        df = df.withColumn("_max_dosage_count", F.max("dosage_count").over(w))
        df = df.filter(F.col("_max_dosage_count") >= min_count)
        df = df.drop("_max_dosage_count")

    return df


"""
These functions aren't used, but keeping in case useful in a later iteration.

def satisfies_group_constraints(seq, groups):
    "checks that there isn't more than one item per group in the sentence"
    for group in groups:
        present = {w for w in seq if w in group}
        if len(present) > 1:
            return False
    return True


def ordered_subsequences(order, max_len=None, groups=None):
    "Generate all ordered subsequences (no repeats), optionally filtered by group constraints."
    n = len(order)
    min_len = 1
    if max_len is None or max_len > n:
        max_len = n
    out = []
    for k in range(min_len, max_len + 1):
        for idxs in combinations(range(n), k):
            seq = [order[i] for i in idxs]
            if groups and not satisfies_group_constraints(seq, groups):
                continue
            out.append(seq)
    return out
"""
