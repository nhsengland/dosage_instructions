"""
Tests for element_order_rules validation.

Tests evaluate_rules() directly (no Spark needed) and validate_dosage_elements() via Spark.

evaluate_rules() takes a dosage_elements string (with *elementKey* markers) and returns:
  - None if valid
  - Comma-separated rule codes if invalid (e.g. "1a", "1c", "not fully captured")
"""

import sys
import os
import pytest

# sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dosage_instructions.model.element_order_rules import (
    evaluate_rules,
    validate_dosage_elements,
)

# ─── evaluate_rules (pure Python, no Spark) ───────────────────────────────────


class TestEvaluateRulesValid:
    """Inputs that should pass all rules (returns None)."""

    def test_single_method_and_dose(self):
        # *methodDirect* *doseQuantity* *periodElement*
        assert evaluate_rules("*methodDirect* *doseQuantity* *periodElement*") is None

    def test_empty_string(self):
        assert evaluate_rules("") is None

    def test_none_input(self):
        assert evaluate_rules(None) is None

    def test_method_dose_and_timing(self):
        assert evaluate_rules("*methodDirect* *doseQuantity* *frequencyBare*") is None


class TestEvaluateRulesFreeText:
    """Leftover free text should be flagged."""

    def test_free_text_before_element(self):
        result = evaluate_rules("hello *methodDirect*")
        assert result == "not fully captured"

    def test_free_text_after_element(self):
        result = evaluate_rules("*methodDirect* leftover")
        assert result == "not fully captured"

    def test_only_free_text(self):
        result = evaluate_rules("some random text")
        assert result == "not fully captured"


class TestEvaluateRulesRule0:
    """Rule 0: Must have (amount OR action) AND timing."""

    def test_dose_without_timing_is_invalid(self):
        result = evaluate_rules("*methodDirect* *doseQuantity*")
        assert result is not None
        assert "0" in result

    def test_timing_without_dose_or_action_is_invalid(self):
        result = evaluate_rules("*periodElement*")
        assert result is not None
        assert "0" in result

    def test_action_and_timing_is_valid(self):
        result = evaluate_rules("*methodDirect* *frequencyBare*")
        assert result is None or "0" not in result

    def test_dose_and_timing_is_valid(self):
        result = evaluate_rules("*doseQuantity* *periodElement*")
        assert result is None or "0" not in result


class TestEvaluateRulesRule1a:
    """Rule 1a: At most one 'to be taken' group element per sentence."""

    def test_two_tbt_elements_same_sentence_is_invalid(self):
        result = evaluate_rules("*methodPassive* *frequencyWithMethod* *doseQuantity*")
        assert result is not None
        assert "1a" in result

    def test_two_tbt_elements_different_sentences_is_valid(self):
        result = evaluate_rules(
            "*methodPassive* *doseQuantity* *periodElement*. *frequencyWithMethod* *doseQuantity*"
        )
        assert result is None or "1a" not in result

    def test_single_tbt_element_is_valid(self):
        result = evaluate_rules("*methodPassive* *doseQuantity* *periodElement*")
        assert result is None or "1a" not in result


class TestEvaluateRulesRule1b:
    """Rule 1b: methodDirect + 'to be taken' element: methodDirect must come first and not adjacent."""

    def test_tbt_before_method_direct_is_invalid(self):
        result = evaluate_rules("*frequencyWithMethod* *methodDirect* *doseQuantity*")
        assert result is not None
        assert "1b" in result

    def test_method_direct_adjacent_to_tbt_is_invalid(self):
        result = evaluate_rules("*methodDirect* *frequencyWithMethod* *doseQuantity*")
        assert result is not None
        assert "1b" in result

    def test_method_direct_separated_from_tbt_is_valid(self):
        result = evaluate_rules("*methodDirect* *doseQuantity* *frequencyWithMethod*")
        assert result is None or "1b" not in result


class TestEvaluateRulesRule1c:
    """Rule 1c: methodDirect + methodPassive together is always invalid."""

    def test_both_methods_present(self):
        result = evaluate_rules("*methodDirect* *methodPassive* *doseQuantity*")
        assert result is not None
        assert "1c" in result

    def test_single_method_is_valid(self):
        result = evaluate_rules("*methodDirect* *doseQuantity* *periodElement*")
        assert result is None or "1c" not in result


