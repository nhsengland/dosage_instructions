"""
Unit tests for cross-column validity rules."""

import pytest
from dosage_instructions.model.cross_column_validity_rules import (
    rule_cc1_fortnight_singular,
    rule_cc2_dose_unit_mismatch,
    rule_vc1_exceeds_365_days,
    rule_vc2_dose_implausibly_high,
    rule_vc3_frequency_exceeds_max,
    rule_cc3_milligram_range_consistency,
    rule_cc4_max_dose_less_than_regular,
    rule_cc5_freq_period_vs_timing,
    rule_cc6_singular_timing_without_frequency,
    rule_cc7_freq_period_exceeds_duration,
    rule_cc8_event_with_period_gt_1_day,
    rule_cc9_event_or_count_with_bounds_duration,
    rule_cc10_freq_leq_1_with_multi_per_day_when,
    rule_cc12_period_without_single_dose,
    rule_cc13_each_every_when_with_non_day_period,
    evaluate_cross_column_rules,
)

# ---------------------------------------------------------------------------
# rule_cc1_fortnight_singular
# ---------------------------------------------------------------------------


class TestFortnightSingular:
    def test_period_1_fortnight_passes(self):
        row = {"periodElement_period_units": "fortnight", "periodElement_period": 1}
        assert rule_cc1_fortnight_singular(row) is None

    def test_period_2_fortnights_fails(self):
        row = {"periodElement_period_units": "fortnight", "periodElement_period": 2}
        assert rule_cc1_fortnight_singular(row) is not None

    def test_period_3_fortnights_fails(self):
        row = {"periodElement_period_units": "fortnight", "periodElement_period": 3}
        assert rule_cc1_fortnight_singular(row) is not None

    def test_period_none_fortnight_passes(self):
        row = {"periodElement_period_units": "fortnight", "periodElement_period": None}
        assert rule_cc1_fortnight_singular(row) is None

    def test_period_2_days_passes(self):
        row = {"periodElement_period_units": "day", "periodElement_period": 2}
        assert rule_cc1_fortnight_singular(row) is None

    def test_frequency_fortnight_period_1_passes(self):
        row = {"frequencyBare_period_unit": "fortnight", "frequencyBare_period": 1}
        assert rule_cc1_fortnight_singular(row) is None

    def test_frequency_fortnight_period_2_fails(self):
        row = {"frequencyBare_period_unit": "fortnight", "frequencyBare_period": 2}
        assert rule_cc1_fortnight_singular(row) is not None

    def test_empty_row_passes(self):
        assert rule_cc1_fortnight_singular({}) is None


# ---------------------------------------------------------------------------
# rule_cc2_dose_unit_mismatch
# ---------------------------------------------------------------------------


class TestDoseUnitMismatch:
    def test_1_tablet_passes(self):
        row = {"doseQuantity_quantity": 1, "doseQuantity_units": "tablet"}
        assert rule_cc2_dose_unit_mismatch(row) is None

    def test_2_tablets_passes(self):
        row = {"doseQuantity_quantity": 2, "doseQuantity_units": "tablets"}
        assert rule_cc2_dose_unit_mismatch(row) is None

    def test_1_tablets_fails(self):
        row = {"doseQuantity_quantity": 1, "doseQuantity_units": "tablets"}
        assert rule_cc2_dose_unit_mismatch(row) is not None

    def test_3_tablet_fails(self):
        row = {"doseQuantity_quantity": 3, "doseQuantity_units": "tablet"}
        assert rule_cc2_dose_unit_mismatch(row) is not None

    def test_half_tablet_passes(self):
        """0.5 is not > 1, so singular is fine."""
        row = {"doseQuantity_quantity": 0.5, "doseQuantity_units": "tablet"}
        assert rule_cc2_dose_unit_mismatch(row) is None

    def test_1_5_tablets_passes(self):
        """1.5 is > 1, so plural is correct."""
        row = {"doseQuantity_quantity": 1.5, "doseQuantity_units": "tablets"}
        assert rule_cc2_dose_unit_mismatch(row) is None

    def test_2_mg_no_opinion(self):
        """mg/ml etc. are not in the singular/plural map so no mismatch."""
        row = {"doseQuantity_quantity": 2, "doseQuantity_units": "mg"}
        assert rule_cc2_dose_unit_mismatch(row) is None

    def test_range_high_3_tablet_fails(self):
        row = {"doseRange_high": 3, "doseRange_units": "tablet"}
        assert rule_cc2_dose_unit_mismatch(row) is not None

    def test_range_high_1_tablets_fails(self):
        row = {"doseRange_high": 1, "doseRange_units": "tablets"}
        assert rule_cc2_dose_unit_mismatch(row) is not None

    def test_empty_row_passes(self):
        assert rule_cc2_dose_unit_mismatch({}) is None

    # ── spray/suck (dual-purpose words) ──
    def test_1_spray_passes(self):
        """1 + singular spray is valid."""
        row = {"doseQuantity_quantity": 1, "doseQuantity_units": "spray"}
        assert rule_cc2_dose_unit_mismatch(row) is None

    def test_5_spray_fails(self):
        """5 + singular spray → mismatch (badly written, should be 'sprays')."""
        row = {"doseQuantity_quantity": 5, "doseQuantity_units": "spray"}
        assert rule_cc2_dose_unit_mismatch(row) is not None

    def test_5_sprays_passes(self):
        """5 + plural sprays is valid."""
        row = {"doseQuantity_quantity": 5, "doseQuantity_units": "sprays"}
        assert rule_cc2_dose_unit_mismatch(row) is None

    def test_1_suck_passes(self):
        row = {"doseQuantity_quantity": 1, "doseQuantity_units": "suck"}
        assert rule_cc2_dose_unit_mismatch(row) is None

    def test_3_suck_fails(self):
        row = {"doseQuantity_quantity": 3, "doseQuantity_units": "suck"}
        assert rule_cc2_dose_unit_mismatch(row) is not None

    def test_3_sucks_passes(self):
        row = {"doseQuantity_quantity": 3, "doseQuantity_units": "sucks"}
        assert rule_cc2_dose_unit_mismatch(row) is None


# ---------------------------------------------------------------------------
# rule_cc5_freq_period_vs_timing
# ---------------------------------------------------------------------------


