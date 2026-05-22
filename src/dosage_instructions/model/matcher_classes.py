import re as _re
from abc import ABC, abstractmethod

import pandas as pd
from pyspark.sql.functions import pandas_udf, col as col_
from pyspark.sql.types import (
    ArrayType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from dosage_instructions.model import constants as myconstants


class BaseElement(ABC):
    """
    Base class for the dosage-instruction *element*s — a logical section
    of a sentence that, when combined with other elements, forms the complete
    dosage instruction.

    Each element instance represents exactly one semantic piece (e.g., dose
    quantity, frequency, route). Elements are "fitted" with:
      - element_key (str): An identifier for the element instance.
      - element_split (Sequence[str]): The important tokens for this element,
        typically obtained from tokenization/regex extraction of the input text.

    The Element classes life cycle is standardized into these steps that
    subclasses implement:

      1) define_options: Discover element-specific words which may be present to help identify which element the
         part of the phrase is part of.
         This is can contain:
            self.options - the main word identifier (e.g. cholesterol)
            self.prefix - a single word or letter prefix to the self.options (e.g. to)
            self.next_prefix - a single word or letter next prefix to the self.options (e.g. lower)
            self.suffix - a single word or letter suffix to the self.options (e.g. level)
         these varables are used in the self.define_pattern() and may also be combined in the
         get_all_combinations() function for separate use.

      2) define_pattern: Specify one or more patterns that reliably
         identify this element in the text and attaches a
         **user-defined self.metadata** which describes where the important tokens sit inside those patterns
         (e.g. in "to be taken", the lemma=take can be found at position 2).
         Each pattern has it's own little docstring below called "Captures" which explains the type of phrase
         we're trying to capture with each pattern.

      3) phrase_parts: Declare which tokens/fields are the *important
         parts* of the element and define how to write the final phrase
         for this element (e.g. a format string or ordered parts list).

      4) Once defined, the element can enrich a dataset via `update_df(...)`, which:
      - Creates **per-token columns** derived from the self.element_split for debugging,
        review and to support downstream export to FHIR.
      - Produces **{element_key}_clean**, the rendered phrase for this
        element according to `phrase_parts(...)`. This value is intended for
        eventual placement into the “bucket” column later.

    - Subclasses must implement define_options(), define_pattern(), and
      phrase_parts(). The base class orchestrates common documentation, functions and
      column semantics; subclasses provide the content.
    """

    def __init__(self, nlp, matcher):
        """
        1) Set up nlp and matcher as part of the spacy.Matcher processing
        2) Initialize a new element with the elements
            element_key: class and element identifier
            element_split: important tokens within the element. Generally uses the naming
                convention found in fhir documentation.
        3) Define schema for extract_element_using_matcher()'s output

        Parameters
        ----------
        element_key : str
            Canonical identifier for this element.
        element_split : Sequence[str]
            Important tokens associated with this element.
        """

        self.nlp = nlp
        self.matcher = matcher

    @abstractmethod
    def define_options(self):
        pass

    @abstractmethod
    def define_pattern(self):
        """"""
        pass

    @abstractmethod
    def phrase_parts(self, span: str, found_dict: dict, token_dict: dict):
        pass

    def meta_creator(self, pattern_name):
        """
        Inititalise a new metadata key for each element and pattern.
        self.metadata is a user-defined metadata describes what position the important tokens sit inside each pattern
        (e.g. in "to be taken", the lemma=take can be found at position 2 - the third token).
        """
        self.metadata[f"{self.element_key}_{pattern_name}"] = {}

    def register_patterns_with_multiword(
        self, pattern_name, base_tokens, options, metadata
    ):
        """
        Register a pattern that supports both single-word and multi-word options.

        For single-word options, registers one pattern with {"LEMMA": {"IN": [...]}}
        at the end. For each multi-word option (e.g. "evening meal"), registers a
        separate pattern with individual token dicts appended.

        Negative metadata positions are shifted to account for the extra tokens in
        multi-word patterns. Positive positions are unchanged.

        Args:
            pattern_name: base name, e.g. "pattern4"
            base_tokens: token dicts up to (not including) the option slot
            options: full list of options (may contain multi-word strings)
            metadata: dict of {field: token_position} for the single-word version
        """
        single_opts = [o for o in options if " " not in o]
        multi_opts = [tuple(o.split()) for o in options if " " in o]

        if single_opts:
            self.meta_creator(pattern_name)
            pattern = base_tokens + [{"LEMMA": {"IN": single_opts}}]
            self.matcher.add(f"{self.element_key}_{pattern_name}", [pattern])
            self.metadata[f"{self.element_key}_{pattern_name}"] = metadata

        for i, words in enumerate(multi_opts):
            mw_name = f"{pattern_name}_mw{i}"
            self.meta_creator(mw_name)
            pattern = base_tokens[:]
            doc = self.nlp(" ".join(words))
            for token in doc:
                if token.pos_ == "NOUN":
                    pattern.append({"LEMMA": token.lemma_})
                else:
                    pattern.append({"LOWER": token.lower_})
            self.matcher.add(f"{self.element_key}_{mw_name}", [pattern])
            extra_tokens = len(words) - 1
            adjusted = {}
            for k, v in metadata.items():
                if isinstance(v, list):
                    adjusted[k] = v
                elif v < 0:
                    adjusted[k] = v - extra_tokens
                else:
                    adjusted[k] = v
            self.metadata[f"{self.element_key}_{mw_name}"] = adjusted


class MethodDirectElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "methodDirect"
    element_split = ["verb"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.method_config["options"]
        self.prefixes = myconstants.method_config["prefixes"]
        self.suffixes = myconstants.method_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}

        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [{"LOWER": "to", "OP": "?"}, {"TEXT": {"IN": self.options}}]
            # TODO maybe re-add "TAG": "VB" if benefit somewhere @ risk of some being missed
            # e.g. "every day take 1" may tag this as a NN noun
        )
        """
        Captures:
            to take
            take
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "verb": -1,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["verb"].append(token_dict["verb"])
        formatted_phrase = f"{found_dict['verb'][-1]}"
        return formatted_phrase, found_dict


class MethodPassiveElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "methodPassive"
    element_split = ["verb"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.method_config["options"]
        self.prefixes = myconstants.method_config["prefixes"]
        self.suffixes = myconstants.method_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}

        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "to"},
                {"LOWER": "be"},
                {"LOWER": {"IN": myconstants.method_config["past_participles"]}},
            ]
        )
        """
        Captures:
            to be taken. extracts "take"
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "verb": -1,
        }
        pattern_name = "pattern2"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": {"IN": myconstants.method_config["past_participles"]}},
            ]
        )
        """
        Captures:
            taken. extracts "take"
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "verb": -1,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["verb"].append(token_dict["verb_token"].lemma_)
        formatted_phrase = f"{found_dict['verb'][-1]}"
        return formatted_phrase, found_dict


class DoseQuantityElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "doseQuantity"
    element_split = ["quantity", "units", "spoonsize"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.unit_config["options"]
        self.prefixes = myconstants.unit_config["prefixes"]
        self.suffixes = myconstants.unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}

        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = [
            {"TEXT": {"REGEX": "^[0-9]$"}},
            {"LOWER": "x", "OP": "?"},
            {"IS_SPACE": True, "OP": "?"},
            {"LOWER": {"REGEX": r"^(5|2\.5)$"}},
            {"IS_SPACE": True, "OP": "?"},
            {"LOWER": {"REGEX": r"mls?"}},
            {"LEMMA": {"IN": ["spoon", "spoonful"]}},
        ]
        """
        Captures:
            4 x 5 ml spoonful
            4 5 ml spoonful  # should this be captured?
            4 x 5 ml spoon
            4 x 5 mls spoonful
            4 x 5ml spoonful
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", [self.pattern])
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "quantity": 0,
            "units": -1,
            "spoonsize": -3,
        }
        """
        Captures:
            4 tablets
            2 chewable tablets
            1 capsule
        """
        self.register_patterns_with_multiword(
            "pattern2",
            base_tokens=[{"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}}],
            options=self.options,
            metadata={"quantity": 0, "units": [1, None]},
        )

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        found_dict["quantity"].append(token_dict["quantity"])
        found_dict["units"].append(token_dict["units"])
        found_dict["spoonsize"].append(token_dict["spoonsize"])
        if pattern_name == "pattern1":
            formatted_phrase = f"{found_dict['quantity'][-1]} x {found_dict['spoonsize'][-1]}ml spoonfuls"
        elif pattern_name.startswith("pattern2"):
            formatted_phrase = f"{found_dict['quantity'][-1]} {found_dict['units'][-1]}"
        else:
            raise AssertionError(
                f"pattern_name: {pattern_name} is not accounted for in this section"
            )
        return formatted_phrase, found_dict


class DoseQuantityValueOnlyElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "dose_QuantityValueOnly"
    element_split = ["value"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.period_unit_config["options"]
        self.prefixes = myconstants.period_unit_config["prefixes"]
        self.suffixes = myconstants.period_unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
            ]
        )
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 0,
        }
        """
        Captures:
            1
            3.25
            0.5
            not 5.6
            not 120
        """

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(token_dict["value"])
        formatted_phrase = f"{found_dict['value'][-1]}"
        return formatted_phrase, found_dict


class DoseXMilliValueOnlyElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "doseXMilliValueOnly"
    element_split = ["value", "val_milli", "milli"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.milli_config["options"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"IS_SPACE": True, "OP": "?"},
                {"LOWER": "x"},
                {"IS_SPACE": True, "OP": "?"},
                {"LIKE_NUM": True},
                {"IS_SPACE": True, "OP": "?"},
                {"LOWER": {"IN": self.options}},
            ]
        )
        """
        Captures:
            120 x 42ml
            120 x 42 ml
            120 x 42 mls
            120 x 42mls
            12 42mls
            120 x42ml
            120x 42 ml
            120x42 ml
            120x42ml
            1 x 42ml
            3.25 x 42ml
            0.5 x 42ml
            4 x 42.6ml  # Qcall should we limit to only .25 .5?
            5.7 x 4.3ml
            5 x 4 millilitre
            5 x 4 millilitres
            5 x 4 milligram  # Qcall should we allow mgs?
            5 x 4 milligrams
            5 x 4 mg
            5 x 4 mgs
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 0,
            "val_milli": 2,
            "milli": 3,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(token_dict["value"])
        found_dict["val_milli"].append(token_dict["val_milli"])
        found_dict["milli"].append(token_dict["milli"])
        formatted_phrase = f"{found_dict['value'][-1]} x {found_dict['val_milli'][-1]} {found_dict['milli'][-1]}"
        return formatted_phrase, found_dict


class DoseQuantityValueAndMaxOnlyElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "dose_QuantityValueAndMaxOnly"
    element_split = ["value", "valueMax"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.period_unit_config["options"]
        self.prefixes = myconstants.period_unit_config["prefixes"]
        self.suffixes = myconstants.period_unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LOWER": {"IN": ["or", "to", "-"]}},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
            ]
        )
        """
        Captures:
            120 - 122 (with help from nlp.Defaults.infixes)
            1-2
            1 -2 (with help from replace: weird_terms)
            1- 2
            3.25 to 4
            0.5 or 1
            not 5.6 - 5.7
            not 4 then 5
        """

        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 0,
            "valueMax": 2,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(token_dict["value"])
        found_dict["valueMax"].append(token_dict["valueMax"])
        formatted_phrase = f"{found_dict['value'][-1]} to {found_dict['valueMax'][-1]}"
        return formatted_phrase, found_dict


class DoseRangeElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "doseRange"
    element_split = ["low", "high", "units", "spoonsize"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.unit_config["options"]
        self.prefixes = myconstants.unit_config["prefixes"]
        self.suffixes = myconstants.unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = [
            {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
            {"LOWER": {"IN": ["to", "or", "-"]}},
            {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
            {"LEMMA": {"IN": self.options}},
        ]
        """
        Captures:
            120 - 122 drops
            1-2 tables
            1 -2 sprays
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", [self.pattern])
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "low": 0,
            "high": 2,
            "units": 3,
        }
        pattern_name = "pattern2"
        self.meta_creator(pattern_name)
        self.pattern = [
            {"LOWER": "up"},
            {"LOWER": "to"},
            {"TEXT": {"REGEX": "^[0-9]$"}},
            {"LEMMA": {"IN": self.options}},
        ]
        """
        Captures:
            up to 5 tablets
            up to 1 spray
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", [self.pattern])
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "high": 2,
            "units": 3,
        }
        pattern_name = "pattern3"
        self.meta_creator(pattern_name)
        self.pattern = [
            {"TEXT": {"REGEX": "^[0-9]$"}},
            {"LOWER": {"IN": ["or", "to", "-"]}},
            {"TEXT": {"REGEX": "^[0-9]$"}},
            {"LOWER": "x", "OP": "?"},
            {"IS_SPACE": True, "OP": "?"},
            {"LOWER": {"REGEX": r"^(5|2\.5)$"}},
            {"IS_SPACE": True, "OP": "?"},
            {"LOWER": {"REGEX": r"mls?"}},
            {"LEMMA": {"IN": ["spoon", "spoonful"]}},
        ]
        """
        Captures:
            1-4 x 5 ml spoonful
            1-4 5 ml spoonful  # should this be captured?
            1-4 x 5 ml spoon
            1-4 x 5 mls spoonful
            1-4 x 5ml spoonful
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", [self.pattern])
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "low": 0,
            "high": 2,
            "units": -1,
            "spoonsize": -3,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        found_dict["units"].append(token_dict["units"])
        found_dict["low"].append(token_dict["low"])
        found_dict["high"].append(token_dict["high"])
        found_dict["spoonsize"].append(token_dict["spoonsize"])
        if pattern_name == "pattern1":
            formatted_phrase = f"{found_dict['low'][-1]} to {found_dict['high'][-1]} {found_dict['units'][-1]}"
        elif pattern_name == "pattern2":
            formatted_phrase = (
                f"up to {found_dict['high'][-1]} {found_dict['units'][-1]}"
            )
        elif pattern_name == "pattern3":
            formatted_phrase = f"{found_dict['low'][-1]} to {found_dict['high'][-1]} x {found_dict['spoonsize'][-1]}ml spoonfuls"
        else:
            raise AssertionError(
                f"pattern_name: {pattern_name} is not accounted for in this section"
            )
        return formatted_phrase, found_dict


class RateRatioElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "rateRatio"
    element_split = ["numerator", "denominator", "period_unit"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.period_unit_config["options"]
        self.prefixes = myconstants.period_unit_config["prefixes"]
        self.suffixes = myconstants.period_unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = [
            {"LOWER": "at"},
            {"LOWER": "a"},
            {"LOWER": "rate"},
            {"LOWER": "of"},
            {"LIKE_NUM": True},
            {"LOWER": "per"},
            {"LEMMA": {"IN": self.options}},
        ]
        """
        Captures:
            at a rate of 4 per day
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", [self.pattern])
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "numerator": 4,
            "period_unit": 6,
        }
        pattern_name = "pattern2"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "at"},
                {"LOWER": "a"},
                {"LOWER": "rate"},
                {"LOWER": "of"},
                {"LIKE_NUM": True},
                {"LOWER": "every"},
                {"LIKE_NUM": True},
                {"LEMMA": {"IN": self.options}},
            ]
        )
        """
        Captures:
            at a rate of 3 every 2 weeks
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "numerator": 4,
            "denominator": 6,
            "period_unit": 7,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        found_dict["numerator"].append(token_dict["numerator"])
        found_dict["denominator"].append(token_dict["denominator"])
        found_dict["period_unit"].append(token_dict["period_unit"])
        if pattern_name == "pattern1":
            formatted_phrase = f"at a rate of {found_dict['numerator'][-1]} per {found_dict['period_unit'][-1]}"
        elif pattern_name == "pattern2":
            formatted_phrase = (
                f"at a rate of {found_dict['numerator'][-1]} "
                f"every {found_dict['denominator'][-1]} {found_dict['period_unit'][-1]}"
            )
        else:
            raise AssertionError(
                f"pattern_name: {pattern_name} is not accounted for in this section"
            )
        return formatted_phrase, found_dict


class RateRangeElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "rateRange"
    element_split = ["low", "high", "special_unit"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.special_unit_config["options"]
        self.prefixes = myconstants.special_unit_config["prefixes"]
        self.suffixes = myconstants.special_unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}

        """
        Captures:
            at a rate of 1 to 4 litres per minute
            at a rate of 2 to 5 microgram per kilogram per hour
        """
        self.register_patterns_with_multiword(
            "pattern1",
            base_tokens=[
                {"LOWER": "at"},
                {"LOWER": "a"},
                {"LOWER": "rate"},
                {"LOWER": "of"},
                {"LIKE_NUM": True},
                {"LOWER": "to"},
                {"LIKE_NUM": True},
            ],
            options=self.options,
            metadata={"low": 4, "high": 6, "special_unit": [7, None]},
        )

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        found_dict["low"].append(token_dict["low"])
        found_dict["high"].append(token_dict["high"])
        found_dict["special_unit"].append(token_dict["special_unit"])
        if pattern_name.startswith("pattern1"):
            formatted_phrase = (
                f"at a rate of {found_dict['low'][-1]} to "
                f"{found_dict['high'][-1]} {found_dict['special_unit'][-1]}"
            )
        else:
            raise AssertionError(
                f"pattern_name: {pattern_name} is not accounted for in this section"
            )
        return formatted_phrase, found_dict


class RateQuantityElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "rateQuantity"
    element_split = ["value", "special_unit"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.special_unit_config["options"]
        self.prefixes = myconstants.special_unit_config["prefixes"]
        self.suffixes = myconstants.special_unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}

        """
        Captures:
            at a rate of 5 litres per minute
            at a rate of 2 microgram per kilogram per hour
        """
        self.register_patterns_with_multiword(
            "pattern1",
            base_tokens=[
                {"LOWER": "at"},
                {"LOWER": "a"},
                {"LOWER": "rate"},
                {"LOWER": "of"},
                {"LIKE_NUM": True},
            ],
            options=self.options,
            metadata={"value": 4, "special_unit": [5, None]},
        )

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        found_dict["value"].append(token_dict["value"])
        found_dict["special_unit"].append(token_dict["special_unit"])
        if pattern_name.startswith("pattern1"):
            formatted_phrase = f"at a rate of {found_dict['value'][-1]} {found_dict['special_unit'][-1]}"
        else:
            raise AssertionError(
                f"pattern_name: {pattern_name} is not accounted for in this section"
            )
        return formatted_phrase, found_dict


class DurationElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "durationValue"
    element_split = ["value", "period_units"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.period_unit_config["options"]
        self.prefixes = myconstants.period_unit_config["prefixes"]
        self.suffixes = myconstants.period_unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "over"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": self.options}},
            ]
        )
        """
        Captures:
            over 5 days
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 1,
            "period_units": 2,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(token_dict["value"])
        found_dict["period_units"].append(token_dict["period_units"])
        formatted_phrase = (
            f"over {found_dict['value'][-1]} {found_dict['period_units'][-1]}"
        )
        return formatted_phrase, found_dict
        # Qcall2 this is picking up aged over 15 years, 65 years. Remove year? Month problems too?


class DurationMaxElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "durationMax"
    element_split = ["value", "period_units"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.period_unit_config["options"]
        self.prefixes = myconstants.period_unit_config["prefixes"]
        self.suffixes = myconstants.period_unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": {"IN": ["maximum", "max"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": self.options}},
            ]
        )
        """
        Captures:
            max 5 weeks
            maximum 3 days
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 1,
            "period_units": 2,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(token_dict["value"])
        found_dict["period_units"].append(token_dict["period_units"])
        formatted_phrase = (
            f"maximum {found_dict['value'][-1]} {found_dict['period_units'][-1]}"
        )
        return formatted_phrase, found_dict


class FrequencyBareElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    This class should be ran after MethodDirectElement to avoid this element picking up the method in patterns ending
    with ".tobetaken".
    """

    element_key = "frequencyBare"
    element_split = ["frequency", "frequencyMax", "period_unit"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.period_unit_config["options"]
        self.prefixes = myconstants.period_unit_config["prefixes"]
        self.suffixes = myconstants.period_unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"TEXT": "times"},
                {"LEMMA": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            4 times per day
            2 times each week
            three times/day
            1 time a month
            twice every year
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "frequency": 0,
            "period_unit": 3,
        }
        pattern_name = "pattern1once"
        # Note: This is the same as pattern1 but with "once" instead of "# times". The naming is purely to help with
        # grouping similar patterns in phrase_parts()
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "once"},
                {"LEMMA": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            once a day
            once every fortnight
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "frequency": 0,
            "period_unit": 2,
        }
        pattern_name = "pattern2"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"ORTH": {"IN": ["to", "or", "-"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": "time"},
                {"LEMMA": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            1 to 3 times per week
            1-2 times a day
            4 or 5 times a year
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "frequency": 0,
            "frequencyMax": 2,
            "period_unit": 5,
        }
        pattern_name = "pattern3"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "up"},
                {"LOWER": "to"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": "time"},
                {"LEMMA": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            up to 6 times per week
            up to 1 time a day
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "frequencyMax": 2,
            "period_unit": 5,
        }

        pattern_name = "pattern3.once"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "up"},
                {"LOWER": "to"},
                {"LEMMA": "once"},
                {"LEMMA": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            up to once per week
            up to once a day
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "period_unit": 4,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        found_dict["frequency"].append(token_dict["frequency"])
        found_dict["frequencyMax"].append(token_dict["frequencyMax"])
        found_dict["period_unit"].append(token_dict["period_unit"])
        if pattern_name in ["pattern1"]:
            if found_dict["frequency"][-1] == 1:
                formatted_phrase = f"once per {found_dict['period_unit'][-1]}"
            elif found_dict["frequency"][-1] == 2:
                formatted_phrase = f"twice per {found_dict['period_unit'][-1]}"
            else:
                formatted_phrase = f"{found_dict['frequency'][-1]} times per {found_dict['period_unit'][-1]}"
        elif pattern_name in ["pattern1once"]:
            formatted_phrase = f"once per {found_dict['period_unit'][-1]}"
        elif pattern_name in ["pattern2"]:
            formatted_phrase = (
                f"{found_dict['frequency'][-1]} to {found_dict['frequencyMax'][-1]} "
                f"times per {found_dict['period_unit'][-1]}"
            )
        elif pattern_name in ["pattern3"]:
            formatted_phrase = f"up to {found_dict['frequencyMax'][-1]} times per {found_dict['period_unit'][-1]}"
        elif pattern_name in ["pattern3.once"]:
            formatted_phrase = f"up to once per {found_dict['period_unit'][-1]}"
        else:
            raise AssertionError(
                f"pattern_name: {pattern_name} is not accounted for in this section"
            )
        return formatted_phrase, found_dict


class FrequencyWithMethodElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    This class should be ran after MethodDirectElement to avoid this element picking up the method in patterns ending
    with ".tobetaken".
    """

    element_key = "frequencyWithMethod"
    element_split = ["frequency", "frequencyMax", "period_unit"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.period_unit_config["options"]
        self.prefixes = myconstants.period_unit_config["prefixes"]
        self.suffixes = myconstants.period_unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}

        pattern_name = "pattern1.tobetaken"
        # Note: This is the same as pattern1 but starting with phrases like "to be taken". The naming is purely to help
        # with grouping similar patterns in phrase_parts(). This class should be ran after MethodDirectElement
        # to avoid this picking up the method
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "to"},
                {"LOWER": "be"},
                {"TEXT": {"IN": myconstants.method_config["past_participles"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"TEXT": "times"},
                {"LEMMA": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            to be taken 4 times per day
            to be taken 2 times each week
            to be taken three times/day
            to be taken 1 time a month
            to be taken twice every year
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "frequency": 3,
            "period_unit": 6,
        }
        pattern_name = "pattern1.once.tobetaken"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "to"},
                {"LOWER": "be"},
                {"TEXT": {"IN": myconstants.method_config["past_participles"]}},
                {"LOWER": "once"},
                {"LEMMA": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            to be taken once a day
            to be taken once every fortnight
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "frequency": 3,
            "period_unit": 5,
        }
        pattern_name = "pattern2.tobetaken"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "to"},
                {"LOWER": "be"},
                {"LOWER": {"IN": myconstants.method_config["past_participles"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"ORTH": {"IN": ["to", "or", "-"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": "time"},
                {"LEMMA": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            to be taken 1 to 3 times per week
            to be taken 1-2 times a day
            to be taken 4 or 5 times a year
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "frequency": 3,
            "frequencyMax": 5,
            "period_unit": 8,
        }
        pattern_name = "pattern3.tobetaken"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "to"},
                {"LOWER": "be"},
                {"LOWER": {"IN": myconstants.method_config["past_participles"]}},
                {"LOWER": "up"},
                {"LOWER": "to"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": "time"},
                {"LEMMA": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            to be taken up to 6 times per week
            to be taken up to 1 time a day
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "frequencyMax": 5,
            "period_unit": 8,
        }
        pattern_name = "pattern3.once.tobetaken"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "to"},
                {"LOWER": "be"},
                {"LOWER": {"IN": myconstants.method_config["past_participles"]}},
                {"LOWER": "up"},
                {"LOWER": "to"},
                {"LEMMA": "once"},
                {"LEMMA": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            to be taken up to 6 times per week
            to be taken up to 1 time a day
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "period_unit": 7,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        found_dict["frequency"].append(token_dict["frequency"])
        found_dict["frequencyMax"].append(token_dict["frequencyMax"])
        found_dict["period_unit"].append(token_dict["period_unit"])
        if pattern_name in ["pattern1.tobetaken"]:
            if found_dict["frequency"][-1] == 1:
                formatted_phrase = f"once per {found_dict['period_unit'][-1]}"
            elif found_dict["frequency"][-1] == 2:
                formatted_phrase = f"twice per {found_dict['period_unit'][-1]}"
            else:
                formatted_phrase = f"{found_dict['frequency'][-1]} times per {found_dict['period_unit'][-1]}"
        elif pattern_name in ["pattern1.once.tobetaken"]:
            formatted_phrase = f"once per {found_dict['period_unit'][-1]}"
        elif pattern_name in ["pattern2.tobetaken"]:
            formatted_phrase = (
                f"{found_dict['frequency'][-1]} to {found_dict['frequencyMax'][-1]} "
                f"times per {found_dict['period_unit'][-1]}"
            )
        elif pattern_name in [
            "pattern3.tobetaken",
        ]:
            formatted_phrase = f"up to {found_dict['frequencyMax'][-1]} times per {found_dict['period_unit'][-1]}"
        elif pattern_name in ["pattern3.once.tobetaken"]:
            formatted_phrase = f"up to once per {found_dict['period_unit'][-1]}"
        else:
            raise AssertionError(
                f"pattern_name: {pattern_name} is not accounted for in this section"
            )
        return formatted_phrase, found_dict


class CountElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "count"
    element_split = ["count", "countMax"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.period_unit_config["options"]
        self.prefixes = myconstants.period_unit_config["prefixes"]
        self.suffixes = myconstants.period_unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": "time"},
            ]
        )
        """
        Captures:
            2 times
            5 times
            1 time
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "count": 0,
        }
        pattern_name = "pattern1once"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LEMMA": "once"},
            ]
        )
        """
        Captures:
            once
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "count": 0,
        }
        pattern_name = "pattern2"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"ORTH": {"IN": ["to", "or"]}},
                # Note: removed "-" as an option because three - four times could mean 3 to 4 times or take 3, 4 times.
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": "time"},
            ]
        )
        """
        Captures:
            1 to 2 times
            2 or 3 times
            not three - four times
            not 1 - 2 times
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "count": 0,
            "countMax": 2,
        }
        pattern_name = "pattern3"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "up"},
                {"LOWER": "to"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": "time"},
            ]
        )
        """
        Captures:
            up to 4 times
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "countMax": 2,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        found_dict["count"].append(token_dict["count"])
        found_dict["countMax"].append(token_dict["countMax"])
        if pattern_name == "pattern1":
            if found_dict["count"][-1] == 1:
                formatted_phrase = "once"
            elif found_dict["count"][-1] == 2:
                formatted_phrase = "twice"
            else:
                formatted_phrase = f"{found_dict['count'][-1]} times"
        elif pattern_name == "pattern1once":
            formatted_phrase = "once"
        elif pattern_name == "pattern2":
            formatted_phrase = (
                f"{found_dict['count'][-1]} to {found_dict['countMax'][-1]} " f"times"
            )
        elif pattern_name == "pattern3":
            formatted_phrase = f"up to {found_dict['countMax'][-1]} times"
        else:
            raise AssertionError(
                f"pattern_name: {pattern_name} is not accounted for in this section"
            )
        return formatted_phrase, found_dict


class PeriodElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "periodElement"
    element_split = ["period", "periodMax", "period_units"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.period_unit_config["options"]
        self.prefixes = myconstants.period_unit_config["prefixes"]
        self.suffixes = myconstants.period_unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LEMMA": {"IN": self.prefixes}},
                {"LEMMA": {"IN": self.options}},
            ]
        )
        """
        Captures:
            per day
            each week
            every month
            /day
            monthly
            hourly
            a minute
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "period_units": 1,
        }
        pattern_name = "pattern2"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LEMMA": {"IN": self.prefixes}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": self.options}},
            ]
        )
        """
        Captures:
            per 4 days
            every 5 weeks
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "period": 1,
            "period_units": 2,
        }
        pattern_name = "pattern3"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LEMMA": {"IN": self.prefixes}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"TEXT": {"IN": ["to", "-", "or"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": self.options}},
            ]
        )
        """
        Captures:
            every 1-2 days
            per 4 to 5 weeks
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "period": 1,
            "periodMax": 3,
            "period_units": 4,
        }
        pattern_name = "pattern4"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"ORTH": {"IN": self.prefixes}},
                {"TEXT": "other"},
                {"LEMMA": {"IN": self.options}},
            ]
        )
        """
        Captures:
            every other day
            each other week
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "period_units": -1,
        }
        pattern_name = "pattern5"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"TEXT": "on", "OP": "?"},
                {"TEXT": "alternate"},
                {"LEMMA": {"IN": self.options}},
            ]
        )
        """
        Captures:
            on alternate days
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "period_units": -1,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        found_dict["period"].append(token_dict["period"])
        found_dict["periodMax"].append(token_dict["periodMax"])
        found_dict["period_units"].append(token_dict["period_units"])
        if pattern_name == "pattern1":
            formatted_phrase = f"every {found_dict['period_units'][-1]}"
        elif pattern_name == "pattern2":
            formatted_phrase = (
                f"every {found_dict['period'][-1]} {found_dict['period_units'][-1]}"
            )
        elif pattern_name == "pattern3":
            formatted_phrase = (
                f"every {found_dict['period'][-1]} to {found_dict['periodMax'][-1]} "
                f"{found_dict['period_units'][-1]}"
            )
        elif pattern_name == "pattern4":
            found_dict["period"][-1] = "2"
            formatted_phrase = f"every 2 {found_dict['period_units'][-1]}s"
        elif pattern_name == "pattern5":
            found_dict["period"][-1] = "2"
            formatted_phrase = f"every 2 {found_dict['period_units'][-1]}"
        else:
            raise AssertionError(
                f"pattern_name: {pattern_name} is not accounted for in this section"
            )
        return formatted_phrase, found_dict


class WhenBareElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "whenBare"
    element_split = ["when", "offset", "offsetMax", "period_unit"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.when_config["options"]
        self.period_unit_options = myconstants.period_unit_config["options"]

    def define_pattern(self):
        self.metadata = {}

        """
        Captures:
            4 to 5 days before evening meal
            30-60 minutes after breakfast
        """
        self.register_patterns_with_multiword(
            "pattern1",
            base_tokens=[
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LOWER": {"IN": ["to", "or", "-"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": self.period_unit_options}},
            ],
            options=self.options,
            metadata={"when": [0, None], "offset": 0, "offsetMax": 2, "period_unit": 3},
        )

        """
        Captures:
            at least 12 minutes after waking
        """
        self.register_patterns_with_multiword(
            "pattern2a",
            base_tokens=[
                {"LOWER": "at"},
                {"LOWER": "least"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": self.period_unit_options}},
            ],
            options=self.options,
            metadata={"when": [0, None], "offset": 2, "period_unit": 3},
        )

        """
        Captures:
            1 hour after bedtime
            2 hours before food
        """
        self.register_patterns_with_multiword(
            "pattern2b",
            base_tokens=[
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": self.period_unit_options}},
            ],
            options=self.options,
            metadata={"when": [0, None], "offset": 0, "period_unit": 1},
        )

        """
        Captures:
            after a meal
            with evening meal
            at noon
        """
        self.register_patterns_with_multiword(
            "pattern4",
            base_tokens=[],
            options=self.options,
            metadata={"when": [0, None]},
        )

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        found_dict["when"].append(token_dict["when"])
        found_dict["offset"].append(token_dict["offset"])
        found_dict["offsetMax"].append(token_dict["offsetMax"])
        found_dict["period_unit"].append(token_dict["period_unit"])
        formatted_phrase = f"{found_dict['when'][-1]}"
        return formatted_phrase, found_dict


class WhenWithMethodElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "whenWithMethod"
    element_split = ["when", "offset", "offsetMax", "period_unit"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.when_config
        self.period_unit_options = myconstants.period_unit_config["options"]

    def define_pattern(self):
        self.metadata = {}

        """
        Captures:
            to be taken 4 to 5 days before evening meal
            to be taken 30-60 minutes after breakfast
        """
        self.register_patterns_with_multiword(
            "pattern1",
            base_tokens=[
                {"LOWER": "to"},
                {"LOWER": "be"},
                {"LOWER": {"IN": myconstants.method_config["past_participles"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LOWER": {"IN": ["to", "or", "-"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": self.period_unit_options}},
            ],
            options=self.options,
            metadata={"when": [0, None], "offset": 3, "offsetMax": 5, "period_unit": 6},
        )

        """
        Captures:
            to be taken at least 12 minutes after waking
        """
        self.register_patterns_with_multiword(
            "pattern2a",
            base_tokens=[
                {"LOWER": "to"},
                {"LOWER": "be"},
                {"LOWER": {"IN": myconstants.method_config["past_participles"]}},
                {"LOWER": "at"},
                {"LOWER": "least"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": self.period_unit_options}},
            ],
            options=self.options,
            metadata={"when": [0, None], "offset": 5, "period_unit": 6},
        )

        """
        Captures:
            to be taken 1 hour after bedtime
            to be taken 2 hours before food
        """
        self.register_patterns_with_multiword(
            "pattern2b",
            base_tokens=[
                {"LOWER": "to"},
                {"LOWER": "be"},
                {"LOWER": {"IN": myconstants.method_config["past_participles"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": self.period_unit_options}},
            ],
            options=self.options,
            metadata={"when": [0, None], "offset": 3, "period_unit": 4},
        )

        """
        Captures:
            to be taken with food
            to be applied after main meal
        """
        self.register_patterns_with_multiword(
            "pattern4",
            base_tokens=[
                {"LOWER": "to"},
                {"LOWER": "be"},
                {"LOWER": {"IN": myconstants.method_config["past_participles"]}},
            ],
            options=self.options,
            metadata={"when": [0, None]},
        )

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["when"].append(token_dict["when"])
        found_dict["offset"].append(token_dict["offset"])
        found_dict["offsetMax"].append(token_dict["offsetMax"])
        found_dict["period_unit"].append(token_dict["period_unit"])
        formatted_phrase = f"{found_dict['when'][-1]}"
        return formatted_phrase, found_dict


class MilligramMaxElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "milligramMax"
    element_split = ["value", "valueMax", "milligram_units"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.milli_config["options"]
        self.prefixes = myconstants.milli_config["prefixes"]
        self.suffixes = myconstants.milli_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}

        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LOWER": {"IN": ["or", "to", "-"]}},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LOWER": {"IN": self.options}},
            ]
        )
        """
        Captures:
            4.5 or 5ml
            4 to 5 mls
            4 - 5 ml
            1 to 2 milligrams
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 0,
            "valueMax": 2,
            "milligram_units": 3,
        }
        pattern_name = "pattern2"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LOWER": {"IN": self.options}},
                {"LOWER": {"IN": ["or", "to", "-"]}},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LOWER": {"IN": self.options}},
            ]
        )
        """
        Captures:
            4.5ml or 5ml
            4ml to 5 mls
            4mls - 5 ml
            0.5 - 1 millilitre
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 0,
            "valueMax": 3,
            "milligram_units": 4,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(token_dict["value"])
        found_dict["valueMax"].append(token_dict["valueMax"])
        found_dict["milligram_units"].append(token_dict["milligram_units"])
        formatted_phrase = f"{found_dict['value'][-1]} to {found_dict['valueMax'][-1]} {found_dict['milligram_units'][-1]}"
        return formatted_phrase, found_dict


class MilligramValueElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "milligramValue"
    element_split = ["value", "milligram_units"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.milli_config["options"]
        self.prefixes = myconstants.milli_config["prefixes"]
        self.suffixes = myconstants.milli_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LOWER": {"IN": self.options}},
            ]
        )
        """
        Captures:
            4.5ml
            5.25mg
            3 mls
            2 milligrams
            1millilitre
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 0,
            "milligram_units": 1,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(token_dict["value"])
        found_dict["milligram_units"].append(token_dict["milligram_units"])
        formatted_phrase = (
            f"{found_dict['value'][-1]} {found_dict['milligram_units'][-1]}"
        )
        return formatted_phrase, found_dict


class DayOfWeekElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "dayOfWeek"
    element_split = ["value"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.weekday_config["options"]
        self.prefixes = myconstants.weekday_config["prefixes"]
        self.suffixes = myconstants.weekday_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "on"},
                {"LEMMA": {"IN": self.options}},
                # {"TEXT": {"IN": [",", "and"]}, "OP": "*"},  # Removed due to rule 7
                # {"LEMMA": {"IN": self.options}, "OP": "*"},  # Removed due to rule 7
            ]
        )
        """
        Captures:
            on Monday
            on tue

        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {"value": 0}

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(span.text)
        formatted_phrase = f"{found_dict['value'][-1]}"
        return formatted_phrase, found_dict


class TimeOfDayElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "timeOfDay"
    element_split = ["value"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = [""]
        self.prefixes = [""]
        self.suffixes = [""]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "at"},
                {"TEXT": {"REGEX": "^([0-9]|10|11|12)$"}},
                {"IS_SPACE": True, "OP": "?"},
                {"TEXT": {"REGEX": "^(am|pm|noon)$"}},
                # {"TEXT": {"IN": [",", "and"]}, "OP": "*"},  # Removed due to rule 7
                # {"LEMMA": {"REGEX": "^([0-9]|10|11|12)(am|pm|noon)$"}, "OP": "*"},  # Removed due to rule 7
            ]
        )
        """
        Captures:
            at 5pm
            at 1am
            at 12 noon
        """
        self.pattern.append(
            [
                {"LOWER": "at"},
                {"LEMMA": {"REGEX": "^(0?[0-9]|1[0-9]|2[0-4]):(00|15|30|45)$"}},
                # {"TEXT": {"IN": [",", "and"]}, "OP": "*"},
                # {
                #     "LEMMA": {"REGEX": "^(0?[0-9]|1[0-9]|2[0-4]):(00|15|30|45)$"},
                #     "OP": "*",
                # }, # Removed due to rule 7
            ]
        )
        """
        Captures:
            at 1:45
            at 03:30
            at 15:30
            not at 3:00, 3:15 and 3:30
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {"value": 0}

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(span.text)
        formatted_phrase = f"{found_dict['value'][-1]}"
        return formatted_phrase, found_dict


class MaxDosePerPeriodElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "maxDosePerPeriod"
    element_split = ["num_value", "num_unit", "denom_value", "denom_unit"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.unit_config["options"]
        self.prefixes = myconstants.unit_config["prefixes"]
        self.suffixes = myconstants.unit_config["suffixes"]

    def define_pattern(self):
        # Qcall2: can we add "maximum 8 tablets in 24 hours"
        # Qcall2: can we add "total dose 12mg" - too ambiguous - additional instruction
        # Qcall2: can we add "total daily dose 12mg"
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "up", "OP": "?"},
                {"LOWER": "to", "OP": "?"},
                {"LOWER": "a", "OP": "?"},
                {"LOWER": {"IN": ["max", "maximum"]}},
                {"LOWER": "of", "OP": "?"},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LEMMA": {"IN": self.options}},
                {"LOWER": "in"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            up to a maximum of 3 tablets in 4 days
            maximum of 3 tablets in 4 weeks
            up to a max of 3 tablets in 4 years
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "num_value": -5,
            "num_unit": -4,
            "denom_value": -2,
            "denom_unit": -1,
        }
        pattern_name = "pattern2"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "up", "OP": "?"},
                {"LOWER": "to", "OP": "?"},
                {"LOWER": "a", "OP": "?"},
                {"LOWER": {"IN": ["max", "maximum"]}},
                {"LOWER": "of", "OP": "?"},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LEMMA": {"IN": self.options}},
                {"LOWER": "in"},
                {"LOWER": "a"},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            up to a maximum of 3 tablets in a day
            maximum of 3 tablets in a week
            up to a max 3 tablets in a year
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "num_value": -5,
            "num_unit": -4,
            "denom_unit": -1,
        }

        pattern_name = "pattern3"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "up", "OP": "?"},
                {"LOWER": "to", "OP": "?"},
                {"LOWER": "a", "OP": "?"},
                {"LOWER": {"IN": ["max", "maximum"]}},
                {"LOWER": "of", "OP": "?"},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LEMMA": {"IN": self.options}},
                {"LEMMA": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            up to a maximum of 3 tablets every day
            maximum of 3 tablets each week
            up to a max of 3 tablets per year
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "num_value": -4,
            "num_unit": -3,
            "denom_unit": -1,
        }
        pattern_name = "pattern4"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": {"IN": ["not", "no"]}},
                {"LOWER": "more"},
                {"LOWER": "than"},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LEMMA": {"IN": self.options}},
                {"LOWER": "in"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            no more than 3 tablets in 4 days
            not more than 3 tablets in 4 weeks
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "num_value": -5,
            "num_unit": -4,
            "denom_value": -2,
            "denom_unit": -1,
        }
        pattern_name = "pattern5"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": {"IN": ["not", "no"]}},
                {"LOWER": "more"},
                {"LOWER": "than"},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LEMMA": {"IN": self.options}},
                {"LOWER": "in"},
                {"LOWER": "a"},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            no more than 3 tablets in a day
            not more than 3 tablets in a week
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "num_value": -5,
            "num_unit": -4,
            "denom_unit": -1,
        }
        pattern_name = "pattern6"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": {"IN": ["not", "no"]}},
                {"LOWER": "more"},
                {"LOWER": "than"},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LEMMA": {"IN": self.options}},
                {"LEMMA": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"LEMMA": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        """
        Captures:
            no more than 3 tablets every day
            not more than 3 tablets each week
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "num_value": -4,
            "num_unit": -3,
            "denom_unit": -1,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        found_dict["num_value"].append(token_dict["num_value"])
        found_dict["num_unit"].append(token_dict["num_unit"])
        found_dict["denom_value"].append(token_dict["denom_value"])
        found_dict["denom_unit"].append(token_dict["denom_unit"])
        if (
            (pattern_name == "pattern2")
            | (pattern_name == "pattern3")
            | (pattern_name == "pattern5")
            | (pattern_name == "pattern6")
        ):
            found_dict["denom_value"][-1] = "1"
        formatted_phrase = (
            f"up to a maximum of {found_dict['num_value'][-1]} {found_dict['num_unit'][-1]} "
            f"in {found_dict['denom_value'][-1]} {found_dict['denom_unit'][-1]}"
        )
        return formatted_phrase, found_dict


class MaxDosePerAdministrationElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "maxDosePerAdministration"
    element_split = ["value", "unit"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.unit_config["options"]
        self.prefixes = myconstants.unit_config["prefixes"]
        self.suffixes = myconstants.unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "up"},
                {"LOWER": "to"},
                {"LOWER": "a"},
                {"LOWER": {"IN": ["max", "maximum"]}},
                {"LOWER": "of"},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LEMMA": {"IN": self.options}},
                {"LOWER": "per"},
                {"LOWER": "dose"},
            ]
        )
        """
        Captures:
            up to a maximum of 5 sprays per dose
            up to a max of 5 sprays per dose
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 5,
            "unit": 6,
        }
        pattern_name = "pattern2"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": {"IN": ["not", "no"]}},
                {"LOWER": "more"},
                {"LOWER": "than"},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LEMMA": {"IN": self.options}},
                {"LOWER": "per"},
                {"LOWER": "dose"},
            ]
        )
        """
        Captures:
            no more than 5 sprays per dose
            not more than 5 sprays per dose
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 3,
            "unit": 4,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(token_dict["value"])
        found_dict["unit"].append(token_dict["unit"])
        formatted_phrase = f"up to a maximum of {found_dict['value'][-1]} {found_dict['unit'][-1]} per dose"
        return formatted_phrase, found_dict


class MaxDosePerLifetimeElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "maxDosePerLifetime"
    element_split = ["value", "unit"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.unit_config["options"]
        self.prefixes = myconstants.unit_config["prefixes"]
        self.suffixes = myconstants.unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "up"},
                {"LOWER": "to"},
                {"LOWER": "a"},
                {"LOWER": {"IN": ["max", "maximum"]}},
                {"LOWER": "of"},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LEMMA": {"IN": self.options}},
                {"LOWER": {"IN": ["in", "per", "for"]}},
                {"LOWER": {"IN": ["the"]}, "OP": "?"},
                {"LOWER": "lifetime"},
                {"LOWER": "of", "OP": "?"},
                {"LOWER": "the", "OP": "?"},
                {"LOWER": "patient", "OP": "?"},
            ]
        )
        """
        Captures:
            up to a maximum of 5 sprays per lifetime of the patient
            up to a max of 5 sprays for the lifetime of patient
            up to a maximum of 5 sprays in the lifetime of the patient
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 5,
            "unit": 6,
        }
        pattern_name = "pattern2"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": {"IN": ["max", "maximum"]}},
                {"LOWER": "of"},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LEMMA": {"IN": self.options}},
                {"LOWER": {"IN": ["in", "per", "for"]}},
                {"LOWER": {"IN": ["the"]}, "OP": "?"},
                {"LOWER": "lifetime"},
                {"LOWER": "of", "OP": "?"},
                {"LOWER": "the", "OP": "?"},
                {"LOWER": "patient", "OP": "?"},
            ]
        )
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 2,
            "unit": 3,
        }
        """
        Captures:
            maximum of 5 sprays per lifetime of the patient
            max of 5 sprays for the lifetime of patient
            maximum of 5 sprays in the lifetime of the patient
        """
        pattern_name = "pattern3"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": {"IN": ["not", "no"]}},
                {"LOWER": "more"},
                {"LOWER": "than"},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LEMMA": {"IN": self.options}},
                {"LOWER": {"IN": ["in", "per", "for"]}},
                {"LOWER": {"IN": ["the"]}, "OP": "?"},
                {"LOWER": "lifetime"},
                {"LOWER": "of", "OP": "?"},
                {"LOWER": "the", "OP": "?"},
                {"LOWER": "patient", "OP": "?"},
            ]
        )
        """
        Captures:
            not more than 5 sprays per lifetime of the patient
            no more than 5 sprays for the lifetime of patient
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 3,
            "unit": 4,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(token_dict["value"])
        found_dict["unit"].append(token_dict["unit"])
        formatted_phrase = (
            f"up to a maximum of {found_dict['value'][-1]} {found_dict['unit'][-1]} "
            f"for the lifetime of patient"
        )
        return formatted_phrase, found_dict


class BoundsDurationElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "boundsDuration"
    element_split = [
        "value",
        "unit",
        "low",
        "high",
        "low_unit",
        "high_unit",
        "start",
        "end",
    ]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.period_unit_config["options"]
        self.prefixes = myconstants.period_unit_config["prefixes"]
        self.suffixes = myconstants.period_unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "for"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": self.options}},
            ]
        )
        """
        Captures:
            for 5 days
            for 3 weeks
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 1,
            "unit": 2,
        }
        pattern_name = "pattern2"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "for"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LOWER": {"IN": ["to", "-", "or"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": self.options}},
            ]
        )
        """
        Captures:
            for 1 to 3 months
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "low": 1,
            "high": 3,
            "high_unit": 4,
        }
        pattern_name = "pattern3"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "for"},
                {"LOWER": "at"},
                {"LOWER": "least"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": self.options}},
            ]
        )
        """
        Captures:
            for at least 4 hours
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "low": 3,
            "low_unit": 4,
        }
        pattern_name = "pattern4"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "for"},
                {"LOWER": "up"},
                {"LOWER": "to"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LEMMA": {"IN": self.options}},
            ]
        )
        """
        Captures:
            for up to 5 days
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "high": 3,
            "high_unit": 4,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        found_dict["value"].append(token_dict["value"])
        found_dict["unit"].append(token_dict["unit"])
        found_dict["low"].append(token_dict["low"])
        found_dict["high"].append(token_dict["high"])
        found_dict["high_unit"].append(token_dict["high_unit"])
        found_dict["low_unit"].append(token_dict["low_unit"])
        if pattern_name == "pattern1":
            formatted_phrase = f"for {found_dict['value'][-1]} {found_dict['unit'][-1]}"
        elif pattern_name == "pattern2":
            formatted_phrase = f"for {found_dict['low'][-1]} to {found_dict['high'][-1]} {found_dict['high_unit'][-1]}"
        elif pattern_name == "pattern3":
            formatted_phrase = (
                f"for at least {found_dict['low'][-1]} {found_dict['low_unit'][-1]}"
            )
        elif pattern_name == "pattern4":
            formatted_phrase = (
                f"for up to {found_dict['high'][-1]} {found_dict['high_unit'][-1]}"
            )
        else:
            raise AssertionError(
                f"pattern_name: {pattern_name} is not accounted for in this section"
            )
        found_dict["start"].append(token_dict["start"])
        found_dict["end"].append(token_dict["end"])
        return formatted_phrase, found_dict


class BoundsPeriodElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "boundsPeriod"
    element_split = ["start", "end"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.unit_config["options"]
        self.prefixes = myconstants.unit_config["prefixes"]
        self.suffixes = myconstants.unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "from"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_dmy}"}},
                {"LOWER": "to"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_dmy}"}},
            ]
        )
        """
        Captures:
            from 2/12/24 to 04/12/24
            from 30-09-2023 to 1-4-1998
        """
        self.pattern.append(
            [
                {"LOWER": "from"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_ymd}"}},
                {"LOWER": "to"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_ymd}"}},
            ]
        )
        """
        Captures:
            from 24/12/2 to 24/12/04
            from 2023-30-09 to 1998-1-4
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "start": 1,
            "end": 3,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["start"].append(token_dict["start"])
        found_dict["end"].append(token_dict["end"])
        formatted_phrase = f"from {found_dict['start'][-1]} to {found_dict['end'][-1]}"
        return formatted_phrase, found_dict


class BoundsAPeriodStartEndElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "boundsAPeriodStartEnd"
    element_split = ["start", "end"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.unit_config["options"]
        self.prefixes = myconstants.unit_config["prefixes"]
        self.suffixes = myconstants.unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "from"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_dmy}"}},
            ]
        )
        """
        Captures:
            from 2/12/24
            from 04/12/24
            from 30-09-2023
            from 1-4-1998
        """
        self.pattern.append(
            [
                {"LOWER": "from"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_ymd}"}},
            ]
        )
        """
        Captures:
            from 24/12/24
            from 24/12/10
            from 2023-09-23
            not from 2024-4-65
            not from 1823/9/9
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "start": 1,
        }
        pattern_name = "pattern2"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": "until"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_dmy}"}},
            ]
        )
        """
        Captures:
            until 4/12/24
            until 04/12/2010
            until 21-09-2009
        """
        self.pattern.append(
            [
                {"LOWER": "until"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_ymd}"}},
            ]
        )
        """
        Captures:
            until 24/12/24
            until 24/12/10
            until 2023-09-23
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "end": 1,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        found_dict["start"].append(token_dict["start"])
        found_dict["end"].append(token_dict["end"])
        if pattern_name == "pattern1":
            formatted_phrase = f"from {found_dict['start'][-1]}"
        elif pattern_name == "pattern2":
            formatted_phrase = f"until {found_dict['end'][-1]}"
        else:
            raise AssertionError(
                f"pattern_name: {pattern_name} is not accounted for in this section"
            )
        return formatted_phrase, found_dict


class EventElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "event"
    element_split = ["value"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.unit_config["options"]
        self.prefixes = myconstants.unit_config["prefixes"]
        self.suffixes = myconstants.unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(  # Qcall2 - what date formats accepted? mentions 2025-05-03 and 29/12/2025 in link
            [
                {"LOWER": "on"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_dmy}"}},
            ]
        )
        """
        Captures:
            on 14/12/24
            on 04/12/10
            on 23-09-2023
        """
        self.pattern.append(
            [
                {"LOWER": "on"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_ymd}"}},
            ]
        )
        """
        Captures:
            on 24/12/24
            on 24/12/10
            on 2023-09-23
        """
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 1,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(token_dict["value"])
        formatted_phrase = f"on {found_dict['value'][-1]}"
        return formatted_phrase, found_dict


class AsNeededCodeableConceptElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "asNeededCodeableConcept"
    element_split = ["value"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.for_config["options"]

    def define_pattern(self):
        self.metadata = {}

        self.register_patterns_with_multiword(
            "pattern1",
            [{"LOWER": "as"}, {"LOWER": "needed"}],
            self.options,
            metadata={"value": [0, None]},
        )

        self.register_patterns_with_multiword(
            "pattern2",
            [{"LOWER": "as"}, {"LOWER": "required"}],
            self.options,
            metadata={"value": [0, None]},
        )

        self.register_patterns_with_multiword(
            "pattern2",
            [{"LOWER": "as"}, {"LOWER": "necessary"}],
            self.options,
            metadata={"value": [0, None]},
        )

        self.register_patterns_with_multiword(
            "pattern2",
            [{"LOWER": "when"}, {"LOWER": "needed"}],
            self.options,
            metadata={"value": [0, None]},
        )

        self.register_patterns_with_multiword(
            "pattern2",
            [{"LOWER": "when"}, {"LOWER": "required"}],
            self.options,
            metadata={"value": [0, None]},
        )

        self.register_patterns_with_multiword(
            "pattern2",
            [{"LOWER": "when"}, {"LOWER": "necessary"}],
            self.options,
            metadata={"value": [0, None]},
        )

        self.register_patterns_with_multiword(
            "pattern2",
            [{"LOWER": "if"}, {"LOWER": "needed"}],
            self.options,
            metadata={"value": [0, None]},
        )

        self.register_patterns_with_multiword(
            "pattern2",
            [{"LOWER": "if"}, {"LOWER": "required"}],
            self.options,
            metadata={"value": [0, None]},
        )

        self.register_patterns_with_multiword(
            "pattern2",
            [{"LOWER": "if"}, {"LOWER": "necessary"}],
            self.options,
            metadata={"value": [0, None]},
        )

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(span.text)
        formatted_phrase = f"{found_dict['value'][-1]}"
        return formatted_phrase, found_dict


class ForElement(BaseElement):
    """
    Please see the base class for explanations of the steps and contents of the classes. The layout, functions and
    attributes are similar across all child classes.
    """

    element_key = "forElement"
    element_split = ["value"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.for_config["options"]

    def define_pattern(self):
        self.metadata = {}
        self.register_patterns_with_multiword(
            "pattern1",
            [],
            self.options,
            metadata={"value": [0, None]},
        )

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(span.text)
        formatted_phrase = f"{found_dict['value'][-1]}"
        return formatted_phrase, found_dict


class POSTagging(BaseElement):
    """
    This class is for testing purposes only, to help review what the input data looks like, and try to
    find new words using pos tagging (e.g. find all the verbs) to add to the constants config options.
    """

    element_key = "posTagging"
    element_split = ["ADJ"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = myconstants.for_config["options"]
        self.prefixes = myconstants.for_config["prefixes"]
        self.next_prefix = myconstants.for_config["next_prefix"]
        self.suffixes = myconstants.for_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}

        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(  # Qcall2 - what date formats accepted? mentions 2025-05-03 and 29/12/2025 in link
            [
                {"POS": "ADV", "OP": "*"},
            ]
        )
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "ADJ": 0,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        for item in self.element_split:
            found_dict[item].append(token_dict[item])
        formatted_phrase = f"{span.text}"
        return formatted_phrase, found_dict


# ---------------------------------------------------------------------------
# Single-Pass Extraction
# ---------------------------------------------------------------------------
#
# Previously, each element class ran its own UDF (~30 sequential calls per row).
# Each call tokenized the text with spaCy, ran the full Matcher, filtered to one
# class, and discarded the rest — repeating ~30 times per row.
#
# This single-pass approach tokenizes ONCE, runs the Matcher ONCE, resolves which
# class "wins" each span, and produces all output columns in a single UDF call.
# ---------------------------------------------------------------------------


def build_extraction_schema(element_classes):
    """
    Build the output StructType for the single-pass extraction UDF.

    Reads element_key and element_split directly from the class definitions
    (class-level attributes), so adding a new element class automatically
    updates the schema.
    """
    fields = [StructField("dosage_elements", StringType(), True)]
    for cls in element_classes:
        fields.append(StructField(f"{cls.element_key}_clean", StringType(), True))
        fields.append(StructField(f"{cls.element_key}_captured", StringType(), True))
        for split_field in cls.element_split:
            fields.append(
                StructField(
                    f"{cls.element_key}_{split_field}",
                    ArrayType(StringType()),
                    True,
                )
            )
    return StructType(fields)


def _extract_single_row(text, instances, instances_by_key, priority_map, nlp, matcher):
    """
    Extract all elements from a single text string in one spaCy pass.

    Steps:
      1. Tokenize text and run all Matcher patterns at once
      2. Map each match back to its owning element class
      3. Resolve overlapping spans (higher-priority class wins)
      4. For each winning match, call the class's phrase_parts() to get structured output
      5. Build the remainder string with *elementKey* markers
    """
    # Pre-fill with None so every column exists even if nothing matches
    empty = {"dosage_elements": text}
    for inst in instances:
        empty[f"{inst.element_key}_clean"] = None
        empty[f"{inst.element_key}_captured"] = None
        for split_field in inst.element_split:
            empty[f"{inst.element_key}_{split_field}"] = []

    if not text or not text.strip():
        return empty

    # --- Step 1: Tokenize once and run ALL patterns in one Matcher call ---
    doc = nlp(text)
    matches = matcher(doc)

    # --- Step 2: Identify which element class each match belongs to ---
    # The Matcher returns ALL matches from ALL classes. We group them by checking
    # which element_key the match label starts with (labels are "{element_key}_{pattern_name}")
    candidates = []
    for match_id, start, end in matches:
        label = doc.vocab.strings[match_id]
        for inst in instances:
            if label.startswith(f"{inst.element_key}_"):
                candidates.append((inst.element_key, label, start, end))
                break

    # --- Step 3: Resolve overlapping spans ---
    # Sort by priority first (position in `classes` list — lower index = higher priority),
    # then by span start position, then prefer longest span (negative length).
    # This ensures higher-priority classes claim their spans before lower-priority ones,
    # and for the same element at the same position, the longest match wins.
    candidates.sort(key=lambda m: (priority_map[m[0]], m[2], -(m[3] - m[2])))

    taken_ranges = []  # token spans already claimed by a higher-priority match
    resolved = {}  # element_key -> (label, start, end) — one winner per class

    for elem_key, label, start, end in candidates:
        # Only one match per element class (mirrors the original `break` after first match)
        if elem_key in resolved:
            continue
        # Skip if these tokens overlap with an already-claimed span
        if any(start < t_end and end > t_start for t_start, t_end in taken_ranges):
            continue
        taken_ranges.append((start, end))
        resolved[elem_key] = (label, start, end)

    # Post-resolution: if methodDirect is captured and a "WithMethod" element was
    # blocked by methodPassive, prefer the longer WithMethod span (which subsumes
    # "to be taken"). Applies to frequencyWithMethod and whenWithMethod.
    if "methodDirect" in resolved and "methodPassive" in resolved:
        mp_start, mp_end = resolved["methodPassive"][1], resolved["methodPassive"][2]
        for with_method_key in ("frequencyWithMethod", "whenWithMethod"):
            if with_method_key in resolved:
                continue
            for elem_key, label, start, end in candidates:
                if elem_key == with_method_key and start <= mp_start and end >= mp_end:
                    taken_ranges = [
                        (s, e) for s, e in taken_ranges if (s, e) != (mp_start, mp_end)
                    ]
                    del resolved["methodPassive"]
                    taken_ranges.append((start, end))
                    resolved[with_method_key] = (label, start, end)
                    break
            if "methodPassive" not in resolved:
                break

    # --- Step 4: For each winning match, extract structured fields via phrase_parts() ---
    result = dict(empty)

    for elem_key, (label, start, end) in resolved.items():
        inst = instances_by_key[elem_key]
        span = doc[start:end]

        # Build token_dict exactly as extract_element_using_matcher() does:
        # uses metadata positions to pull out the important tokens from the span
        token_dict = {}
        for key in inst.element_split:
            token_dict[key] = ""
        for key, position in inst.metadata[label].items():
            if isinstance(position, list):
                sliced = span[position[0] : position[1]]
                token_dict[key] = sliced.text
            else:
                token = span[position]
                token_dict[key] = token.text
                token_dict[f"{key}_token"] = token
        token_dict["pattern_name"] = label.replace(f"{elem_key}_", "")

        # phrase_parts() formats the output string and populates found_dict
        found_dict = {var: [] for var in inst.element_split}
        formatted_phrase, found_dict = inst.phrase_parts(span, found_dict, token_dict)
        if formatted_phrase is None:
            continue

        result[f"{elem_key}_clean"] = formatted_phrase
        result[f"{elem_key}_captured"] = span.text
        for split_field in inst.element_split:
            result[f"{elem_key}_{split_field}"] = (
                found_dict[split_field] if found_dict[split_field] else []
            )

    # --- Step 5: Build remainder string with *elementKey* markers ---
    # Use character-level positions (doc[token].idx) for accurate replacement,
    # rather than str.replace() which could match the wrong occurrence of duplicate text.
    replacements = []
    for elem_key, (label, start, end) in resolved.items():
        if result.get(f"{elem_key}_clean") is None:
            continue
        char_start = doc[start].idx
        char_end = doc[end - 1].idx + len(doc[end - 1])
        replacements.append((char_start, char_end, f"*{elem_key}*"))

    # Replace from end-to-start so earlier positions aren't shifted by insertions
    replacements.sort(key=lambda r: r[0], reverse=True)
    remainder = text
    for char_start, char_end, replacement in replacements:
        remainder = remainder[:char_start] + replacement + remainder[char_end:]

    # Normalize whitespace (same as the original regexp_replace(r"\s+", " ") in update_df)
    result["dosage_elements"] = _re.sub(r"\s+", " ", remainder).strip()
    return result


def create_extract_all_udf(instances, bc_nlp, bc_matcher):
    """
    Create a pandas_udf that extracts all elements in a single spaCy/Matcher pass.

    This replaces the loop `for instance in instances: instance.update_df(...)` with one
    UDF call. The pandas_udf processes rows in vectorized batches, reducing JVM<->Python
    serialization overhead compared to ~30 separate standard UDFs.

    Parameters
    ----------
    instances : list
        Initialized element class instances (in priority order).
    bc_nlp : Broadcast
        Broadcast spaCy nlp pipeline.
    bc_matcher : Broadcast
        Broadcast spaCy Matcher (with all patterns registered).

    Returns
    -------
    tuple of (pandas_udf function, StructType schema)
    """
    schema = build_extraction_schema(classes)
    # Priority = position in the classes list (lower index = higher priority = wins overlaps)
    priority_map = {inst.element_key: idx for idx, inst in enumerate(instances)}
    instances_by_key = {inst.element_key: inst for inst in instances}

    array_columns = [f.name for f in schema.fields if isinstance(f.dataType, ArrayType)]

    @pandas_udf(schema)
    def extract_all_udf(texts: pd.Series) -> pd.DataFrame:
        # Retrieve broadcast objects once per batch (not per row)
        nlp = bc_nlp.value
        matcher = bc_matcher.value
        rows = [
            _extract_single_row(
                text, instances, instances_by_key, priority_map, nlp, matcher
            )
            for text in texts
        ]
        df = pd.DataFrame(rows, columns=[f.name for f in schema.fields])
        for col in array_columns:
            df[col] = df[col].apply(lambda x: x if isinstance(x, list) else [])
        return df

    return extract_all_udf, schema


classes = [
    MethodDirectElement,
    MethodPassiveElement,
    RateRatioElement,
    RateRangeElement,
    RateQuantityElement,
    DurationElement,
    DurationMaxElement,  # durationMax
    FrequencyWithMethodElement,
    FrequencyBareElement,
    TimeOfDayElement,
    DayOfWeekElement,
    MaxDosePerPeriodElement,
    MaxDosePerAdministrationElement,
    MaxDosePerLifetimeElement,
    PeriodElement,
    WhenWithMethodElement,
    WhenBareElement,
    BoundsDurationElement,
    BoundsPeriodElement,
    BoundsAPeriodStartEndElement,
    EventElement,
    AsNeededCodeableConceptElement,
    ForElement,
    CountElement,
    DoseRangeElement,
    DoseQuantityElement,
    DoseXMilliValueOnlyElement,  # needs to be higher than DoseQuantity and below Milligram.
    MilligramMaxElement,  # needs to be after DoseQuantity
    MilligramValueElement,  # needs to be after MilligamMax
    DoseQuantityValueAndMaxOnlyElement,  # needs to be after DoseRangeQuantity
    DoseQuantityValueOnlyElement,  # needs to be last. 2
]
# doseRange
# 1 - 2 x 5ml spoonful
# 2 x 5ml spoonful  DQuantity
# 2 x 5ml DoseXMilli
# 5ml
# 1-2 DQMOnly
# 1 QOnly

# ---------------------------------------------------------------------------
# Full Lookup Schema (generated from the classes list)
# ---------------------------------------------------------------------------
# This is the complete output schema for the lookup table. It's built by iterating
# the classes list and reading their element_key/element_split class attributes,
# so it automatically stays in sync when you add/remove/rename element classes.


def _build_lookup_schema():
    fields = [
        # --- Input columns ---
        StructField("dosage", StringType(), True),
        StructField("dosage_lower", StringType(), True),
        StructField("dosage_count", LongType(), True),
        # StructField("excluded", StringType(), True),
        StructField("dosage_elements", StringType(), True),
        StructField("extras_b_clean", StringType(), True),
    ]

    # --- Element columns (derived from classes list) ---
    for cls in classes:
        fields.append(StructField(f"{cls.element_key}_clean", StringType(), True))
        fields.append(StructField(f"{cls.element_key}_captured", StringType(), True))
        for split_field in cls.element_split:
            fields.append(
                StructField(
                    f"{cls.element_key}_{split_field}",
                    ArrayType(StringType(), True),
                    True,
                )
            )

    # --- Post-extraction columns ---
    fields.extend(
        [
            StructField("buckets", StringType(), True),
            StructField("extras_clean", StringType(), True),
            StructField("extrasPAUSE_clean", StringType(), True),
            StructField("extrasALTER_clean", StringType(), True),
            StructField("asNeededBoolean_clean", StringType(), True),
            StructField("route_clean", StringType(), True),
            StructField("site_clean", StringType(), True),
            StructField("extras_whenoffset", StringType(), True),
            # --- Validation columns (from validate_dosage_elements) ---
            StructField("exclude", StringType(), True),
            StructField("dosage_spare", StringType(), True),
            StructField("mapped", StringType(), True),
            # --- Metadata ---
            StructField("timestamp", TimestampType(), True),
            StructField("space", StringType(), True),
            StructField("_snapshot_ts", TimestampType(), True),
        ]
    )

    return StructType(fields)


lookup_schema = _build_lookup_schema()