class TestEvaluateRulesRule2:
    """Rule 2: methodDirect must not follow a dose element."""

    def test_dose_before_method(self):
        result = evaluate_rules("*doseQuantity* *methodDirect*")
        assert result is not None
        assert "2" in result

    def test_method_before_dose_is_valid(self):
        result = evaluate_rules("*methodDirect* *doseQuantity*")
        assert result is None or "2" not in result


class TestEvaluateRulesRule3:
    """Rule 3: Only one element per logical group."""

    def test_two_dose_elements_is_invalid(self):
        result = evaluate_rules("*doseQuantity* *doseRange* *periodElement*")
        assert result is not None
        assert "3" in result

    def test_two_frequency_elements_is_invalid(self):
        result = evaluate_rules("*methodDirect* *frequencyBare* *periodElement*")
        assert result is not None
        assert "3" in result

    def test_clarification_adjacent_is_valid(self):
        result = evaluate_rules(
            "*methodDirect* *doseQuantity* *milligramValue* *periodElement*"
        )
        assert result is None or "3" not in result

    def test_one_per_group_is_valid(self):
        result = evaluate_rules("*methodDirect* *doseQuantity* *frequencyBare*")
        assert result is None or "3" not in result


class TestEvaluateRulesRule4:
    """Rule 4: Dose before frequency (rescued by full stop or comma/dash)."""

    def test_frequency_before_dose_is_invalid(self):
        result = evaluate_rules("*methodDirect* *frequencyBare* *doseQuantity*")
        assert result is not None
        assert "4" in result

    def test_frequency_before_dose_with_comma_is_valid(self):
        result = evaluate_rules("*methodDirect* *frequencyBare*, *doseQuantity*")
        assert result is None or "4" not in result

    def test_frequency_before_dose_different_sentence_is_valid(self):
        result = evaluate_rules(
            "*methodDirect* *frequencyBare*. *doseQuantity* *periodElement*"
        )
        assert result is None or "4" not in result

    def test_dose_before_frequency_is_valid(self):
        result = evaluate_rules("*methodDirect* *doseQuantity* *frequencyBare*")
        assert result is None or "4" not in result


class TestEvaluateRulesRule7:
    """Rule 7: WhenBare/Site before dose -> AMBIGUOUS (rescued by full stop or comma/dash)."""

    def test_when_before_dose_is_invalid(self):
        result = evaluate_rules(
            "*methodDirect* *whenBare* *doseQuantity* *periodElement*"
        )
        assert result is not None
        assert "7" in result

    def test_site_before_dose_is_invalid(self):
        result = evaluate_rules("*methodDirect* *site* *doseQuantity* *periodElement*")
        assert result is not None
        assert "7" in result

    def test_when_before_dose_with_comma_is_valid(self):
        result = evaluate_rules(
            "*methodDirect* *whenBare*, *doseQuantity* *periodElement*"
        )
        assert result is None or "7" not in result

    def test_dose_before_when_is_valid(self):
        result = evaluate_rules(
            "*methodDirect* *doseQuantity* *whenBare* *periodElement*"
        )
        assert result is None or "7" not in result


class TestEvaluateRulesRule8:
    """Rule 8: ForElement/AsNeeded before both dose AND frequency -> AMBIGUOUS."""

    def test_for_before_dose_and_freq_is_invalid(self):
        result = evaluate_rules("*forElement* *doseQuantity* *frequencyBare*")
        assert result is not None
        assert "8" in result

    def test_as_needed_before_dose_and_freq_is_invalid(self):
        result = evaluate_rules("*asNeededBoolean* *doseQuantity* *frequencyBare*")
        assert result is not None
        assert "8" in result

    def test_for_before_dose_and_freq_with_comma_is_valid(self):
        result = evaluate_rules("*forElement*, *doseQuantity* *frequencyBare*")
        assert result is None or "8" not in result

    def test_for_after_dose_is_valid(self):
        result = evaluate_rules(
            "*methodDirect* *doseQuantity* *frequencyBare* *forElement*"
        )
        assert result is None or "8" not in result