class TestFreqPeriodVsTiming:
    # ── dayOfWeek ──
    def test_once_a_week_on_mondays_passes(self):
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "week",
            "dayOfWeek_value": "on mondays",
        }
        assert rule_cc5_freq_period_vs_timing(row) is None

    def test_twice_a_week_on_mondays_fails(self):
        row = {
            "frequencyBare_frequency": 2,
            "frequencyBare_period_unit": "week",
            "dayOfWeek_value": "on mondays",
        }
        assert rule_cc5_freq_period_vs_timing(row) is not None

    def test_twice_a_day_on_mondays_fails(self):
        row = {
            "frequencyBare_frequency": 2,
            "frequencyBare_period_unit": "day",
            "dayOfWeek_value": "on mondays",
        }
        assert rule_cc5_freq_period_vs_timing(row) is not None

    def test_once_a_month_on_mondays_fails(self):
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "month",
            "dayOfWeek_value": "on mondays",
        }
        assert rule_cc5_freq_period_vs_timing(row) is not None

    def test_every_2_weeks_on_monday_fails(self):
        row = {
            "periodElement_frequency": 1,
            "periodElement_period": 2,
            "periodElement_period_units": "week",
            "dayOfWeek_value": "on monday",
        }
        assert rule_cc5_freq_period_vs_timing(row) is not None

    # ── when (specific) ──
    def test_once_a_day_at_night_passes(self):
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "at night",
        }
        assert rule_cc5_freq_period_vs_timing(row) is None

    def test_twice_a_day_at_night_fails(self):
        row = {
            "frequencyBare_frequency": 2,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "at night",
        }
        assert rule_cc5_freq_period_vs_timing(row) is not None

    def test_3_times_a_day_at_bedtime_fails(self):
        row = {
            "frequencyBare_frequency": 3,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "at bedtime",
        }
        assert rule_cc5_freq_period_vs_timing(row) is not None

    def test_once_a_week_at_night_fails(self):
        """freq_period=7, timing=1 → 7 != 1 → EXCLUDE."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "week",
            "whenBare_when": "at night",
        }
        assert rule_cc5_freq_period_vs_timing(row) is not None

    def test_3_times_with_breakfast_fails(self):
        row = {
            "frequencyBare_frequency": 3,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "with breakfast",
        }
        assert rule_cc5_freq_period_vs_timing(row) is not None

    def test_once_a_day_with_breakfast_passes(self):
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "with breakfast",
        }
        assert rule_cc5_freq_period_vs_timing(row) is None

    # ── when (generic — rule should not apply) ──
    def test_3_times_with_food_passes(self):
        """Generic when — no timing cycle, rule doesn't apply."""
        row = {
            "frequencyBare_frequency": 3,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "with food",
        }
        assert rule_cc5_freq_period_vs_timing(row) is None

    def test_4_times_on_empty_stomach_passes(self):
        row = {
            "frequencyBare_frequency": 4,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "on empty stomach",
        }
        assert rule_cc5_freq_period_vs_timing(row) is None

    # ── timeOfDay ──
    def test_once_a_day_at_8am_passes(self):
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "timeOfDay_value": "at 8am",
        }
        assert rule_cc5_freq_period_vs_timing(row) is None

    def test_twice_a_day_at_8am_fails(self):
        row = {
            "frequencyBare_frequency": 2,
            "frequencyBare_period_unit": "day",
            "timeOfDay_value": "at 8am",
        }
        assert rule_cc5_freq_period_vs_timing(row) is not None

    # ── frequencyMax (up to / range patterns) ──
    def test_up_to_3_times_a_day_at_night_fails(self):
        """frequencyMax only — 3 × 1 = 3, timing = 1 → EXCLUDE."""
        row = {
            "frequencyBare_frequencyMax": 3,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "at night",
        }
        assert rule_cc5_freq_period_vs_timing(row) is not None

    def test_up_to_once_a_day_at_night_passes(self):
        """frequencyMax=1 × 1 = 1, timing = 1 → FINE."""
        row = {
            "frequencyBare_frequencyMax": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "at night",
        }
        assert rule_cc5_freq_period_vs_timing(row) is None

    def test_1_to_3_times_a_day_at_night_fails(self):
        """Both frequency=1 and frequencyMax=3 — uses max: 3 × 1 = 3, timing = 1 → EXCLUDE."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_frequencyMax": 3,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "at night",
        }
        assert rule_cc5_freq_period_vs_timing(row) is not None

    def test_1_to_3_times_a_week_on_mondays_fails(self):
        """Uses frequencyMax=3: 3 × 7 = 21, timing = 7 → EXCLUDE."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_frequencyMax": 3,
            "frequencyBare_period_unit": "week",
            "dayOfWeek_value": "on mondays",
        }
        assert rule_cc5_freq_period_vs_timing(row) is not None

    def test_up_to_once_a_week_on_mondays_passes(self):
        """frequencyMax=1 × 7 = 7, timing = 7 → FINE."""
        row = {
            "frequencyBare_frequencyMax": 1,
            "frequencyBare_period_unit": "week",
            "dayOfWeek_value": "on mondays",
        }
        assert rule_cc5_freq_period_vs_timing(row) is None

    # ── new formula: period÷freq (twice a fortnight on mondays) ──
    def test_twice_a_fortnight_on_mondays_passes(self):
        """14÷2=7, timing=7 → FINE (one dose each monday over 2-week cycle)."""
        row = {
            "frequencyBare_frequency": 2,
            "frequencyBare_period_unit": "fortnight",
            "dayOfWeek_value": "on mondays",
        }
        assert rule_cc5_freq_period_vs_timing(row) is None

    def test_7_times_every_day_on_monday_fails(self):
        """1÷7≈0.14, timing=7 → EXCLUDE."""
        row = {
            "frequencyBare_frequency": 7,
            "frequencyBare_period_unit": "day",
            "dayOfWeek_value": "on monday",
        }
        assert rule_cc5_freq_period_vs_timing(row) is not None

    # ── count sub-rule: count with daily timing ──
    def test_count_1_at_night_passes(self):
        """count=1 with singular when → FINE."""
        row = {"count_count": 1, "whenBare_when": "at night"}
        assert rule_cc5_freq_period_vs_timing(row) is None

    def test_count_3_at_night_fails(self):
        """count=3 with singular when → EXCLUDE (ambiguous)."""
        row = {"count_count": 3, "whenBare_when": "at night"}
        assert rule_cc5_freq_period_vs_timing(row) is not None

    def test_count_2_at_8am_fails(self):
        """count=2 with timeOfDay → EXCLUDE (ambiguous: 2 times at 8am?)."""
        row = {"count_count": 2, "timeOfDay_value": "at 8am"}
        assert rule_cc5_freq_period_vs_timing(row) is not None

    def test_count_1_at_8am_passes(self):
        """count=1 with timeOfDay → FINE."""
        row = {"count_count": 1, "timeOfDay_value": "at 8am"}
        assert rule_cc5_freq_period_vs_timing(row) is None

    def test_count_2_on_mondays_passes(self):
        """count=2 with dayOfWeek → FINE (2 times on mondays is acceptable)."""
        row = {"count_count": 2, "dayOfWeek_value": "on mondays"}
        assert rule_cc5_freq_period_vs_timing(row) is None

    def test_count_3_at_bedtime_fails(self):
        """count=3 with singular specific when → EXCLUDE."""
        row = {"count_count": 3, "whenBare_when": "at bedtime"}
        assert rule_cc5_freq_period_vs_timing(row) is not None

    def test_count_1_at_bedtime_passes(self):
        """count=1 with singular specific when → FINE."""
        row = {"count_count": 1, "whenBare_when": "at bedtime"}
        assert rule_cc5_freq_period_vs_timing(row) is None

    def test_count_with_food_passes(self):
        """count with generic when → no daily timing, rule doesn't apply."""
        row = {"count_count": 3, "whenBare_when": "with food"}
        assert rule_cc5_freq_period_vs_timing(row) is None

    def test_count_with_plural_when_passes(self):
        """count with plural when (e.g. 'at nights') → not singular, rule skips."""
        row = {"count_count": 3, "whenBare_when": "at nights"}
        assert rule_cc5_freq_period_vs_timing(row) is None

    def test_count_ignored_when_frequency_present(self):
        """If both count and frequency are present, count sub-rule defers to main rule."""
        row = {
            "count_count": 3,
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "at night",
        }
        # Main rule: period÷freq = 1/1 = 1, timing=1 → PASS
        assert rule_cc5_freq_period_vs_timing(row) is None

    # ── no timing present — rule doesn't apply ──
    def test_no_timing_passes(self):
        row = {"frequencyBare_frequency": 4, "frequencyBare_period_unit": "day"}
        assert rule_cc5_freq_period_vs_timing(row) is None

    def test_empty_row_passes(self):
        assert rule_cc5_freq_period_vs_timing({}) is None

    # ── periodElement as frequency source ──
    def test_every_day_at_night_passes(self):
        """periodElement defaults frequency=1, period_unit=day → period÷freq=1, timing=1."""
        row = {
            "periodElement_frequency": 1,
            "periodElement_period_units": "day",
            "periodElement_period": 1,
            "whenBare_when": "at night",
        }
        assert rule_cc5_freq_period_vs_timing(row) is None


