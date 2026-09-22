"""
Structural tests for refine_lookup_output_func (functions.py).

Ensures that:
1. Every lookup_v2 source column referenced in fhir_logic._has() / _first()
   is either passed through directly in output_cols OR correctly renamed/
   coalesced into a refined output column.
2. No source column appears in two different coalesce targets (silent drop).
3. No source column is both renamed and coalesced (ambiguous mapping).

These tests are pure-Python (no Spark) and run against the static mapping
defined in REFINED_COLUMN_SOURCES below — which must be kept in sync with
the withColumnRenamed / _coalesce_to calls in functions.py.

If you add a rename or coalesce in functions.py you MUST add an entry here.
If you add a _has() / _first() reference OR a new column to the extras loop
in fhir_logic.py you MUST ensure the column is in FHIR_LOGIC_COLUMNS and that
it resolves via this mapping.
"""

import pytest

# ---------------------------------------------------------------------------
# Canonical mapping: refined output column -> lookup_v2 source column(s)
# Keep in sync with withColumnRenamed / _coalesce_to calls in functions.py.
# ---------------------------------------------------------------------------
REFINED_COLUMN_SOURCES = {
    # withColumnRenamed
    "doseXMilli_value": ["doseXMilliValueOnly_value"],
    "doseXMilli_valMilli": ["doseXMilliValueOnly_val_milli"],
    "doseXMilli_milli": ["doseXMilliValueOnly_milli"],
    "milligram_valueMax": ["milligramMax_valueMax"],
    "rateRatio_periodUnit": ["rateRatio_period_unit"],
    "rateRange_unit": ["rateRange_special_unit"],
    "rateQuantity_unit": ["rateQuantity_special_unit"],
    "period_value": ["periodElement_period"],
    "period_valueMax": ["periodElement_periodMax"],
    "period_units": ["periodElement_period_units"],
    "duration_value": ["durationValue_value"],
    "duration_valueMax": ["durationMax_value"],
    # _coalesce_to
    "milligram_value": ["milligramValue_value", "milligramMax_value"],
    "milligram_units": [
        "milligramValue_milligram_units",
        "milligramMax_milligram_units",
    ],
    "method_verb": ["methodDirect_verb", "methodPassive_verb"],
    "frequency_value": [
        "frequencyBare_frequency",
        "frequencyWithMethod_frequency",
        "periodElement_frequency",
    ],
    "frequency_valueMax": [
        "frequencyBare_frequencyMax",
        "frequencyWithMethod_frequencyMax",
    ],
    "frequency_periodUnit": [
        "frequencyBare_period_unit",
        "frequencyWithMethod_period_unit",
    ],
    "duration_units": ["durationValue_period_units", "durationMax_period_units"],
    "when_value": ["whenBare_when", "whenWithMethod_when"],
    "when_offset": ["whenBare_offset", "whenWithMethod_offset"],
    "when_periodUnit": ["whenBare_period_unit", "whenWithMethod_period_unit"],
    "boundsPeriod_start": ["boundsPeriod_start", "boundsAPeriodStartEnd_start"],
    "boundsPeriod_end": ["boundsPeriod_end", "boundsAPeriodStartEnd_end"],
}

