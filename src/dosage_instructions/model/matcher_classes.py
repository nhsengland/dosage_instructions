import re as _re
from abc import ABC, abstractmethod

import pandas as pd
from pyspark.sql import functions as F
from pyspark.sql.functions import pandas_udf
from pyspark.sql.types import (
    ArrayType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from dosage_instructions.model import constants as myconstants

# ---------------------------------------------------------------------------
# (s) resolution — convert "tablet(s)" to "tablet" or "tablets" based on qty
# ---------------------------------------------------------------------------


def _resolve_parenthetical_s(unit: str, quantity: str) -> str:
    """Resolve a '(s)' unit to singular or plural based on quantity.

    E.g. "tablet(s)" + "1" → "tablet"; "tablet(s)" + "2" → "tablets".
    If the unit doesn't contain '(s)', returns it unchanged.
    """
    if "(s)" not in unit:
        return unit
    try:
        qty = float(quantity)
    except (ValueError, TypeError):
        qty = 1  # default to singular if quantity is unparseable
    if qty == 1:
        return myconstants.PARENTHETICAL_S_SINGULAR.get(unit, unit.replace("(s)", ""))
    else:
        return myconstants.PARENTHETICAL_S_PLURAL.get(unit, unit.replace("(s)", "s"))


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

        For single-word options, registers one pattern with {"NORM": {"IN": [...]}}
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
            pattern = base_tokens + [{"NORM": {"IN": single_opts}}]
            self.matcher.add(f"{self.element_key}_{pattern_name}", [pattern])
            self.metadata[f"{self.element_key}_{pattern_name}"] = metadata

        for i, words in enumerate(multi_opts):
            mw_name = f"{pattern_name}_mw{i}"
            self.meta_creator(mw_name)
            pattern = base_tokens[:]
            doc = self.nlp(" ".join(words))
            for token in doc:
                if token.pos_ == "NOUN":
                    pattern.append({"NORM": token.lemma_})
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
        )
        # See to_test.py element_specific for capture/ignore examples
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "verb": -1,
        }

        # Compound method patterns — multi-token phrases captured as a single method.
        # These are registered with higher token count so they win over single-word
        # pattern1 matches via the longest-match resolution in _extract_single_row.
        for i, compound in enumerate(
            myconstants.method_config.get("compound_options", [])
        ):
            cmp_name = f"pattern_compound_{i}"
            self.meta_creator(cmp_name)
            tokens = [{"LOWER": word} for word in compound.split()]
            # Register two patterns: with and without "to" prefix
            pattern_bare = tokens[:]
            pattern_with_to = [{"LOWER": "to"}] + tokens
            self.matcher.add(
                f"{self.element_key}_{cmp_name}", [pattern_bare, pattern_with_to]
            )
            self.metadata[f"{self.element_key}_{cmp_name}"] = {
                "verb": [0, None],  # entire span is the verb phrase
            }

    def phrase_parts(self, span, found_dict, token_dict):
        verb = token_dict["verb"]
        # Strip leading "to " from compound matches (e.g. "to apply sparingly" → "apply sparingly")
        if isinstance(verb, str) and verb.lower().startswith("to "):
            verb = verb[3:]
        found_dict["verb"].append(verb)
        formatted_phrase = f"{verb}"
        return formatted_phrase, found_dict