# ---------------------------------------------------------------------------
# rule_cc6_singular_timing_without_frequency
# ---------------------------------------------------------------------------


class TestSingularTimingWithoutFrequency:
    # ── dayOfWeek ──
    def test_on_monday_without_freq_fails(self):
        row = {"dayOfWeek_value": "on monday"}
        assert rule_cc6_singular_timing_without_frequency(row) is not None

    def test_on_mondays_without_freq_passes(self):
        row = {"dayOfWeek_value": "on mondays"}
        assert rule_cc6_singular_timing_without_frequency(row) is None

    def test_on_monday_with_freq_passes(self):
        """Rule 9 handles this case — Rule 10 skips."""
        row = {
            "dayOfWeek_value": "on monday",
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "week",
        }
        assert rule_cc6_singular_timing_without_frequency(row) is None

    # ── when (specific) ──
    def test_at_night_without_freq_fails(self):
        row = {"whenBare_when": "at night"}
        assert rule_cc6_singular_timing_without_frequency(row) is not None

    def test_at_nights_without_freq_passes(self):
        row = {"whenBare_when": "at nights"}
        assert rule_cc6_singular_timing_without_frequency(row) is None

    def test_at_bedtime_without_freq_fails(self):
        row = {"whenBare_when": "at bedtime"}
        assert rule_cc6_singular_timing_without_frequency(row) is not None

    def test_at_bedtimes_without_freq_passes(self):
        row = {"whenBare_when": "at bedtimes"}
        assert rule_cc6_singular_timing_without_frequency(row) is None

    def test_at_night_with_freq_passes(self):
        """Rule 9 handles this — Rule 10 skips."""
        row = {"whenBare_when": "at night", "periodElement_period_units": "day"}
        assert rule_cc6_singular_timing_without_frequency(row) is None

    # ── when (generic — not a timing point) ──
    def test_with_food_without_freq_passes(self):
        """Generic when is not a timing point — Rule 10 doesn't apply."""
        row = {"whenBare_when": "with food"}
        assert rule_cc6_singular_timing_without_frequency(row) is None

    def test_on_empty_stomach_without_freq_passes(self):
        row = {"whenBare_when": "on empty stomach"}
        assert rule_cc6_singular_timing_without_frequency(row) is None

    # ── timeOfDay ──
    def test_at_8am_without_freq_fails(self):
        row = {"timeOfDay_value": "at 8am"}
        assert rule_cc6_singular_timing_without_frequency(row) is not None

    def test_at_8am_with_freq_passes(self):
        row = {
            "timeOfDay_value": "at 8am",
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
        }
        assert rule_cc6_singular_timing_without_frequency(row) is None

    # ── count does NOT suppress rule 10 ──
    def test_count_2_on_monday_singular_fails(self):
        """count present but singular dayOfWeek → still EXCLUDE (no period)."""
        row = {"count_count": 2, "dayOfWeek_value": "on monday"}
        assert rule_cc6_singular_timing_without_frequency(row) is not None

    def test_count_1_at_night_singular_fails(self):
        """count=1 with singular when → Rule 10 still fires (Rule 9 handles count logic)."""
        row = {"count_count": 1, "whenBare_when": "at night"}
        assert rule_cc6_singular_timing_without_frequency(row) is not None

    def test_count_3_at_8am_fails(self):
        """count present with timeOfDay → still EXCLUDE (no period)."""
        row = {"count_count": 3, "timeOfDay_value": "at 8am"}
        assert rule_cc6_singular_timing_without_frequency(row) is not None

    # ── empty ──
    def test_empty_row_passes(self):
        assert rule_cc6_singular_timing_without_frequency({}) is None