# ---------------------------------------------------------------------------
# All columns that fhir_logic.py reads via _has() or _first().
# Every entry here must either:
#   a) appear in output_cols in functions.py (passed through directly), OR
#   b) be a source column that maps to a refined output column via
#      REFINED_COLUMN_SOURCES, OR
#   c) be a _clean gate column that is now included in output_cols.
# ---------------------------------------------------------------------------
FHIR_LOGIC_COLUMNS = {
    # _clean gate columns (presence checks only — data comes from a different col)
    "asNeededBoolean_clean",
    "asNeededCodeableConcept_clean",
    "boundsAPeriodStartEnd_clean",
    "boundsDuration_clean",
    "boundsPeriod_clean",
    "count_clean",
    "dayOfWeek_clean",
    "doseQuantity_clean",
    "doseRange_clean",
    "doseXMilliValueOnly_clean",
    "dose_QuantityValueAndMaxOnly_clean",
    "dose_QuantityValueOnly_clean",
    "durationMax_clean",
    "durationValue_clean",
    "event_clean",
    "forElement_clean",
    "frequencyBare_clean",
    "frequencyWithMethod_clean",
    "maxDosePerAdministration_clean",
    "maxDosePerLifetime_clean",
    "maxDosePerPeriod_clean",
    "methodDirect_clean",
    "methodPassive_clean",
    "milligramMax_clean",
    "milligramValue_clean",
    "periodElement_clean",
    "rateQuantity_clean",
    "rateRange_clean",
    "rateRatio_clean",
    "route_clean",
    "site_clean",
    "timeOfDay_clean",
    "whenBare_clean",
    "whenWithMethod_clean",
    # extras loop columns (iterated in fhir_logic._build_additional_instructions)
    "extrasAsDirected_clean",
    "extras_clean",
    "extrasPAUSE_clean",
    "extrasALTER_clean",
    "extras_b_clean",
    "extras_whenoffset",
    # data columns read directly from refined output
    "asNeededCodeableConcept_value",
    "boundsDuration_high",
    "boundsDuration_high_unit",
    "boundsDuration_low",
    "boundsDuration_low_unit",
    "boundsDuration_unit",
    "boundsDuration_value",
    "boundsPeriod_end",
    "boundsPeriod_start",
    "boundsAPeriodStartEnd_end",
    "boundsAPeriodStartEnd_start",
    "count_count",
    "count_countMax",
    "dayOfWeek_value",
    "doseQuantity_spoonsize",
    "doseQuantity_unit",
    "doseQuantity_value",
    "doseRange_high",
    "doseRange_highunit",
    "doseRange_low",
    "doseRange_lowunit",
    "doseRange_spoonsize",
    "doseXMilli_milli",
    "doseXMilli_valMilli",
    "doseXMilli_value",
    "duration_units",
    "duration_value",
    "duration_valueMax",
    "event_value",
    "frequency_periodUnit",
    "frequency_value",
    "frequency_valueMax",
    "maxDosePerAdministration_unit",
    "maxDosePerAdministration_value",
    "maxDosePerLifetime_unit",
    "maxDosePerLifetime_value",
    "maxDosePerPeriod_denom_unit",
    "maxDosePerPeriod_denom_value",
    "maxDosePerPeriod_num_unit",
    "maxDosePerPeriod_num_value",
    "methodDirect_verb",
    "methodPassive_verb",
    "milligramMax_milligram_units",
    "milligramMax_value",
    "milligramMax_valueMax",
    "milligramValue_milligram_units",
    "milligramValue_value",
    "period_units",
    "period_value",
    "period_valueMax",
    "periodElement_frequency",
    "periodElement_period",
    "periodElement_periodMax",
    "periodElement_period_units",
    "rateQuantity_unit",
    "rateQuantity_value",
    "rateRange_high",
    "rateRange_low",
    "rateRange_unit",
    "rateRatio_denominator",
    "rateRatio_numerator",
    "rateRatio_periodUnit",
    "route_clean",
    "site_clean",
    "timeOfDay_value",
    "when_offset",
    "when_periodUnit",
    "when_value",
    "whenBare_offset",
    "whenBare_period_unit",
    "whenBare_when",
    "whenWithMethod_offset",
    "whenWithMethod_period_unit",
    "whenWithMethod_when",
    # output_cols pass-throughs (included for completeness)
    "dosage",
}