class MethodPassiveElement(BaseElement):
    """
    Matches passive method phrases ("to be taken", "applied", "given" etc.)
    and outputs the lemmatised verb form (e.g. "take", "apply", "give").

    Note: spaCy lemmatises "instilled" → "instill" (American/SNOMED spelling),
    not "instil" (British). The _clean output uses spaCy's lemma directly,
    so the output will be "instill" — this matches SNOMED terminology.
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
        # See to_test.py element_specific for capture/ignore examples
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
        # See to_test.py element_specific for capture/ignore examples
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
            {"NORM": {"IN": ["spoon", "spoonful"]}},
        ]
        # See to_test.py element_specific for capture/ignore examples
        self.matcher.add(f"{self.element_key}_{pattern_name}", [self.pattern])
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "quantity": 0,
            "units": -1,
            "spoonsize": -3,
        }
        # See to_test.py element_specific for capture/ignore examples
        self.register_patterns_with_multiword(
            "pattern2",
            base_tokens=[{"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}}],
            options=self.options,
            metadata={"quantity": 0, "units": [1, None]},
        )

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        qty = token_dict["quantity"]
        units = _resolve_parenthetical_s(token_dict["units"], qty)
        found_dict["quantity"].append(qty)
        found_dict["units"].append(units)
        found_dict["spoonsize"].append(token_dict["spoonsize"])
        if pattern_name == "pattern1":
            formatted_phrase = f"{qty} x {found_dict['spoonsize'][-1]}ml spoonfuls"
        elif pattern_name.startswith("pattern2"):
            formatted_phrase = f"{qty} {units}"
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
        # See to_test.py element_specific for capture/ignore examples

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
        # See to_test.py element_specific for capture/ignore examples
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
        # See to_test.py element_specific for capture/ignore examples

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
            {"NORM": {"IN": self.options}},
        ]
        # See to_test.py element_specific for capture/ignore examples
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
            {"NORM": {"IN": self.options}},
        ]
        # See to_test.py element_specific for capture/ignore examples
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
            {"NORM": {"IN": ["spoon", "spoonful"]}},
        ]
        # See to_test.py element_specific for capture/ignore examples
        self.matcher.add(f"{self.element_key}_{pattern_name}", [self.pattern])
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "low": 0,
            "high": 2,
            "units": -1,
            "spoonsize": -3,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        # For doseRange, resolve (s) using the high value (e.g. "1 to 2 tablet(s)" → "tablets")
        high = token_dict["high"]
        units = _resolve_parenthetical_s(token_dict["units"], high)
        found_dict["units"].append(units)
        found_dict["low"].append(token_dict["low"])
        found_dict["high"].append(high)
        found_dict["spoonsize"].append(token_dict["spoonsize"])
        if pattern_name == "pattern1":
            formatted_phrase = f"{found_dict['low'][-1]} to {high} {units}"
        elif pattern_name == "pattern2":
            formatted_phrase = f"up to {high} {units}"
        elif pattern_name == "pattern3":
            formatted_phrase = f"{found_dict['low'][-1]} to {high} x {found_dict['spoonsize'][-1]}ml spoonfuls"
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
            {"NORM": {"IN": self.options}},
        ]
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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

        # See to_test.py element_specific for capture/ignore examples
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
            formatted_phrase = f"at a rate of {found_dict['low'][-1]} to {found_dict['high'][-1]} {found_dict['special_unit'][-1]}"
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

        # See to_test.py element_specific for capture/ignore examples
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
        self.options = [
            u
            for u in myconstants.period_unit_config["options"]
            if u not in ("week", "fortnight", "month", "year", "annual")
        ]
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
                {"NORM": {"IN": self.options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"NORM": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"NORM": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": "time"},
                {"NORM": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"NORM": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": "time"},
                {"NORM": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"NORM": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": "once"},
                {"NORM": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"NORM": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                formatted_phrase = f"once every {found_dict['period_unit'][-1]}"
            elif found_dict["frequency"][-1] == 2:
                formatted_phrase = f"twice every {found_dict['period_unit'][-1]}"
            else:
                formatted_phrase = f"{found_dict['frequency'][-1]} times every {found_dict['period_unit'][-1]}"
        elif pattern_name in ["pattern1once"]:
            found_dict["frequency"][-1] = "1"
            formatted_phrase = f"once every {found_dict['period_unit'][-1]}"
        elif pattern_name in ["pattern2"]:
            formatted_phrase = (
                f"{found_dict['frequency'][-1]} to {found_dict['frequencyMax'][-1]} "
                f"times every {found_dict['period_unit'][-1]}"
            )
        elif pattern_name in ["pattern3"]:
            formatted_phrase = f"up to {found_dict['frequencyMax'][-1]} times every {found_dict['period_unit'][-1]}"
        elif pattern_name in ["pattern3.once"]:
            found_dict["frequencyMax"][-1] = "1"
            formatted_phrase = f"up to once every {found_dict['period_unit'][-1]}"
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
                {"NORM": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"NORM": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"NORM": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": "time"},
                {"NORM": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"NORM": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": "time"},
                {"NORM": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"NORM": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": "once"},
                {"NORM": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"NORM": {"IN": myconstants.period_unit_config["options"]}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                formatted_phrase = f"once every {found_dict['period_unit'][-1]}"
            elif found_dict["frequency"][-1] == 2:
                formatted_phrase = f"twice every {found_dict['period_unit'][-1]}"
            else:
                formatted_phrase = f"{found_dict['frequency'][-1]} times every {found_dict['period_unit'][-1]}"
        elif pattern_name in ["pattern1.once.tobetaken"]:
            found_dict["frequency"][-1] = "1"
            formatted_phrase = f"once every {found_dict['period_unit'][-1]}"
        elif pattern_name in ["pattern2.tobetaken"]:
            formatted_phrase = (
                f"{found_dict['frequency'][-1]} to {found_dict['frequencyMax'][-1]} "
                f"times every {found_dict['period_unit'][-1]}"
            )
        elif pattern_name in [
            "pattern3.tobetaken",
        ]:
            formatted_phrase = f"up to {found_dict['frequencyMax'][-1]} times every {found_dict['period_unit'][-1]}"
        elif pattern_name in ["pattern3.once.tobetaken"]:
            found_dict["frequencyMax"][-1] = "1"
            formatted_phrase = f"up to once every {found_dict['period_unit'][-1]}"
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
                {"NORM": "time"},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "count": 0,
        }
        pattern_name = "pattern1once"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"NORM": "once"},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": "time"},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": "time"},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
            found_dict["count"][-1] = "1"
            formatted_phrase = "once"
        elif pattern_name == "pattern2":
            formatted_phrase = (
                f"{found_dict['count'][-1]} to {found_dict['countMax'][-1]} times"
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
    element_split = ["period", "periodMax", "period_units", "frequency"]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = [
            u
            for u in myconstants.period_unit_config["options"]
            if u not in ("year", "annual")
        ]
        self.prefixes = myconstants.period_unit_config["prefixes"]
        self.suffixes = myconstants.period_unit_config["suffixes"]

    def define_pattern(self):
        self.metadata = {}
        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"NORM": {"IN": self.prefixes}},
                {"NORM": {"IN": self.options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "period_units": 1,
        }
        pattern_name = "pattern2"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"NORM": {"IN": self.prefixes}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"NORM": {"IN": self.options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.prefixes}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"TEXT": {"IN": ["to", "-", "or"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"NORM": {"IN": self.options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "period_units": -1,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        found_dict["period"].append(token_dict["period"])
        found_dict["period"][-1] = found_dict["period"][-1] or "1"
        found_dict["periodMax"].append(token_dict["periodMax"])
        found_dict["period_units"].append(token_dict["period_units"])
        found_dict["frequency"].append(myconstants.IMPLIED_FREQUENCY)
        if pattern_name == "pattern1":
            formatted_phrase = f"once every {found_dict['period_units'][-1]}"
        elif pattern_name == "pattern2":
            if found_dict["period"][-1] == "1":
                formatted_phrase = f"once every {found_dict['period_units'][-1]}"
            else:
                formatted_phrase = f"once every {found_dict['period'][-1]} {found_dict['period_units'][-1]}"
        elif pattern_name == "pattern3":
            formatted_phrase = f"once every {found_dict['period'][-1]} to {found_dict['periodMax'][-1]} {found_dict['period_units'][-1]}"
        elif pattern_name == "pattern4":
            found_dict["period"][-1] = "2"
            formatted_phrase = f"once every 2 {found_dict['period_units'][-1]}s"
        elif pattern_name == "pattern5":
            found_dict["period"][-1] = "2"
            formatted_phrase = f"once every 2 {found_dict['period_units'][-1]}"
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

        # See to_test.py element_specific for capture/ignore examples
        self.register_patterns_with_multiword(
            "pattern1",
            base_tokens=[
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LOWER": {"IN": ["to", "or", "-"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"NORM": {"IN": self.period_unit_options}},
            ],
            options=self.options,
            metadata={"when": [0, None], "offset": 0, "offsetMax": 2, "period_unit": 3},
        )

        # See to_test.py element_specific for capture/ignore examples
        self.register_patterns_with_multiword(
            "pattern2a",
            base_tokens=[
                {"LOWER": "at"},
                {"LOWER": "least"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"NORM": {"IN": self.period_unit_options}},
            ],
            options=self.options,
            metadata={"when": [0, None], "offset": 2, "period_unit": 3},
        )

        # See to_test.py element_specific for capture/ignore examples
        self.register_patterns_with_multiword(
            "pattern2b",
            base_tokens=[
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"NORM": {"IN": self.period_unit_options}},
            ],
            options=self.options,
            metadata={"when": [0, None], "offset": 0, "period_unit": 1},
        )

        # See to_test.py element_specific for capture/ignore examples
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
        self.options = myconstants.when_config["options"]
        self.period_unit_options = myconstants.period_unit_config["options"]

    def define_pattern(self):
        self.metadata = {}

        # See to_test.py element_specific for capture/ignore examples
        self.register_patterns_with_multiword(
            "pattern1",
            base_tokens=[
                {"LOWER": "to"},
                {"LOWER": "be"},
                {"LOWER": {"IN": myconstants.method_config["past_participles"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"LOWER": {"IN": ["to", "or", "-"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"NORM": {"IN": self.period_unit_options}},
            ],
            options=self.options,
            metadata={"when": [0, None], "offset": 3, "offsetMax": 5, "period_unit": 6},
        )

        # See to_test.py element_specific for capture/ignore examples
        self.register_patterns_with_multiword(
            "pattern2a",
            base_tokens=[
                {"LOWER": "to"},
                {"LOWER": "be"},
                {"LOWER": {"IN": myconstants.method_config["past_participles"]}},
                {"LOWER": "at"},
                {"LOWER": "least"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"NORM": {"IN": self.period_unit_options}},
            ],
            options=self.options,
            metadata={"when": [0, None], "offset": 5, "period_unit": 6},
        )

        # See to_test.py element_specific for capture/ignore examples
        self.register_patterns_with_multiword(
            "pattern2b",
            base_tokens=[
                {"LOWER": "to"},
                {"LOWER": "be"},
                {"LOWER": {"IN": myconstants.method_config["past_participles"]}},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"NORM": {"IN": self.period_unit_options}},
            ],
            options=self.options,
            metadata={"when": [0, None], "offset": 3, "period_unit": 4},
        )

        # See to_test.py element_specific for capture/ignore examples
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
    element_split = ["value", "valueMax", "milligram_units", "low_unit"]

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
                {
                    "LOWER": {"IN": ["or", "to"]}
                },  # Excluded "-" because 1- 60mg could be ambiguous
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"LOWER": {"IN": self.options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
        # See to_test.py element_specific for capture/ignore examples
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 0,
            "low_unit": 1,
            "valueMax": 3,
            "milligram_units": 4,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        found_dict["value"].append(token_dict["value"])
        found_dict["valueMax"].append(token_dict["valueMax"])
        found_dict["milligram_units"].append(token_dict["milligram_units"])
        found_dict["low_unit"].append(token_dict["low_unit"])
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
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
                # {"TEXT": {"IN": [",", "and"]}, "OP": "*"},  # Removed due to rule 7
                # {"NORM": {"IN": self.options}, "OP": "*"},  # Removed due to rule 7
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                # {"NORM": {"REGEX": "^([0-9]|10|11|12)(am|pm|noon)$"}, "OP": "*"},  # Removed due to rule 7
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
        self.pattern.append(
            [
                {"LOWER": "at"},
                {"NORM": {"REGEX": "^(0[1-9]|1[0-9]|2[0-4]):(00|15|30|45)$"}},
                # {"TEXT": {"IN": [",", "and"]}, "OP": "*"},
                # {
                #     "NORM": {"REGEX": "^(0?[0-9]|1[0-9]|2[0-4]):(00|15|30|45)$"},
                #     "OP": "*",
                # }, # Removed due to rule 7
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 0
        }  # not used as span is taken in phrase parts

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
        # Denominator period restricted to week or shorter (no fortnight/month/year)
        self.denom_options = [
            u
            for u in myconstants.period_unit_config["options"]
            if u not in ("fortnight", "month", "year", "annual")
        ]

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
                {"NORM": {"IN": self.options}},
                {"LOWER": "in"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"NORM": {"IN": self.denom_options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
                {"LOWER": "in"},
                {"LOWER": "a"},
                {"NORM": {"IN": self.denom_options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
                {"NORM": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"NORM": {"IN": self.denom_options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
                {"LOWER": "in"},
                {"TEXT": {"REGEX": "^[0-9]+$"}},
                {"NORM": {"IN": self.denom_options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
                {"LOWER": "in"},
                {"LOWER": "a"},
                {"NORM": {"IN": self.denom_options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
                {"NORM": {"IN": myconstants.period_unit_config["prefixes"]}},
                {"NORM": {"IN": self.denom_options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "num_value": -4,
            "num_unit": -3,
            "denom_unit": -1,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        pattern_name = token_dict["pattern_name"]
        num_value = token_dict["num_value"]
        num_unit = _resolve_parenthetical_s(token_dict["num_unit"], num_value)
        found_dict["num_value"].append(num_value)
        found_dict["num_unit"].append(num_unit)
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
            f"up to a maximum of {num_value} {num_unit} "
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
                {"NORM": {"IN": self.options}},
                {"LOWER": "per"},
                {"LOWER": "dose"},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
                {"LOWER": "per"},
                {"LOWER": "dose"},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 3,
            "unit": 4,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        value = token_dict["value"]
        unit = _resolve_parenthetical_s(token_dict["unit"], value)
        found_dict["value"].append(value)
        found_dict["unit"].append(unit)
        formatted_phrase = f"up to a maximum of {value} {unit} per dose"
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
                {"NORM": {"IN": self.options}},
                {"LOWER": {"IN": ["in", "per", "for"]}},
                {"LOWER": {"IN": ["the"]}, "OP": "?"},
                {"LOWER": "lifetime"},
                {"LOWER": "of", "OP": "?"},
                {"LOWER": "the", "OP": "?"},
                {"LOWER": "patient", "OP": "?"},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
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
        # See to_test.py element_specific for capture/ignore examples
        pattern_name = "pattern3"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
            [
                {"LOWER": {"IN": ["not", "no"]}},
                {"LOWER": "more"},
                {"LOWER": "than"},
                {"TEXT": {"REGEX": "^[0-9]+(\\.5|\\.25)?$"}},
                {"NORM": {"IN": self.options}},
                {"LOWER": {"IN": ["in", "per", "for"]}},
                {"LOWER": {"IN": ["the"]}, "OP": "?"},
                {"LOWER": "lifetime"},
                {"LOWER": "of", "OP": "?"},
                {"LOWER": "the", "OP": "?"},
                {"LOWER": "patient", "OP": "?"},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
        self.matcher.add(f"{self.element_key}_{pattern_name}", self.pattern)
        self.metadata[f"{self.element_key}_{pattern_name}"] = {
            "value": 3,
            "unit": 4,
        }

    def phrase_parts(self, span, found_dict, token_dict):
        value = token_dict["value"]
        unit = _resolve_parenthetical_s(token_dict["unit"], value)
        found_dict["value"].append(value)
        found_dict["unit"].append(unit)
        formatted_phrase = (
            f"up to a maximum of {value} {unit} for the lifetime of patient"
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
    ]

    def __init__(self, nlp, matcher):
        super().__init__(nlp, matcher)
        self.define_options()
        self.define_pattern()

    def define_options(self):
        self.options = [
            u for u in myconstants.period_unit_config["options"] if u not in ("minute",)
        ]
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
                {"NORM": {"IN": self.options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
                {"NORM": {"IN": self.options}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
        return formatted_phrase, found_dict


class BoundsPeriodElement(BaseElement):
    """
    Matches date ranges like "from 01.01.2025 to 31.12.2025".

    Dates must arrive as SINGLE tokens for the TEXT regex to match. This relies
    on preprocessing normalising "/" and "-" separators to "." before spaCy
    tokenises the text. See docs/preprocessing_dates.md for details.
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
        # See to_test.py element_specific for capture/ignore examples
        self.pattern.append(
            [
                {"LOWER": "from"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_ymd}"}},
                {"LOWER": "to"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_ymd}"}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
    Matches single-ended date bounds: "from 01.01.2025" or "until 31.12.2025".

    Dates must arrive as SINGLE tokens for the TEXT regex to match. This relies
    on preprocessing normalising "/" and "-" separators to "." before spaCy
    tokenises the text. See docs/preprocessing_dates.md for details.
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
        # See to_test.py element_specific for capture/ignore examples
        self.pattern.append(
            [
                {"LOWER": "from"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_ymd}"}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
        # See to_test.py element_specific for capture/ignore examples
        self.pattern.append(
            [
                {"LOWER": "until"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_ymd}"}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
    Matches specific dates: "on 01.01.2025".

    Dates must arrive as SINGLE tokens for the TEXT regex to match. This relies
    on preprocessing normalising "/" and "-" separators to "." before spaCy
    tokenises the text. See docs/preprocessing_dates.md for details.
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
        # See to_test.py element_specific for capture/ignore examples
        self.pattern.append(
            [
                {"LOWER": "on"},
                {"TEXT": {"REGEX": f"{myconstants.date_reg_ymd}"}},
            ]
        )
        # See to_test.py element_specific for capture/ignore examples
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
        self.options = myconstants.for_config

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
            "pattern3",
            [{"LOWER": "as"}, {"LOWER": "necessary"}],
            self.options,
            metadata={"value": [0, None]},
        )

        self.register_patterns_with_multiword(
            "pattern4",
            [{"LOWER": "when"}, {"LOWER": "needed"}],
            self.options,
            metadata={"value": [0, None]},
        )

        self.register_patterns_with_multiword(
            "pattern5",
            [{"LOWER": "when"}, {"LOWER": "required"}],
            self.options,
            metadata={"value": [0, None]},
        )

        self.register_patterns_with_multiword(
            "pattern6",
            [{"LOWER": "when"}, {"LOWER": "necessary"}],
            self.options,
            metadata={"value": [0, None]},
        )

        self.register_patterns_with_multiword(
            "pattern7",
            [{"LOWER": "if"}, {"LOWER": "needed"}],
            self.options,
            metadata={"value": [0, None]},
        )

        self.register_patterns_with_multiword(
            "pattern8",
            [{"LOWER": "if"}, {"LOWER": "required"}],
            self.options,
            metadata={"value": [0, None]},
        )

        self.register_patterns_with_multiword(
            "pattern9",
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
        self.options = myconstants.for_config

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
        self.options = myconstants.for_config
        self.prefixes = [""]
        self.next_prefix = [""]
        self.suffixes = [""]

    def define_pattern(self):
        self.metadata = {}

        pattern_name = "pattern1"
        self.meta_creator(pattern_name)
        self.pattern = []
        self.pattern.append(
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


DASHABLE_GROUP = frozenset(
    {
        "frequencyBare",
        "dose_QuantityValueAndMaxOnly",
        "doseRange",
        "doseXMilliValueOnly",
        "milligramMax",
        "whenBare",
        "doseQuantity",
        "count",
    }
)
DASH_AT_START_RE = _re.compile(r"^\s*\d+\s*-\s*\d+")


def _is_dashed_instance(elem_key: str, span_text: str) -> bool:
    """
    Return True when this element should be emitted as *{elem_key}Dashed* in
    dosage_elements, i.e. when it is one of the allowed dashable element types
    and its matched text begins with a numeric dash range.
    """
    return elem_key in DASHABLE_GROUP and DASH_AT_START_RE.match(span_text) is not None


def _extract_single_row(text, elements, elements_by_key, priority_map, nlp, matcher):
    """
    Extract all elements from a single text string in one spaCy pass.

    Steps:
      1. Tokenise text and run all Matcher patterns at once
      2. Map each match back to its owning element extractor
      3. Resolve overlapping spans (higher-priority element wins)
      4. For each winning match, call the element's phrase_parts() to get structured output
      5. Build the remainder string with *elementKey* markers
    """
    # Pre-fill with None so every column exists even if nothing matches
    empty = {"dosage_elements": text}
    for element in elements:
        empty[f"{element.element_key}_clean"] = None
        empty[f"{element.element_key}_captured"] = None
        for split_field in element.element_split:
            empty[f"{element.element_key}_{split_field}"] = []

    if not text or not text.strip():
        return empty

    # --- Step 1: Tokenize once and run ALL patterns in one Matcher call ---
    doc = nlp(text)
    matches = matcher(doc)

    # --- Step 2: Identify which element class each match belongs to ---
    # The Matcher returns ALL matches from ALL element types. We group them by checking
    # which element_key the match label starts with (labels are "{element_key}_{pattern_name}")
    candidates = []
    for match_id, start, end in matches:
        label = doc.vocab.strings[match_id]
        for element in elements:
            if label.startswith(f"{element.element_key}_"):
                candidates.append((element.element_key, label, start, end))
                break

    # --- Step 3: Resolve overlapping spans ---
    # Sort by priority first (position in `element_types` list — lower index = higher priority),
    # then by span start position, then prefer longest span (negative length).
    # This ensures higher-priority element types claim their spans before lower-priority ones,
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

    # Post-resolution rescue: if methodDirect claimed a dual-purpose word (spray/suck)
    # that also appears as a unit in a doseQuantity candidate immediately after a number,
    # prefer doseQuantity (the longer, more informative span).  Rule 2 (singular/plural
    # mismatch) will then catch badly-written cases like "5 spray per day" (qty=5 + singular).
    _DUAL_METHOD_UNIT_WORDS = {"spray", "suck"}
    if "methodDirect" in resolved:
        md_label, md_start, md_end = resolved["methodDirect"]
        method_text = doc[md_start:md_end].text.lower().lstrip("to ")
        if method_text in _DUAL_METHOD_UNIT_WORDS:
            for _ek, _lbl, _s, _e in candidates:
                if (
                    _ek == "doseQuantity"
                    and _e == md_end
                    and _s < md_start
                    and doc[_s].like_num
                ):
                    # Drop method, drop orphaned dose_QuantityValueOnly, claim doseQuantity
                    taken_ranges = [
                        (s, e) for s, e in taken_ranges if (s, e) != (md_start, md_end)
                    ]
                    del resolved["methodDirect"]
                    if "dose_QuantityValueOnly" in resolved:
                        qvo_s, qvo_e = (
                            resolved["dose_QuantityValueOnly"][1],
                            resolved["dose_QuantityValueOnly"][2],
                        )
                        taken_ranges = [
                            (s, e) for s, e in taken_ranges if (s, e) != (qvo_s, qvo_e)
                        ]
                        del resolved["dose_QuantityValueOnly"]
                    taken_ranges.append((_s, _e))
                    resolved["doseQuantity"] = (_lbl, _s, _e)
                    break

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
                    # Remove any already-resolved element whose span is fully subsumed
                    # by the newly promoted WithMethod span. This prevents e.g.
                    # frequencyBare being retained when frequencyWithMethod is promoted
                    # to cover the same tokens — the bare element won its span before
                    # the rescue ran so normal overlap detection didn't catch it.
                    subsumed = [
                        k
                        for k, (_, s, e) in list(resolved.items())
                        if k != with_method_key and s >= start and e <= end
                    ]
                    for k in subsumed:
                        sub_s, sub_e = resolved[k][1], resolved[k][2]
                        resolved.pop(k)
                        taken_ranges = [
                            (s, e)
                            for s, e in taken_ranges
                            if not (s == sub_s and e == sub_e)
                        ]
                    break
            if "methodPassive" not in resolved:
                break

    # --- Step 4: For each winning match, extract structured fields via phrase_parts() ---
    result = dict(empty)

    for elem_key, (label, start, end) in resolved.items():
        element = elements_by_key[elem_key]
        span = doc[start:end]

        # Build token_dict exactly as extract_element_using_matcher() does:
        # uses metadata positions to pull out the important tokens from the span
        token_dict = {}
        for key in element.element_split:
            token_dict[key] = ""
        for key, position in element.metadata[label].items():
            if isinstance(position, list):
                sliced = span[position[0] : position[1]]
                token_dict[key] = sliced.text
            else:
                token = span[position]
                token_dict[key] = token.text
                token_dict[f"{key}_token"] = token
        token_dict["pattern_name"] = label.replace(f"{elem_key}_", "")

        # phrase_parts() formats the output string and populates found_dict
        found_dict = {var: [] for var in element.element_split}
        formatted_phrase, found_dict = element.phrase_parts(
            span, found_dict, token_dict
        )
        if formatted_phrase is None:
            continue

        result[f"{elem_key}_clean"] = formatted_phrase
        result[f"{elem_key}_captured"] = span.text
        for split_field in element.element_split:
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

        span = doc[start:end]
        emitted_key = (
            f"{elem_key}Dashed"
            if _is_dashed_instance(elem_key, span.text)
            else elem_key
        )

        char_start = doc[start].idx
        char_end = doc[end - 1].idx + len(doc[end - 1])
        replacements.append((char_start, char_end, f"*{emitted_key}*"))

    # Replace from end-to-start so earlier positions aren't shifted by insertions
    replacements.sort(key=lambda r: r[0], reverse=True)
    remainder = text
    for char_start, char_end, replacement in replacements:
        remainder = remainder[:char_start] + replacement + remainder[char_end:]

    # Normalize whitespace (same as the original regexp_replace(r"\s+", " ") in update_df)
    result["dosage_elements"] = _re.sub(r"\s+", " ", remainder).strip()
    return result


def create_extract_all_udf(elements, bc_nlp, bc_matcher):
    """
    Create a pandas_udf that extracts all elements in a single spaCy/Matcher pass.

    Overview
    --------
    Each dosage string (e.g. "take 2 tablets 3 times a day") needs to be parsed
    into structured fields (dose quantity, frequency, method, etc.). Rather than
    running ~30 separate UDFs — one per element type — this function creates a
    **single** ``pandas_udf`` that does everything in one call:

    1. **spaCy tokenises** the text once.
    2. The **Matcher** runs all ~30 element patterns simultaneously, returning
       every match in one pass.
    3. ``_extract_single_row()`` resolves overlapping matches (higher-priority
       element wins), then calls each element's ``phrase_parts()`` to produce
       the structured output (``_clean``, ``_captured``, and sub-field arrays).
    4. The UDF returns a struct column containing all element fields, which the
       caller unpacks into individual DataFrame columns.

    Using a ``pandas_udf`` means Spark sends rows in **vectorised batches**
    (Arrow-serialised chunks) rather than one-at-a-time, significantly reducing
    JVM ↔ Python serialisation overhead.

    The ``bc_nlp`` and ``bc_matcher`` broadcast variables ensure the large spaCy
    model and compiled Matcher are sent to each executor **once**, not copied
    per-row or per-partition.

    Parameters
    ----------
    elements : list[BaseElement]
        Initialised element extractor objects (in priority order — lower index
        wins when two elements match the same tokens).
    bc_nlp : pyspark.Broadcast
        Broadcast spaCy ``nlp`` pipeline (tokenizer + lemmatizer + norm_from_lemma).
    bc_matcher : pyspark.Broadcast
        Broadcast spaCy ``Matcher`` with all element patterns registered.

    Returns
    -------
    pandas_udf
        A Spark UDF that accepts a string column and returns a struct column
        with all element fields (schema derived from ``element_types``).
    """
    schema = build_extraction_schema(element_types)
    # Priority = position in element_types list (lower index = higher priority = wins overlaps)
    priority_map = {elem.element_key: idx for idx, elem in enumerate(elements)}
    elements_by_key = {elem.element_key: elem for elem in elements}

    array_columns = [f.name for f in schema.fields if isinstance(f.dataType, ArrayType)]

    @pandas_udf(schema)
    def extract_all_udf(texts: pd.Series) -> pd.DataFrame:
        # Retrieve broadcast objects once per batch (not per row)
        nlp = bc_nlp.value
        matcher = bc_matcher.value
        rows = [
            _extract_single_row(
                text, elements, elements_by_key, priority_map, nlp, matcher
            )
            for text in texts
        ]
        df = pd.DataFrame(rows, columns=[f.name for f in schema.fields])
        for col in array_columns:
            df[col] = df[col].apply(lambda x: x if isinstance(x, list) else [])
        return df

    return extract_all_udf


# ---------------------------------------------------------------------------
# Element types — ordered list of all element extractor classes.
#
# Order matters: earlier entries have higher priority and win when two
# element types match the same tokens. See _extract_single_row() for the
# overlap resolution logic.
# ---------------------------------------------------------------------------
element_types = [
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
# Full Lookup Schema (generated from the element_types list)
# ---------------------------------------------------------------------------
# This is the complete output schema for the lookup table. It's built by iterating
# element_types and reading their element_key/element_split class attributes,
# so it automatically stays in sync when you add/remove/rename element types.


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

    # --- Element columns (derived from element_types list) ---
    for element_type in element_types:
        fields.append(
            StructField(f"{element_type.element_key}_clean", StringType(), True)
        )
        fields.append(
            StructField(f"{element_type.element_key}_captured", StringType(), True)
        )
        for split_field in element_type.element_split:
            fields.append(
                StructField(
                    f"{element_type.element_key}_{split_field}",
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