# ---------------------------------------------------------------------------
# rule_cc7_freq_period_exceeds_duration
# ---------------------------------------------------------------------------


class TestFreqPeriodExceedsDuration:
    # ── fails: cycle > duration ──
    def test_once_a_week_for_5_days_fails(self):
        """7 > 5 → EXCLUDE."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "week",
            "boundsDuration_value": 5,
            "boundsDuration_unit": "day",
        }
        assert rule_cc7_freq_period_exceeds_duration(row) is not None

    def test_once_a_month_for_2_weeks_fails(self):
        """30 > 14 → EXCLUDE."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "month",
            "boundsDuration_value": 2,
            "boundsDuration_unit": "week",
        }
        assert rule_cc7_freq_period_exceeds_duration(row) is not None

    def test_every_2_weeks_for_5_days_fails(self):
        """14 > 5 → EXCLUDE."""
        row = {
            "periodElement_frequency": 1,
            "periodElement_period": 2,
            "periodElement_period_units": "week",
            "boundsDuration_value": 5,
            "boundsDuration_unit": "day",
        }
        assert rule_cc7_freq_period_exceeds_duration(row) is not None

    # ── passes: cycle <= duration ──
    def test_once_a_day_for_5_days_passes(self):
        """1 <= 5 → FINE."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "boundsDuration_value": 5,
            "boundsDuration_unit": "day",
        }
        assert rule_cc7_freq_period_exceeds_duration(row) is None

    def test_twice_a_day_for_5_days_passes(self):
        """period = 1 day ≤ 5 → FINE (frequency doesn't matter)."""
        row = {
            "frequencyBare_frequency": 2,
            "frequencyBare_period_unit": "day",
            "boundsDuration_value": 5,
            "boundsDuration_unit": "day",
        }
        assert rule_cc7_freq_period_exceeds_duration(row) is None

    def test_12_times_a_day_for_5_days_passes(self):
        """period = 1 day ≤ 5 → FINE (high frequency within a day is fine)."""
        row = {
            "frequencyBare_frequency": 12,
            "frequencyBare_period_unit": "day",
            "boundsDuration_value": 5,
            "boundsDuration_unit": "day",
        }
        assert rule_cc7_freq_period_exceeds_duration(row) is None

    def test_once_a_week_for_7_days_passes(self):
        """7 == 7, not strict > → FINE."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "week",
            "boundsDuration_value": 7,
            "boundsDuration_unit": "day",
        }
        assert rule_cc7_freq_period_exceeds_duration(row) is None

    def test_once_a_week_for_2_weeks_passes(self):
        """7 <= 14 → FINE."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "week",
            "boundsDuration_value": 2,
            "boundsDuration_unit": "week",
        }
        assert rule_cc7_freq_period_exceeds_duration(row) is None

    def test_3_times_a_day_for_5_days_passes(self):
        """period = 1 day ≤ 5 → FINE."""
        row = {
            "frequencyBare_frequency": 3,
            "frequencyBare_period_unit": "day",
            "boundsDuration_value": 5,
            "boundsDuration_unit": "day",
        }
        assert rule_cc7_freq_period_exceeds_duration(row) is None

    # ── uses valueMax when present ──
    def test_once_a_week_for_1_to_2_weeks_passes(self):
        """Uses valueMax=2 → 7 <= 14 → FINE."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "week",
            "boundsDuration_value": 1,
            "boundsDuration_valueMax": 2,
            "boundsDuration_unit": "week",
        }
        assert rule_cc7_freq_period_exceeds_duration(row) is None

    def test_once_a_month_for_1_to_3_weeks_fails(self):
        """Uses valueMax=3 → 30 > 21 → EXCLUDE."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "month",
            "boundsDuration_value": 1,
            "boundsDuration_valueMax": 3,
            "boundsDuration_unit": "week",
        }
        assert rule_cc7_freq_period_exceeds_duration(row) is not None

    # ── no duration or no frequency — rule doesn't apply ──
    def test_no_duration_passes(self):
        row = {"frequencyBare_frequency": 1, "frequencyBare_period_unit": "week"}
        assert rule_cc7_freq_period_exceeds_duration(row) is None

    def test_no_frequency_passes(self):
        row = {"boundsDuration_value": 5, "boundsDuration_unit": "day"}
        assert rule_cc7_freq_period_exceeds_duration(row) is None

    def test_empty_row_passes(self):
        assert rule_cc7_freq_period_exceeds_duration({}) is None


# ---------------------------------------------------------------------------
# rule_cc8_event_with_period_gt_1_day
# ---------------------------------------------------------------------------


