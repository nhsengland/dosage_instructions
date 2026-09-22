from pyspark.sql import DataFrame
from pyspark.sql import functions as F

import dosage_instructions.model.constants as myconstants


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
                col_name, F.regexp_replace(col_name, replace_term, meaning)
            )

    df = df.withColumn(col_name, F.regexp_replace(col_name, r"\s{2,}", " "))

    return df


def exclude_rows(exclude_list: list[str], df: DataFrame, col_name: str) -> DataFrame:
    """
    If cell in df[col_name] contains any items in the exclude list, the column "exclude" should
    be populated with the original text and the dosage column set to blank
    """

    exclude_str = "|".join([f"({item})" for item in exclude_list])
    df = df.withColumn(
        "exclude",
        F.when(
            F.col(col_name).rlike(exclude_str), F.lit("general_fail: removed")
        ).otherwise(F.lit(None)),
    ).withColumn(
        col_name,
        F.when(F.col(col_name).rlike(exclude_str), F.lit("")).otherwise(
            F.col(col_name)
        ),
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

    df = df.withColumn(dosage_col_name, F.lower(F.col("dosage")))

    # Normalise whitespace early — trim leading/trailing and collapse internal
    # tabs/multi-spaces to a single space before any pattern matching begins.
    df = df.withColumn(dosage_col_name, F.trim(F.col(dosage_col_name)))
    df = df.withColumn(
        dosage_col_name, F.regexp_replace(F.col(dosage_col_name), r"[ \t]+", " ")
    )

    latin = add_dots_to_latin(myconstants.latin_dict)
    df = replace_preprocess(latin, df, dosage_col_name, only_if_isolated=False)

    df = exclude_rows(myconstants.exclude_list, df, dosage_col_name)

    # Convert number words to digits (e.g. "two" → "2") using native Spark
    # regexp_replace via replace_preprocess — avoids Python UDF serialisation.
    df = replace_preprocess(myconstants.WORD_TO_DIGIT, df, dosage_col_name)

    df = replace_preprocess(
        myconstants.preprocess_units_of_measure,
        df,
        dosage_col_name,
        replacer_is_key=True,
        only_if_isolated=False,
    )
    df = replace_preprocess(myconstants.replace_isolated_terms, df, dosage_col_name)
    # Normalise date separators (/ and - → .) so dates tokenise as single tokens.
    # See docs/preprocessing_dates.md for full explanation.
    df = replace_preprocess(
        myconstants.normalise_date_separators,
        df,
        dosage_col_name,
        only_if_isolated=False,
    )
    df = replace_preprocess(
        myconstants.normalise_number_ranges, df, dosage_col_name, only_if_isolated=False
    )

    # Tidy up messy punctuation — stray dots and spaces at the start, end, and middle of dosage strings.
    df = df.withColumn(dosage_col_name, F.trim(F.col(dosage_col_name)))
    df = df.withColumn(
        dosage_col_name, F.regexp_replace(F.col(dosage_col_name), r"\.+$", "")
    )
    df = df.withColumn(
        dosage_col_name, F.regexp_replace(F.col(dosage_col_name), r"^\.\s*", "")
    )
    df = df.withColumn(
        dosage_col_name, F.regexp_replace(F.col(dosage_col_name), r"\.\s*\.", ".")
    )

    return df
