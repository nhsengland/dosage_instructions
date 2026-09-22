"""
Unit tests for helper functions in dosage_repo/functions.

No Spark or spaCy required — these test pure Python utility functions.
"""

import sys
import os
import pytest

# sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dosage_instructions.model.functions import (
    remove_first_match,
    get_all_combinations,
)
from dosage_instructions.model.preprocessing import (
    add_dots_to_latin,
)

# ─── remove_first_match ──────────────────────────────────────────────────────


class TestRemoveFirstMatch:

    def test_replaces_first_occurrence(self):
        result = remove_first_match("take 2 tablets daily", "daily", "freq")
        assert result == "take 2 tablets *freq*"

    def test_only_replaces_first_when_multiple(self):
        result = remove_first_match("daily daily", "daily", "freq")
        assert result == "*freq* daily"

    def test_returns_none_for_none_input(self):
        assert remove_first_match(None, "daily", "freq") is None

    def test_no_match_returns_original(self):
        result = remove_first_match("take 2 tablets", "daily", "freq")
        assert result == "take 2 tablets"

    def test_regex_pattern(self):
        result = remove_first_match("take 2 tablets", r"\d+", "num")
        assert result == "take *num* tablets"


# ─── get_all_combinations ─────────────────────────────────────────────────────


class TestGetAllCombinations:

    def test_simple_prefix_option_suffix(self):
        config = {
            "options": ["tablet"],
            "prefixes": [""],
            "suffixes": ["", "s"],
        }
        combo_dict, combo_list = get_all_combinations(config)
        assert "tablet" in combo_list
        assert "tablets" in combo_list

    def test_with_prefix(self):
        config = {
            "options": ["day"],
            "prefixes": ["every", ""],
            "suffixes": [""],
        }
        combo_dict, combo_list = get_all_combinations(
            config, how=["{prefix} {option}{suffix}"]
        )
        assert "every day" in combo_list
        assert "day" in [c.strip() for c in combo_list]

    def test_with_next_prefix(self):
        config = {
            "options": ["eye"],
            "prefixes": ["in the"],
            "next_prefixes": ["left", "right", ""],
            "suffixes": [""],
        }
        combo_dict, combo_list = get_all_combinations(
            config, how=["{prefix} {next_prefix} {option}{suffix}"]
        )
        assert "in the left eye" in combo_list
        assert "in the right eye" in combo_list

    def test_odd_spellings_corrected(self):
        config = {
            "options": ["day"],
            "prefixes": [""],
            "suffixes": ["ly"],
        }
        combo_dict, combo_list = get_all_combinations(
            config,
            odd_spellings={"daily": "dayly"},
            how=["{prefix}{option}{suffix}"],
        )
        assert "daily" in combo_list
        assert "dayly" not in combo_list

    def test_returns_dict_and_list(self):
        config = {
            "options": ["tablet"],
            "prefixes": [""],
            "suffixes": [""],
        }
        combo_dict, combo_list = get_all_combinations(config)
        assert isinstance(combo_dict, dict)
        assert isinstance(combo_list, list)
        assert "tablet" in combo_dict


# ─── add_dots_to_latin ────────────────────────────────────────────────────────


class TestAddDotsToLatin:

    def test_two_letter_abbreviation(self):
        result = add_dots_to_latin({"ac": "before food"})
        # Should produce regex pattern that matches "a.c." and "ac"
        assert "before food" in result.values()
        key = list(result.keys())[0]
        assert r"\.?" in key

    def test_three_letter_abbreviation(self):
        result = add_dots_to_latin({"tds": "to be taken 3 times daily"})
        key = list(result.keys())[0]
        # t\.?d\.?s
        assert "t" in key
        assert "d" in key
        assert "s" in key

    def test_preserves_values(self):
        input_dict = {"bd": "twice daily", "od": "every day"}
        result = add_dots_to_latin(input_dict)
        assert "twice daily" in result.values()
        assert "every day" in result.values()