class TestEventWithPeriodGt1Day:
    # ── fails: period > 1 day ──
    def test_once_a_week_on_date_fails(self):
        """period = 7 days > 1 → EXCLUDE."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "week",
            "event_value": "on 2.12.2024",
        }
        assert rule_cc8_event_with_period_gt_1_day(row) is not None

    def test_every_3_days_on_date_fails(self):
        """period = 3 days > 1 → EXCLUDE."""
        row = {
            "periodElement_frequency": 1,
            "periodElement_period": 3,
            "periodElement_period_units": "day",
            "event_value": "on 2.12.2024",
        }
        assert rule_cc8_event_with_period_gt_1_day(row) is not None

    def test_once_a_month_on_date_fails(self):
        """period = 30 days > 1 → EXCLUDE."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "month",
            "event_value": "on 2.12.2024",
        }
        assert rule_cc8_event_with_period_gt_1_day(row) is not None

    def test_every_2_weeks_on_date_fails(self):
        """period = 14 days > 1 → EXCLUDE."""
        row = {
            "periodElement_frequency": 1,
            "periodElement_period": 2,
            "periodElement_period_units": "week",
            "event_value": "on 2.12.2024",
        }
        assert rule_cc8_event_with_period_gt_1_day(row) is not None

    # ── passes: period <= 1 day ──
    def test_3_times_a_day_on_date_passes(self):
        """period = 1 day, frequency=3 is fine — multiple times within the day."""
        row = {
            "frequencyBare_frequency": 3,
            "frequencyBare_period_unit": "day",
            "event_value": "on 2.12.2024",
        }
        assert rule_cc8_event_with_period_gt_1_day(row) is None

    def test_once_a_day_on_date_passes(self):
        """period = 1 day → FINE."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "event_value": "on 2.12.2024",
        }
        assert rule_cc8_event_with_period_gt_1_day(row) is None

    def test_every_4_hours_on_date_passes(self):
        """period = 4 hours = 1/6 day → FINE."""
        row = {
            "periodElement_frequency": 1,
            "periodElement_period": 4,
            "periodElement_period_units": "hour",
            "event_value": "on 2.12.2024",
        }
        assert rule_cc8_event_with_period_gt_1_day(row) is None

    def test_twice_a_day_on_date_passes(self):
        """period = 1 day, frequency=2 within the day is fine."""
        row = {
            "frequencyBare_frequency": 2,
            "frequencyBare_period_unit": "day",
            "event_value": "on 2.12.2024",
        }
        assert rule_cc8_event_with_period_gt_1_day(row) is None

    # ── no event or no period — rule doesn't apply ──
    def test_no_event_passes(self):
        row = {"frequencyBare_frequency": 1, "frequencyBare_period_unit": "week"}
        assert rule_cc8_event_with_period_gt_1_day(row) is None

    def test_no_period_passes(self):
        row = {"event_value": "on 2.12.2024"}
        assert rule_cc8_event_with_period_gt_1_day(row) is None

    def test_empty_row_passes(self):
        assert rule_cc8_event_with_period_gt_1_day({}) is None


# ---------------------------------------------------------------------------
# rule_cc9_event_or_count_with_bounds_duration
# ---------------------------------------------------------------------------


class TestEventOrCountWithBoundsDuration:
    # ── Sub-rule 1: event + boundsDuration ──
    def test_event_with_duration_fails(self):
        """Event date + boundsDuration is contradictory."""
        row = {
            "event_value": "on 2.12.2024",
            "boundsDuration_value": 5,
            "boundsDuration_unit": "day",
        }
        assert rule_cc9_event_or_count_with_bounds_duration(row) is not None

    def test_event_without_duration_passes(self):
        """Event alone is fine."""
        row = {"event_value": "on 2.12.2024"}
        assert rule_cc9_event_or_count_with_bounds_duration(row) is None

    # ── Sub-rule 2: count + boundsDuration ──
    def test_count_1_with_duration_fails(self):
        """'take once for 5 days' — count + duration → EXCLUDE."""
        row = {
            "count_count": 1,
            "boundsDuration_value": 5,
            "boundsDuration_unit": "day",
        }
        assert rule_cc9_event_or_count_with_bounds_duration(row) is not None

    def test_count_3_with_duration_fails(self):
        """'take 3 times for 5 days' — count + duration → EXCLUDE."""
        row = {
            "count_count": 3,
            "boundsDuration_value": 5,
            "boundsDuration_unit": "day",
        }
        assert rule_cc9_event_or_count_with_bounds_duration(row) is not None

    def test_count_without_duration_passes(self):
        """Count alone is fine."""
        row = {"count_count": 3}
        assert rule_cc9_event_or_count_with_bounds_duration(row) is None

    # ── duration without event or count is fine (other rules handle) ──
    def test_duration_with_frequency_passes(self):
        """Frequency + duration is fine — Rule 11 handles."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "boundsDuration_value": 5,
            "boundsDuration_unit": "day",
        }
        assert rule_cc9_event_or_count_with_bounds_duration(row) is None

    def test_duration_alone_passes(self):
        """Duration without event or count — other rules may apply but not 14."""
        row = {"boundsDuration_value": 5, "boundsDuration_unit": "day"}
        assert rule_cc9_event_or_count_with_bounds_duration(row) is None

    def test_empty_row_passes(self):
        assert rule_cc9_event_or_count_with_bounds_duration({}) is None


# ---------------------------------------------------------------------------
# rule_vc1_exceeds_365_days
# ---------------------------------------------------------------------------


class TestExceeds365Days:
    def test_period_400_days_fails(self):
        row = {"periodElement_period": 400, "periodElement_period_units": "day"}
        assert rule_vc1_exceeds_365_days(row) is not None

    def test_period_365_days_passes(self):
        row = {"periodElement_period": 365, "periodElement_period_units": "day"}
        assert rule_vc1_exceeds_365_days(row) is None

    def test_period_400_weeks_passes(self):
        """Only fails when unit is day/days."""
        row = {"periodElement_period": 400, "periodElement_period_units": "week"}
        assert rule_vc1_exceeds_365_days(row) is None

    def test_duration_500_days_fails(self):
        row = {"durationValue_value": 500, "durationValue_period_units": "day"}
        assert rule_vc1_exceeds_365_days(row) is not None

    def test_duration_500_days_plural_fails(self):
        row = {"durationValue_value": 500, "durationValue_period_units": "days"}
        assert rule_vc1_exceeds_365_days(row) is not None

    def test_duration_30_days_passes(self):
        row = {"durationValue_value": 30, "durationValue_period_units": "day"}
        assert rule_vc1_exceeds_365_days(row) is None

    def test_bounds_duration_400_days_fails(self):
        row = {"boundsDuration_value": 400, "boundsDuration_unit": "day"}
        assert rule_vc1_exceeds_365_days(row) is not None

    def test_empty_row_passes(self):
        assert rule_vc1_exceeds_365_days({}) is None


# ---------------------------------------------------------------------------
# rule_vc2_dose_implausibly_high
# ---------------------------------------------------------------------------