class TestEvaluateRulesRule9a:
    """Rule 9a: extrasALTER present -> INVALID (unless in separate sentence)."""

    def test_extras_alter_same_sentence_is_invalid(self):
        result = evaluate_rules(
            "*methodDirect* *doseQuantity* *extrasALTER* *periodElement*"
        )
        assert result is not None
        assert "9a" in result

    def test_extras_alter_in_separate_sentence_is_valid(self):
        result = evaluate_rules(
            "*methodDirect* *doseQuantity* *periodElement*. *extrasALTER*"
        )
        assert result is None or "9a" not in result


class TestEvaluateRulesRule9b:
    """Rule 9b: extrasPAUSE needs punctuation/sentence boundary between it and other elements."""

    def test_extras_pause_without_boundary_is_invalid(self):
        result = evaluate_rules(
            "*methodDirect* *doseQuantity* *extrasPAUSE* *periodElement*"
        )
        assert result is not None
        assert "9b" in result

    def test_extras_pause_in_separate_sentence_is_valid(self):
        result = evaluate_rules(
            "*methodDirect* *doseQuantity* *periodElement*. *extrasPAUSE*"
        )
        assert result is None or "9b" not in result


class TestEvaluateRulesRule9c:
    """Rule 9c: extras_b needs punctuation/sentence boundary between it and other elements."""

    def test_extras_b_without_boundary_is_invalid(self):
        result = evaluate_rules(
            "*methodDirect* *doseQuantity* *extras_b* *periodElement*"
        )
        assert result is not None
        assert "9c" in result

    def test_extras_b_in_separate_sentence_is_valid(self):
        result = evaluate_rules(
            "*methodDirect* *doseQuantity* *periodElement*. *extras_b*"
        )
        assert result is None or "9c" not in result

    def test_extras_b_does_not_trigger_9c_when_in_separate_sentence(self):
        result = evaluate_rules(
            "*methodDirect* *doseQuantity* *periodElement*. *extras_b*"
        )
        assert result is None or "9c" not in result


class TestEvaluateRulesRule10:
    """Rule 10: Singular DayOfWeek + any Frequency element -> INVALID."""

    def test_day_of_week_with_frequency_is_invalid(self):
        result = evaluate_rules(
            "*methodDirect* *doseQuantity* *dayOfWeek* *frequencyBare*"
        )
        assert result is not None
        assert "10" in result

    def test_day_of_week_without_frequency_is_valid(self):
        result = evaluate_rules("*methodDirect* *doseQuantity* *dayOfWeek*")
        assert result is None or "10" not in result

    def test_frequency_without_day_of_week_is_valid(self):
        result = evaluate_rules("*methodDirect* *doseQuantity* *frequencyBare*")
        assert result is None or "10" not in result


# ─── validate_dosage_elements (Spark integration) ─────────────────────────────


class TestValidateDosageElements:
    """Test the Spark DataFrame wrapper."""

    def test_adds_expected_columns(self, spark):
        from pyspark.sql.types import StructType, StructField, StringType

        schema = StructType([StructField("dosage_elements", StringType())])
        df = spark.createDataFrame(
            [("*methodDirect* *doseQuantity*",)],
            schema=schema,
        )
        result = validate_dosage_elements(df)
        columns = result.columns
        assert "exclude" in columns
        assert "dosage_spare" in columns
        assert "mapped" in columns

    def test_fully_mapped_row(self, spark):
        from pyspark.sql.types import StructType, StructField, StringType

        schema = StructType([StructField("dosage_elements", StringType())])
        df = spark.createDataFrame(
            [("*methodDirect* *doseQuantity* *periodElement*",)],
            schema=schema,
        )
        result = validate_dosage_elements(df)
        row = result.collect()[0]
        assert row["mapped"] is True
        assert row["exclude"] is None

    def test_free_text_not_mapped(self, spark):
        from pyspark.sql.types import StructType, StructField, StringType

        schema = StructType([StructField("dosage_elements", StringType())])
        df = spark.createDataFrame(
            [("*methodDirect* leftover text",)],
            schema=schema,
        )
        result = validate_dosage_elements(df)
        row = result.collect()[0]
        assert row["mapped"] is False
        assert "not fully captured" in row["exclude"]