# output_cols from functions.py — columns that reach refined_lookup directly
OUTPUT_COLS = {
    "dosage",
    "dosage_lower",
    "dosage_count",
    "dosage_elements",
    "exclude",
    "mapped",
    "buckets",
    "fhir_json",
    "dosage_spare",
    "doseQuantity_value",
    "doseQuantity_unit",
    "doseQuantity_spoonsize",
    "doseRange_low",
    "doseRange_high",
    "doseRange_lowunit",
    "doseRange_highunit",
    "doseRange_spoonsize",
    "dose_unit_all",
    "dose_unit_code",
    "dose_unit_display",
    "dose_unit_system",
    "doseXMilli_value",
    "doseXMilli_valMilli",
    "doseXMilli_milli",
    "milligram_value",
    "milligram_valueMax",
    "milligram_units",
    "method_verb",
    "method_snomed_code",
    "method_snomed_display",
    "rateRatio_numerator",
    "rateRatio_denominator",
    "rateRatio_periodUnit",
    "rateRatio_periodUnit_ucum",
    "rateRange_low",
    "rateRange_high",
    "rateRange_unit",
    "rateRange_unit_code",
    "rateRange_unit_display",
    "rateRange_unit_system",
    "rateQuantity_value",
    "rateQuantity_unit",
    "rateQuantity_unit_code",
    "rateQuantity_unit_display",
    "rateQuantity_unit_system",
    "frequency_value",
    "frequency_valueMax",
    "frequency_periodUnit",
    "frequency_periodUnit_ucum",
    "count_count",
    "count_countMax",
    "period_value",
    "period_valueMax",
    "period_units",
    "period_units_ucum",
    "duration_value",
    "duration_valueMax",
    "duration_units",
    "duration_units_ucum",
    "when_value",
    "when_fhir",
    "when_offset",
    "when_periodUnit",
    "when_periodUnit_ucum",
    "dayOfWeek_value",
    "dayOfWeek_fhir",
    "timeOfDay_value",
    "event_value",
    "boundsDuration_value",
    "boundsDuration_unit",
    "boundsDuration_unit_ucum",
    "boundsDuration_low",
    "boundsDuration_high",
    "boundsDuration_low_unit",
    "boundsDuration_high_unit",
    "boundsPeriod_start",
    "boundsPeriod_end",
    "maxDosePerPeriod_num_value",
    "maxDosePerPeriod_num_unit",
    "maxDosePerPeriod_num_unit_code",
    "maxDosePerPeriod_num_unit_display",
    "maxDosePerPeriod_num_unit_system",
    "maxDosePerPeriod_denom_value",
    "maxDosePerPeriod_denom_unit",
    "maxDosePerPeriod_denom_unit_ucum",
    "maxDosePerAdministration_value",
    "maxDosePerAdministration_unit",
    "maxDosePerAdministration_unit_code",
    "maxDosePerAdministration_unit_display",
    "maxDosePerAdministration_unit_system",
    "maxDosePerLifetime_value",
    "maxDosePerLifetime_unit",
    "maxDosePerLifetime_unit_code",
    "maxDosePerLifetime_unit_display",
    "maxDosePerLifetime_unit_system",
    "route_clean",
    "route_snomed_code",
    "route_snomed_display",
    "site_clean",
    "asNeededBoolean_clean",
    "asNeededCodeableConcept_value",
    "extrasAsDirected_clean",
    "extras_clean",
    "extrasPAUSE_clean",
    "extrasALTER_clean",
    "extras_b_clean",
    "extras_whenoffset",
    "forElement_clean",
    # _clean gate columns
    "asNeededCodeableConcept_clean",
    "boundsAPeriodStartEnd_clean",
    "boundsDuration_clean",
    "boundsPeriod_clean",
    "count_clean",
    "dayOfWeek_clean",
    "doseQuantity_clean",
    "doseRange_clean",
    "doseXMilliValueOnly_clean",
    "dose_QuantityValueAndMaxOnly_clean",
    "dose_QuantityValueOnly_clean",
    "durationMax_clean",
    "durationValue_clean",
    "event_clean",
    "frequencyBare_clean",
    "frequencyWithMethod_clean",
    "maxDosePerAdministration_clean",
    "maxDosePerLifetime_clean",
    "maxDosePerPeriod_clean",
    "methodDirect_clean",
    "methodPassive_clean",
    "milligramMax_clean",
    "milligramValue_clean",
    "periodElement_clean",
    "rateQuantity_clean",
    "rateRange_clean",
    "rateRatio_clean",
    "timeOfDay_clean",
    "whenBare_clean",
    "whenWithMethod_clean",
}

# Build reverse map: lookup_v2 source col -> refined output col(s) it feeds
_source_to_refined: dict[str, list[str]] = {}
for refined_col, sources in REFINED_COLUMN_SOURCES.items():
    for src in sources:
        _source_to_refined.setdefault(src, []).append(refined_col)


def _resolves(col: str) -> bool:
    """True if col is available in refined_lookup (directly or via mapping)."""
    if col in OUTPUT_COLS:
        return True
    # It's a source col that gets renamed/coalesced into something in OUTPUT_COLS
    if col in _source_to_refined:
        return any(refined in OUTPUT_COLS for refined in _source_to_refined[col])
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_source_column_in_two_coalesce_targets():
    """A source column must not feed two different coalesce targets — that would be a silent drop."""
    multi_target = {
        src: targets
        for src, targets in _source_to_refined.items()
        if len(set(targets)) > 1
        # boundsPeriod_start/end self-coalesce with boundsAPeriodStartEnd — that's intentional
        and src not in ("boundsPeriod_start", "boundsPeriod_end")
    }
    assert not multi_target, (
        "Source column(s) feed multiple coalesce targets — data may be silently dropped: "
        + str(multi_target)
    )


def test_no_source_column_both_renamed_and_coalesced():
    """A column must not appear in both a withColumnRenamed AND a _coalesce_to — ambiguous."""
    rename_sources = {
        srcs[0] for srcs in REFINED_COLUMN_SOURCES.values() if len(srcs) == 1
    }
    coalesce_sources = {
        src for srcs in REFINED_COLUMN_SOURCES.values() if len(srcs) > 1 for src in srcs
    }
    overlap = rename_sources & coalesce_sources
    assert not overlap, f"Column(s) appear in both rename and coalesce: {overlap}"


@pytest.mark.parametrize("col", sorted(FHIR_LOGIC_COLUMNS))
def test_fhir_logic_column_resolves_in_refined(col):
    """Every column read by fhir_logic must be available in refined_lookup output."""
    assert _resolves(col), (
        f"Column '{col}' is read by fhir_logic but is neither in output_cols "
        f"nor mapped from a lookup_v2 source via REFINED_COLUMN_SOURCES. "
        f"Add it to output_cols in functions.py and to OUTPUT_COLS in this test."
    )