class TestDoseImplausiblyHigh:
    def test_2_tablets_passes(self):
        row = {"doseQuantity_quantity": 2, "doseQuantity_units": "tablets"}
        assert rule_vc2_dose_implausibly_high(row) is None

    def test_10_tablets_passes(self):
        row = {"doseQuantity_quantity": 10, "doseQuantity_units": "tablets"}
        assert rule_vc2_dose_implausibly_high(row) is None

    def test_11_tablets_fails(self):
        row = {"doseQuantity_quantity": 11, "doseQuantity_units": "tablets"}
        assert rule_vc2_dose_implausibly_high(row) is not None

    def test_20_puffs_fails(self):
        row = {"doseQuantity_quantity": 20, "doseQuantity_units": "puffs"}
        assert rule_vc2_dose_implausibly_high(row) is not None

    def test_50_mg_passes(self):
        """mg is not a unit-dose form, no limit applied."""
        row = {"doseQuantity_quantity": 50, "doseQuantity_units": "mg"}
        assert rule_vc2_dose_implausibly_high(row) is None

    def test_range_high_15_capsules_fails(self):
        row = {"doseRange_high": 15, "doseRange_units": "capsules"}
        assert rule_vc2_dose_implausibly_high(row) is not None

    def test_empty_row_passes(self):
        assert rule_vc2_dose_implausibly_high({}) is None


# ---------------------------------------------------------------------------
# rule_vc3_frequency_exceeds_max
# ---------------------------------------------------------------------------


class TestFrequencyExceedsMax:
    def test_4_times_per_day_passes(self):
        row = {"frequencyBare_frequency": 4, "frequencyBare_period_unit": "day"}
        assert rule_vc3_frequency_exceeds_max(row) is None

    def test_12_times_per_day_passes(self):
        row = {"frequencyBare_frequency": 12, "frequencyBare_period_unit": "day"}
        assert rule_vc3_frequency_exceeds_max(row) is None

    def test_13_times_per_day_fails(self):
        row = {"frequencyBare_frequency": 13, "frequencyBare_period_unit": "day"}
        assert rule_vc3_frequency_exceeds_max(row) is not None

    def test_15_times_per_week_passes(self):
        """Only applies when period_unit is day."""
        row = {"frequencyBare_frequency": 15, "frequencyBare_period_unit": "week"}
        assert rule_vc3_frequency_exceeds_max(row) is None

    def test_frequency_with_method_14_per_day_fails(self):
        row = {
            "frequencyWithMethod_frequency": 14,
            "frequencyWithMethod_period_unit": "day",
        }
        assert rule_vc3_frequency_exceeds_max(row) is not None

    def test_empty_row_passes(self):
        assert rule_vc3_frequency_exceeds_max({}) is None


# ---------------------------------------------------------------------------
# rule_cc3_milligram_range_consistency
# ---------------------------------------------------------------------------


class TestMilligramRangeConsistency:
    def test_same_unit_passes(self):
        """Same unit on both sides — raw numeric check applies."""
        row = {
            "milligramMax_value": 100,
            "milligramMax_valueMax": 200,
            "milligramMax_low_unit": "mg",
            "milligramMax_milligram_units": "mg",
        }
        assert rule_cc3_milligram_range_consistency(row) is None

    def test_same_unit_inverted_fails(self):
        """Same unit but low > high — fails."""
        row = {
            "milligramMax_value": 200,
            "milligramMax_valueMax": 100,
            "milligramMax_low_unit": "mg",
            "milligramMax_milligram_units": "mg",
        }
        assert rule_cc3_milligram_range_consistency(row) is not None

    def test_no_low_unit_inverted_fails(self):
        """Pattern1 (no low_unit), but low > high — fails."""
        row = {
            "milligramMax_value": 10,
            "milligramMax_valueMax": 5,
            "milligramMax_low_unit": None,
            "milligramMax_milligram_units": "ml",
        }
        assert rule_cc3_milligram_range_consistency(row) is not None

    def test_500mg_to_1g_passes(self):
        """500mg < 1g — valid cross-unit range."""
        row = {
            "milligramMax_value": 500,
            "milligramMax_valueMax": 1,
            "milligramMax_low_unit": "mg",
            "milligramMax_milligram_units": "g",
        }
        assert rule_cc3_milligram_range_consistency(row) is None

    def test_2g_to_500mg_fails(self):
        """2g > 500mg — inverted cross-unit range."""
        row = {
            "milligramMax_value": 2,
            "milligramMax_valueMax": 500,
            "milligramMax_low_unit": "g",
            "milligramMax_milligram_units": "mg",
        }
        assert rule_cc3_milligram_range_consistency(row) is not None

    def test_100mcg_to_1mg_passes(self):
        """100mcg < 1mg — valid."""
        row = {
            "milligramMax_value": 100,
            "milligramMax_valueMax": 1,
            "milligramMax_low_unit": "mcg",
            "milligramMax_milligram_units": "mg",
        }
        assert rule_cc3_milligram_range_consistency(row) is None

    def test_5mg_to_2mcg_fails(self):
        """5mg > 2mcg — inverted."""
        row = {
            "milligramMax_value": 5,
            "milligramMax_valueMax": 2,
            "milligramMax_low_unit": "mg",
            "milligramMax_milligram_units": "mcg",
        }
        assert rule_cc3_milligram_range_consistency(row) is not None

    def test_ml_to_mg_incompatible_fails(self):
        """ml and mg are different categories — incompatible."""
        row = {
            "milligramMax_value": 5,
            "milligramMax_valueMax": 10,
            "milligramMax_low_unit": "ml",
            "milligramMax_milligram_units": "mg",
        }
        assert rule_cc3_milligram_range_consistency(row) is not None

    def test_2ml_to_5ml_same_unit_passes(self):
        """Same unit, no cross-unit check."""
        row = {
            "milligramMax_value": 2,
            "milligramMax_valueMax": 5,
            "milligramMax_low_unit": "ml",
            "milligramMax_milligram_units": "ml",
        }
        assert rule_cc3_milligram_range_consistency(row) is None

    def test_no_low_unit_passes(self):
        """Pattern1 (no low_unit) — rule doesn't apply."""
        row = {
            "milligramMax_value": 4,
            "milligramMax_valueMax": 5,
            "milligramMax_low_unit": None,
            "milligramMax_milligram_units": "ml",
        }
        assert rule_cc3_milligram_range_consistency(row) is None

    def test_empty_row_passes(self):
        assert rule_cc3_milligram_range_consistency({}) is None

    def test_5ml_to_1_litre_passes(self):
        """5ml < 1 litre — valid cross-volume range."""
        row = {
            "milligramMax_value": 5,
            "milligramMax_valueMax": 1,
            "milligramMax_low_unit": "ml",
            "milligramMax_milligram_units": "litre",
        }
        assert rule_cc3_milligram_range_consistency(row) is None

    def test_2_litres_to_500ml_fails(self):
        """2 litres > 500ml — inverted."""
        row = {
            "milligramMax_value": 2,
            "milligramMax_valueMax": 500,
            "milligramMax_low_unit": "litre",
            "milligramMax_milligram_units": "ml",
        }
        assert rule_cc3_milligram_range_consistency(row) is not None


