import re

from pyspark.sql import DataFrame
from pyspark.sql.types import StringType
from pyspark.sql.functions import (
    lower,
    trim,
    regexp_replace,
    when,
    udf,
    lit,
    col as col_,
)

from dosage_instructions.model.constants import (
    number_dict_options,
    latin_dict,
    preprocess_units_of_measure,
    exclude_list,
    replace_isolated_terms,
    replace_partofaword_terms,
    weird_terms,
)


def convert_words_to_digits(text: str) -> str:
    """
    Converts words from 1-10 to digits. Using this in initial preprocessing so that
    numbers can be picked up in the model using regex's \\d and [0-9].
    """

    result = re.sub(
        r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten)+\b",
        lambda x: " " + number_dict_options["word_to_digit"][x.group()] + " ",
        text,
    )
    return re.sub(r" {2,}", " ", result).strip()


def replace_preprocess(
    terms_to_replace: dict[str, str],
    df: DataFrame,
    col_name: str,
    only_if_isolated: bool = True,
    replacer_is_key: bool = False,
    reverse: bool = False,
) -> DataFrame:
    """
    Replace key from dictionary with value in all instances within df[col_name].

    Inputs:
    terms_to_replace is a dictionary where the key is the item to replace, value is the replacer
    df: pySpark.DataFrame
    col_name: specific column to make the replacements on
    only_if_isolated: Bool. Default = True
        Keep true for terms like "om" where you only want to replace them if they're alone
        Change to false if you want to find the term in any occurence, even within words
    replacer_is_key: defaut False. Make true for input dict's with the replacer in the key and items_to_replace
        in the value, written as a list.
        False example: if dict is written as "hr": "hour"
        True example: if dict is written as "hour": ["hr", "hrs", "hours"].
    reverse: swap the terms and the meanings for resersing the initial preprocessing. Useful for items changed
    only for coding purposes, such as "evening meal": "eveningmeal"
    """

    for term, meaning in terms_to_replace.items():
        # reverse inputs if reverse=True
        if reverse or replacer_is_key:
            swap = [term, meaning]
            meaning = swap[0]
            term = swap[1]

        # convert to list if not already
        if isinstance(term, str):
            term = [term]
        elif isinstance(term, list):
            term = term
        else:
            raise AssertionError(
                "dict values must be string or list for this function to work."
            )

        for i in term:
            # add \\b if only_if_isolated is True
            if only_if_isolated:
                replace_term = rf"\b{i}\b"
            else:
                replace_term = rf"{i}"

            df = df.withColumn(
                col_name, regexp_replace(col_name, replace_term, meaning)
            )

    df = df.withColumn(col_name, regexp_replace(col_name, r"\s{2,}", " "))

    return df


def exclude_rows(exclude_list: list[str], df: DataFrame, col_name: str) -> DataFrame:
    """
    If cell in df[col_name] contains any items in the exclude list, the column "exclude" should
    be populated with the original text and the dosage column set to blank
    """

    exclude_str = "|".join([f"({item})" for item in exclude_list])
    df = df.withColumn(
        "exclude",
        when(col_(col_name).rlike(exclude_str), lit("removed")).otherwise(lit(None)),
    ).withColumn(
        col_name,
        when(col_(col_name).rlike(exclude_str), lit("")).otherwise(col_(col_name)),
    )
    return df


def add_dots_to_latin(latin: dict):
    """
    Uses \\b at the start and (?!\\w) at the end to avoid matching inside words
    while still consuming a trailing dot.
    """
    new_dict = {}
    for key, value in latin.items():
        dotted_key = r"\b" + r"\.?".join(list(key)) + r"\.?(?!\w)"
        new_dict[dotted_key] = value
    return new_dict


def preprocess_dosage(df):
    """
    Preprocesses raw dosage text into normalised `dosage_lower` column.

    Input:  DataFrame with a `dosage` column (raw text).
    Output: Same DataFrame with `dosage_lower` added (lowercased, latin expanded,
            words→digits, units normalised, terms replaced, trimmed).
    """
    dosage_col_name = "dosage_lower"
    convert_udf = udf(convert_words_to_digits, StringType())

    df = df.withColumn(dosage_col_name, lower(col_("dosage")))

    latin = add_dots_to_latin(latin_dict)
    df = replace_preprocess(latin, df, dosage_col_name, only_if_isolated=False)

    df = exclude_rows(exclude_list, df, dosage_col_name)

    df = df.withColumn(dosage_col_name, convert_udf(col_(dosage_col_name)))

    df = replace_preprocess(
        preprocess_units_of_measure,
        df,
        dosage_col_name,
        replacer_is_key=True,
        only_if_isolated=False,
    )
    df = replace_preprocess(replace_isolated_terms, df, dosage_col_name)
    df = replace_preprocess(
        replace_partofaword_terms, df, dosage_col_name, only_if_isolated=False
    )
    df = replace_preprocess(weird_terms, df, dosage_col_name, only_if_isolated=False)

    df = df.withColumn(dosage_col_name, trim(col_(dosage_col_name)))
    df = df.withColumn(
        dosage_col_name, regexp_replace(col_(dosage_col_name), r"\.+$", "")
    )
    df = df.withColumn(
        dosage_col_name, regexp_replace(col_(dosage_col_name), r"^\.\s*", "")
    )
    df = df.withColumn(
        dosage_col_name, regexp_replace(col_(dosage_col_name), r"\.\s*\.", ".")
    )

    return df