# ---------------------------------------------------------------------------
# rule_cc4_max_dose_less_than_regular
# ---------------------------------------------------------------------------


class TestMaxDoseLessThanRegular:
    def test_max_8_dose_2_passes(self):
        row = {"maxDosePerPeriod_num_value": 8, "doseQuantity_quantity": 2}
        assert rule_cc4_max_dose_less_than_regular(row) is None

    def test_max_2_dose_4_fails(self):
        row = {"maxDosePerPeriod_num_value": 2, "doseQuantity_quantity": 4}
        assert rule_cc4_max_dose_less_than_regular(row) is not None

    def test_max_4_range_high_5_fails(self):
        row = {"maxDosePerPeriod_num_value": 4, "doseRange_high": 5}
        assert rule_cc4_max_dose_less_than_regular(row) is not None

    def test_max_8_range_high_2_passes(self):
        row = {"maxDosePerPeriod_num_value": 8, "doseRange_high": 2}
        assert rule_cc4_max_dose_less_than_regular(row) is None

    def test_no_max_dose_passes(self):
        row = {"doseQuantity_quantity": 4}
        assert rule_cc4_max_dose_less_than_regular(row) is None

    def test_empty_row_passes(self):
        assert rule_cc4_max_dose_less_than_regular({}) is None


# ---------------------------------------------------------------------------
# evaluate_cross_column_rules (integration)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# rule_cc10_freq_leq_1_with_multi_per_day_when
# ---------------------------------------------------------------------------


class TestFreqLeq1WithMultiPerDayWhen:
    """Rule 15: frequency ≤1/day with multi-per-day when → EXCLUDE."""

    def test_once_a_day_with_meals_fails(self):
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "with meals",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is not None

    def test_once_a_day_after_eating_passes(self):
        """'eating' is generic (like 'food'), not multi-per-day — rule doesn't apply."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "after eating",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is None

    def test_once_a_day_with_each_meal_fails(self):
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "with each meal",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is not None

    def test_once_a_day_with_every_main_meal_fails(self):
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "with every main meal",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is not None

    def test_once_a_day_after_bowel_movements_fails(self):
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "after bowel movements",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is not None

    def test_once_a_day_after_each_bowel_movement_fails(self):
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "after each bowel movement",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is not None

    def test_once_a_day_with_foods_fails(self):
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "with foods",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is not None

    def test_once_a_week_with_meals_fails(self):
        """Even less frequent — once a week with meals is also contradictory."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "week",
            "whenBare_when": "with meals",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is not None

    def test_3_times_a_day_with_meals_passes(self):
        row = {
            "frequencyBare_frequency": 3,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "with meals",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is None

    def test_2_times_a_day_with_meals_passes(self):
        row = {
            "frequencyBare_frequency": 2,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "with meals",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is None

    def test_once_a_day_with_food_passes(self):
        """Singular 'food' is not multi-per-day."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "with food",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is None

    def test_once_a_day_after_breakfast_passes(self):
        """Specific meal — only once per day."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "after breakfast",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is None

    def test_once_a_day_at_night_passes(self):
        """Night is once per day."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "at night",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is None

    def test_once_a_day_on_empty_stomach_passes(self):
        """Empty stomach is not multi-per-day."""
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
            "whenBare_when": "on an empty stomach",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is None

    def test_no_when_passes(self):
        row = {
            "frequencyBare_frequency": 1,
            "frequencyBare_period_unit": "day",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is None

    def test_no_frequency_passes(self):
        """No frequency present — other rules handle this."""
        row = {"whenBare_when": "with meals"}
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is None

    def test_empty_row_passes(self):
        assert rule_cc10_freq_leq_1_with_multi_per_day_when({}) is None

    def test_with_method_prefix(self):
        """Works with frequencyWithMethod columns too."""
        row = {
            "frequencyWithMethod_frequency": 1,
            "frequencyWithMethod_period_unit": "day",
            "whenWithMethod_when": "with meals",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is not None

    def test_period_element_once_a_day_with_meals_fails(self):
        """Works with periodElement frequency too."""
        row = {
            "periodElement_frequency": 1,
            "periodElement_period_units": "day",
            "whenBare_when": "after each meal",
        }
        assert rule_cc10_freq_leq_1_with_multi_per_day_when(row) is not None


# ---------------------------------------------------------------------------
# evaluate_cross_column_rules (integration)
# ---------------------------------------------------------------------------


class TestEvaluateCrossColumnRules:
    def test_clean_row_passes(self):
        row = {
            "doseQuantity_quantity": 2,
            "doseQuantity_units": "tablets",
            "frequencyBare_frequency": 3,
            "frequencyBare_period_unit": "day",
            "periodElement_period": 1,
            "periodElement_period_units": "day",
        }
        assert evaluate_cross_column_rules(row) is None

    def test_multiple_failures_returns_all_numbers(self):
        """evaluate_cross_column_rules collects all failing rule numbers."""
        row = {
            "periodElement_period_units": "fortnight",
            "periodElement_period": 2,
            "doseQuantity_quantity": 1,
            "doseQuantity_units": "tablets",  # also a mismatch (rule 2)
        }
        result = evaluate_cross_column_rules(row)
        assert result is not None
        assert "cross_column_fail:" in result
        # CC1 (fortnight) and CC2 (singular/plural) should both fire
        assert "CC1" in result
        assert "CC2" in result

    def test_empty_row_passes(self):
        assert evaluate_cross_column_rules({}) is None


# ---------------------------------------------------------------------------
# CC12: periodElement (implied frequency=1) with dose != 1
# ---------------------------------------------------------------------------


class TestCC12PeriodWithoutSingleDose:
    """CC12: periodElement assumes frequency=1, only valid when dose == 1."""

    def test_pass_dose_quantity_equals_1(self):
        """1 tablet every day → FINE."""
        row = {
            "periodElement_period_units": "day",
            "periodElement_period": 1,
            "periodElement_frequency": 1,
            "doseQuantity_quantity": 1,
            "doseQuantity_units": "tablet",
        }
        assert rule_cc12_period_without_single_dose(row) is None

    def test_pass_value_only_equals_1(self):
        """'1 every day' (dose_QuantityValueOnly=1) → FINE."""
        row = {
            "periodElement_period_units": "day",
            "periodElement_period": 1,
            "periodElement_frequency": 1,
            "dose_QuantityValueOnly_value": 1,
        }
        assert rule_cc12_period_without_single_dose(row) is None

    def test_fail_dose_quantity_gt_1(self):
        """2 tablets every day → EXCLUDE."""
        row = {
            "periodElement_period_units": "day",
            "periodElement_period": 1,
            "periodElement_frequency": 1,
            "doseQuantity_quantity": 2,
            "doseQuantity_units": "tablets",
        }
        assert rule_cc12_period_without_single_dose(row) is not None

    def test_fail_value_only_gt_1(self):
        """'3 every 4 hours' (dose_QuantityValueOnly=3) → EXCLUDE."""
        row = {
            "periodElement_period_units": "hours",
            "periodElement_period": 4,
            "periodElement_frequency": 1,
            "dose_QuantityValueOnly_value": 3,
        }
        assert rule_cc12_period_without_single_dose(row) is not None

    def test_fail_dose_range(self):
        """1-2 tablets every day → EXCLUDE (range)."""
        row = {
            "periodElement_period_units": "day",
            "periodElement_period": 1,
            "periodElement_frequency": 1,
            "doseRange_low": 1,
            "doseRange_high": 2,
        }
        assert rule_cc12_period_without_single_dose(row) is not None

    def test_fail_value_and_max(self):
        """dose_QuantityValueAndMaxOnly with period → EXCLUDE."""
        row = {
            "periodElement_period_units": "day",
            "periodElement_period": 1,
            "periodElement_frequency": 1,
            "dose_QuantityValueAndMaxOnly_value": 2,
        }
        assert rule_cc12_period_without_single_dose(row) is not None

    def test_fail_no_dose(self):
        """'every day' with no dose at all → EXCLUDE."""
        row = {
            "periodElement_period_units": "day",
            "periodElement_period": 1,
            "periodElement_frequency": 1,
        }
        assert rule_cc12_period_without_single_dose(row) is not None

    def test_skip_when_frequency_bare_present(self):
        """2 tablets 3 times a day every day — frequencyBare present, rule doesn't apply."""
        row = {
            "periodElement_period_units": "day",
            "periodElement_period": 1,
            "periodElement_frequency": 1,
            "frequencyBare_frequency": 3,
            "frequencyBare_period_unit": "day",
            "doseQuantity_quantity": 2,
            "doseQuantity_units": "tablets",
        }
        assert rule_cc12_period_without_single_dose(row) is None

    def test_skip_when_no_period_element(self):
        """No periodElement at all — rule doesn't apply."""
        row = {
            "frequencyBare_frequency": 2,
            "frequencyBare_period_unit": "day",
            "doseQuantity_quantity": 2,
            "doseQuantity_units": "tablets",
        }
        assert rule_cc12_period_without_single_dose(row) is None

    def test_pass_every_4_weeks_dose_1(self):
        """1 injection every 4 weeks → FINE."""
        row = {
            "periodElement_period_units": "weeks",
            "periodElement_period": 4,
            "periodElement_frequency": 1,
            "doseQuantity_quantity": 1,
            "doseQuantity_units": "injection",
        }
        assert rule_cc12_period_without_single_dose(row) is None


# ---------------------------------------------------------------------------
# CC13: "each/every <time-of-day>" when contradicts non-day period
# ---------------------------------------------------------------------------


class TestCC13EachEveryWhenWithNonDayPeriod:
    """CC13: each/every morning/night/etc with non-day period → EXCLUDE."""

    def test_fail_each_morning_with_weekly_period(self):
        """'take 1 every week each morning' → period=week contradicts daily when."""
        row = {
            "whenBare_captured": "each morning",
            "periodElement_period_units": "week",
            "periodElement_period": "1",
        }
        assert rule_cc13_each_every_when_with_non_day_period(row) is not None

    def test_fail_every_night_with_monthly_period(self):
        """'take 1 every month every night' → period=month contradicts daily when."""
        row = {
            "whenBare_captured": "every night",
            "periodElement_period_units": "month",
            "periodElement_period": "1",
        }
        assert rule_cc13_each_every_when_with_non_day_period(row) is not None

    def test_pass_each_morning_with_day_period(self):
        """'take 1 a day each morning' → period=day, consistent."""
        row = {
            "whenBare_captured": "each morning",
            "periodElement_period_units": "day",
            "periodElement_period": "1",
        }
        assert rule_cc13_each_every_when_with_non_day_period(row) is None

    def test_pass_each_morning_no_period(self):
        """'take 1 each morning' → no period (will be inferred as day)."""
        row = {
            "whenBare_captured": "each morning",
        }
        assert rule_cc13_each_every_when_with_non_day_period(row) is None

    def test_pass_at_night_not_each_every(self):
        """'take 1 a day at night' → no each/every prefix → rule N/A."""
        row = {
            "whenBare_captured": "at night",
            "periodElement_period_units": "week",
            "periodElement_period": "1",
        }
        assert rule_cc13_each_every_when_with_non_day_period(row) is None

    def test_pass_when_with_method_each_evening_day(self):
        """whenWithMethod_captured 'each evening' with period=day → FINE."""
        row = {
            "whenWithMethod_captured": "each evening",
            "periodElement_period_units": "day",
        }
        assert rule_cc13_each_every_when_with_non_day_period(row) is None

    def test_fail_when_with_method_every_bedtime_weekly(self):
        """whenWithMethod_captured 'every bedtime' with period=week → EXCLUDE."""
        row = {
            "whenWithMethod_captured": "every bedtime",
            "periodElement_period_units": "week",
        }
        assert rule_cc13_each_every_when_with_non_day_period(row) is not None
