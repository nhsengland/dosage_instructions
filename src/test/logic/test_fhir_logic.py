"""Tests for fhir_logic module — verifies FHIR JSON generation from pipeline rows."""

import json
import sys
import os

# sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dosage_instructions.data_enrichment.fhir_logic import (
    row_to_fhir_dosage,
    _unit_coding,
    _map_when_to_fhir,
)

# ---------------------------------------------------------------------------
# Unit coding tests
# ---------------------------------------------------------------------------


def test_unit_coding_snomed_tablet():
    """Pharmaceutical forms use SNOMED."""
    result = _unit_coding("tablet")
    assert result["system"] == "http://snomed.info/sct"
    assert result["code"] == "428673006"
    assert result["display"] == "Tablet"


def test_unit_coding_snomed_capsule():
    result = _unit_coding("capsules")
    assert result["system"] == "http://snomed.info/sct"
    assert result["code"] == "428641000"
    assert result["display"] == "Capsule"


def test_unit_coding_ucum_mg():
    """Metric units use UCUM."""
    result = _unit_coding("mg")
    assert result["system"] == "http://unitsofmeasure.org"
    assert result["code"] == "mg"


def test_unit_coding_ucum_ml():
    result = _unit_coding("millilitre")
    assert result["system"] == "http://unitsofmeasure.org"
    assert result["code"] == "mL"


def test_unit_coding_unknown_fallback():
    """Unknown units default to UCUM with raw value."""
    result = _unit_coding("widgets")
    assert result["system"] == "http://unitsofmeasure.org"
    assert result["code"] == "widgets"


# ---------------------------------------------------------------------------
# When mapping tests
# ---------------------------------------------------------------------------


def test_when_mapping_before_food():
    # "before food" is now routed to additionalInstruction with SNOMED, not timing.repeat.when
    from dosage_instructions.data_enrichment.fhir_logic import _classify_when

    category, value = _classify_when("before food")
    assert category == "additional_snomed"
    assert value["code"] == "311500009"
    # _map_when_to_fhir returns None for this (it's no longer a timing code)
    assert _map_when_to_fhir("before food") is None


def test_when_mapping_at_night():
    assert _map_when_to_fhir("at night") == "NIGHT"


def test_when_mapping_with_breakfast():
    assert _map_when_to_fhir("with breakfast") == "CM"


def test_when_mapping_empty():
    assert _map_when_to_fhir("") is None
    assert _map_when_to_fhir(None) is None


# ---------------------------------------------------------------------------
# Full row_to_fhir_dosage tests
# ---------------------------------------------------------------------------


def test_fhir_basic_tablet_dose():
    """Take 2 tablets twice a day — SNOMED for tablet, SNOMED for method (STU3 structure)."""
    row = {
        "dosage": "take 2 tablets twice a day",
        "mapped": "True",
        "doseQuantity_clean": "2 tablets",
        "doseQuantity_value": ["2"],
        "doseQuantity_unit": ["tablet"],
        "frequencyBare_clean": "twice a day",
        "frequencyBare_frequency": ["2"],
        "frequencyBare_period_unit": ["day"],
        "methodDirect_clean": "take",
        "methodDirect_verb": ["take"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))

    assert dosage["text"] == "take 2 tablets twice a day"

    # doseQuantity is top-level on Dosage
    dq = dosage["doseQuantity"]
    assert dq["value"] == 2
    assert dq["system"] == "http://snomed.info/sct"
    assert dq["code"] == "428673006"
    assert dq["unit"] == "Tablet"

    # Timing
    assert dosage["timing"]["repeat"]["frequency"] == 2
    assert dosage["timing"]["repeat"]["periodUnit"] == "d"

    # Method: SNOMED
    assert dosage["method"]["coding"][0]["system"] == "http://snomed.info/sct"
    assert dosage["method"]["coding"][0]["code"] == "419652001"


def test_fhir_mg_dose():
    """5mg — UCUM for milligrams (STU3 structure)."""
    row = {
        "dosage": "inject 5mg subcutaneous",
        "mapped": "True",
        "milligramValue_clean": "5mg",
        "doseQuantity_value": ["5"],
        "doseQuantity_unit": ["mg"],
        "methodDirect_clean": "inject",
        "methodDirect_verb": ["inject"],
        "route_clean": "subcutaneous",
    }
    dosage = json.loads(row_to_fhir_dosage(row))

    # doseQuantity is top-level on Dosage
    dq = dosage["doseQuantity"]
    assert dq["value"] == 5
    assert dq["system"] == "http://unitsofmeasure.org"
    assert dq["code"] == "mg"

    # Method: newer inject code
    assert dosage["method"]["coding"][0]["code"] == "740685003"

    # Route: SNOMED
    assert dosage["route"]["coding"][0]["code"] == "34206005"


def test_fhir_dose_range():
    """1-2 capsules — SNOMED for capsule (STU3 structure)."""
    row = {
        "dosage": "1 to 2 capsules at night",
        "mapped": "True",
        "doseRange_clean": "1 to 2 capsules",
        "doseRange_low": ["1"],
        "doseRange_high": ["2"],
        "doseRange_lowunit": ["capsule"],
        "doseRange_highunit": ["capsule"],
        "whenBare_clean": "at night",
        "whenBare_when": ["night"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))

    # doseRange is top-level on Dosage
    dr = dosage["doseRange"]
    assert dr["low"]["value"] == 1
    assert dr["low"]["system"] == "http://snomed.info/sct"
    assert dr["low"]["code"] == "428641000"
    assert dr["high"]["value"] == 2
    assert dr["high"]["code"] == "428641000"

    assert dosage["timing"]["repeat"]["when"] == ["NIGHT"]


def test_fhir_dose_range_from_quantity_value_and_max_only():
    """dose_QuantityValueAndMaxOnly '1-2' with frequency — doseRange low AND high must populate.

    Regression test: previously doseRange_high was not populated because
    refine_lookup_output_func checked the overwritten doseRange_low column
    (which was already set from QVMO_value) to decide the branch, causing the
    FHIR logic to read the original empty doseRange_high instead of QVMO_valueMax.
    """
    row = {
        "dosage": "1-2 once every day",
        "mapped": "True",
        "dose_QuantityValueAndMaxOnly_clean": "1 to 2",
        "doseRange_low": ["1"],  # after refine: from dose_QuantityValueAndMaxOnly_value
        "doseRange_high": [
            "2"
        ],  # after refine: from dose_QuantityValueAndMaxOnly_valueMax
        "frequencyBare_clean": "once per day",
        "frequencyBare_frequency": ["1"],
        "frequencyBare_period_unit": ["day"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))

    # doseRange must have BOTH low and high
    dr = dosage["doseRange"]
    assert dr["low"]["value"] == 1
    assert dr["high"]["value"] == 2

    # Timing
    repeat = dosage["timing"]["repeat"]
    assert repeat["frequency"] == 1
    assert repeat["periodUnit"] == "d"


def test_fhir_as_needed():
    """As needed with codeable concept."""
    row = {
        "dosage": "1 tablet when required for pain",
        "mapped": "True",
        "dose_QuantityValueOnly_clean": "1",
        "dose_QuantityValueOnly_value": ["1"],
        # asNeededBoolean_clean is null — only the CC is populated when indication present
        "asNeededCodeableConcept_clean": "for pain",  # prefix stripped by pipeline
    }
    dosage = json.loads(row_to_fhir_dosage(row))

    ancc = dosage["asNeededCodeableConcept"]
    assert ancc["text"] == "for pain"
    assert ancc["coding"][0]["code"] == "22253000"
    assert ancc["coding"][0]["display"] == "Pain"
    assert ancc["coding"][0]["system"] == "http://snomed.info/sct"
    assert "asNeededBoolean" not in dosage  # boolean absent when CC is present


def test_fhir_unmapped_returns_none():
    """Unmapped rows should not be processed (caller checks mapped flag)."""
    row = {"dosage": "something", "mapped": "False"}
    # The caller in refine_function checks mapped == True before calling
    # but row_to_fhir_dosage itself just builds from whatever is there
    dosage = json.loads(row_to_fhir_dosage(row))
    assert dosage["text"] == "something"


def test_fhir_max_dose_per_period():
    """Max dose uses SNOMED for tablet unit."""
    row = {
        "dosage": "1-2 tablets every 4 hours max 8 in 24 hours",
        "mapped": "True",
        "doseRange_clean": "1-2 tablets",
        "doseRange_low": ["1"],
        "doseRange_high": ["2"],
        "doseRange_units": ["tablet"],
        "maxDosePerPeriod_clean": "max 8 in 24 hours",
        "maxDosePerPeriod_num_value": ["8"],
        "maxDosePerPeriod_num_unit": ["tablet"],
        "maxDosePerPeriod_denom_value": ["24"],
        "maxDosePerPeriod_denom_unit": ["hour"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))

    mdp = dosage["maxDosePerPeriod"]
    assert mdp["numerator"]["value"] == 8
    assert mdp["numerator"]["unit"] == "Tablet"
    assert mdp["numerator"]["system"] == "http://snomed.info/sct"
    assert mdp["numerator"]["code"] == "428673006"
    assert mdp["denominator"]["value"] == 24
    assert mdp["denominator"]["unit"] == "hour"
    assert mdp["denominator"]["system"] == "http://unitsofmeasure.org"
    assert mdp["denominator"]["code"] == "h"


def test_fhir_inhale_puffs():
    """Inhale 2 puffs — newer inhale code + SNOMED puff (STU3 structure)."""
    row = {
        "dosage": "inhale 2 puffs twice daily",
        "mapped": "True",
        "doseQuantity_clean": "2 puffs",
        "doseQuantity_value": ["2"],
        "doseQuantity_unit": ["puff"],
        "frequencyBare_clean": "twice daily",
        "frequencyBare_frequency": ["2"],
        "frequencyBare_period_unit": ["day"],
        "methodDirect_clean": "inhale",
        "methodDirect_verb": ["inhale"],
        "route_clean": "inhalation",
    }
    dosage = json.loads(row_to_fhir_dosage(row))

    # doseQuantity is top-level on Dosage
    dq = dosage["doseQuantity"]
    assert dq["system"] == "http://snomed.info/sct"
    assert dq["code"] == "415215001"
    assert dq["unit"] == "Puff"

    assert dosage["method"]["coding"][0]["code"] == "740666001"
    assert dosage["route"]["coding"][0]["code"] == "18679011000001101"


# ---------------------------------------------------------------------------
# Dose element isolation tests — value and unit must come from same element
# ---------------------------------------------------------------------------


def test_fhir_dose_value_only_no_mg_unit_bleed():
    """(300mg) 3 to be taken at night — dose value=3 must NOT get unit=mg from milligramValue.

    milligramValue is a clarification only; the actual dose is '3 [tablets]' with no explicit unit.
    STU3 structure: doseQuantity directly on Dosage.
    """
    row = {
        "dosage": "(300mg) 3 to be taken at night",
        "mapped": "True",
        "dose_QuantityValueOnly_clean": "3",
        "doseQuantity_value": ["3"],  # refined: came from dose_QuantityValueOnly
        "doseQuantity_unit": None,  # refined: no unit from dose_QuantityValueOnly
        "milligramValue_clean": "300 mg",
        "milligramValue_value": ["300"],
        "milligramValue_milligram_units": ["mg"],
        "methodPassive_clean": "take",
        "methodPassive_verb": ["take"],
        "whenBare_clean": "at night",
        "whenBare_when": ["at night"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    dq = dosage["doseQuantity"]
    assert dq["value"] == 3
    # Unit must NOT be "mg" — that would be dangerous (3mg ≠ 3 tablets)
    assert "unit" not in dq
    assert "code" not in dq
    assert "system" not in dq
    # milligramValue should appear as patientInstruction
    assert dosage["patientInstruction"] == "(300 mg)"


def test_fhir_mg_only_dose_gets_unit():
    """5mg with no other dose element — milligramValue provides BOTH value and unit (STU3)."""
    row = {
        "dosage": "take 5mg at night",
        "mapped": "True",
        "milligramValue_clean": "5 mg",
        "doseQuantity_value": ["5"],  # refined: came from milligramValue (only source)
        "doseQuantity_unit": [
            "mg"
        ],  # refined: from milligramValue (safe, no other dose)
        "methodDirect_clean": "take",
        "methodDirect_verb": ["take"],
        "whenBare_clean": "at night",
        "whenBare_when": ["at night"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    dq = dosage["doseQuantity"]
    assert dq["value"] == 5
    assert dq["code"] == "mg"
    assert dq["system"] == "http://unitsofmeasure.org"


# ---------------------------------------------------------------------------
# Timing / repeat mapping tests — periodElement scenarios
# ---------------------------------------------------------------------------


def test_fhir_period_once_every_day():
    """periodElement pattern1: 'per day' → frequency=1, period=1, periodUnit=d."""
    row = {
        "dosage": "1 tablet per day",
        "mapped": "True",
        "dose_QuantityValueOnly_clean": "1",
        "dose_QuantityValueOnly_value": ["1"],
        "periodElement_clean": "once every day",
        "periodElement_period": ["1"],
        "periodElement_periodMax": [""],
        "periodElement_period_units": ["day"],
        "periodElement_frequency": ["1"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    repeat = dosage["timing"]["repeat"]
    assert repeat["frequency"] == 1
    assert repeat["period"] == 1
    assert repeat["periodUnit"] == "d"
    assert "periodMax" not in repeat


def test_fhir_period_once_every_4_weeks():
    """periodElement pattern2: 'every 4 weeks' → frequency=1, period=4, periodUnit=wk."""
    row = {
        "dosage": "1 injection every 4 weeks",
        "mapped": "True",
        "doseQuantity_clean": "1 injection",
        "doseQuantity_value": ["1"],
        "doseQuantity_unit": ["injection"],
        "periodElement_clean": "once every 4 weeks",
        "periodElement_period": ["4"],
        "periodElement_periodMax": [""],
        "periodElement_period_units": ["weeks"],
        "periodElement_frequency": ["1"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    repeat = dosage["timing"]["repeat"]
    assert repeat["frequency"] == 1
    assert repeat["period"] == 4
    assert repeat["periodUnit"] == "wk"
    assert "periodMax" not in repeat


def test_fhir_period_once_every_4_to_6_hours():
    """periodElement pattern3: 'every 4 to 6 hours' → frequency=1, period=4, periodMax=6, periodUnit=h."""
    row = {
        "dosage": "1-2 tablets every 4 to 6 hours",
        "mapped": "True",
        "doseRange_clean": "1 to 2 tablets",
        "doseRange_low": ["1"],
        "doseRange_high": ["2"],
        "doseRange_lowunit": ["tablet"],
        "doseRange_highunit": ["tablet"],
        "periodElement_clean": "once every 4 to 6 hours",
        "periodElement_period": ["4"],
        "periodElement_periodMax": ["6"],
        "periodElement_period_units": ["hours"],
        "periodElement_frequency": ["1"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    repeat = dosage["timing"]["repeat"]
    assert repeat["frequency"] == 1
    assert repeat["period"] == 4
    assert repeat["periodMax"] == 6
    assert repeat["periodUnit"] == "h"


def test_fhir_period_alternate_days():
    """periodElement pattern4/5: 'every other day' → frequency=1, period=2, periodUnit=d."""
    row = {
        "dosage": "1 tablet on alternate days",
        "mapped": "True",
        "dose_QuantityValueOnly_clean": "1",
        "dose_QuantityValueOnly_value": ["1"],
        "periodElement_clean": "once every 2 days",
        "periodElement_period": ["2"],
        "periodElement_periodMax": [""],
        "periodElement_period_units": ["days"],
        "periodElement_frequency": ["1"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    repeat = dosage["timing"]["repeat"]
    assert repeat["frequency"] == 1
    assert repeat["period"] == 2
    assert repeat["periodUnit"] == "d"
    assert "periodMax" not in repeat


def test_fhir_period_once_every_month():
    """periodElement pattern1 with month: 'per month' → frequency=1, period=1, periodUnit=mo."""
    row = {
        "dosage": "1 injection per month",
        "mapped": "True",
        "doseQuantity_clean": "1 injection",
        "doseQuantity_value": ["1"],
        "doseQuantity_unit": ["injection"],
        "periodElement_clean": "once every month",
        "periodElement_period": ["1"],
        "periodElement_periodMax": [""],
        "periodElement_period_units": ["month"],
        "periodElement_frequency": ["1"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    repeat = dosage["timing"]["repeat"]
    assert repeat["frequency"] == 1
    assert repeat["period"] == 1
    assert repeat["periodUnit"] == "mo"


# ---------------------------------------------------------------------------
# Timing / repeat mapping tests — frequencyBare scenarios
# ---------------------------------------------------------------------------


def test_fhir_frequency_twice_a_day():
    """frequencyBare: '2 times per day' → frequency=2, period=1, periodUnit=d."""
    row = {
        "dosage": "1 tablet twice a day",
        "mapped": "True",
        "doseQuantity_clean": "1 tablet",
        "doseQuantity_value": ["1"],
        "doseQuantity_unit": ["tablet"],
        "frequencyBare_clean": "2 times per day",
        "frequencyBare_frequency": ["2"],
        "frequencyBare_period_unit": ["day"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    repeat = dosage["timing"]["repeat"]
    assert repeat["frequency"] == 2
    assert repeat["period"] == 1
    assert repeat["periodUnit"] == "d"


def test_fhir_frequency_three_times_a_day():
    """frequencyBare: '3 times per day' → frequency=3, period=1, periodUnit=d."""
    row = {
        "dosage": "1 tablet three times a day",
        "mapped": "True",
        "doseQuantity_clean": "1 tablet",
        "doseQuantity_value": ["1"],
        "doseQuantity_unit": ["tablet"],
        "frequencyBare_clean": "3 times per day",
        "frequencyBare_frequency": ["3"],
        "frequencyBare_period_unit": ["day"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    repeat = dosage["timing"]["repeat"]
    assert repeat["frequency"] == 3
    assert repeat["period"] == 1
    assert repeat["periodUnit"] == "d"


def test_fhir_frequency_once_per_week():
    """frequencyBare: 'once per week' → frequency=1, period=1, periodUnit=wk."""
    row = {
        "dosage": "take 1 tablet once a week",
        "mapped": "True",
        "doseQuantity_clean": "1 tablet",
        "doseQuantity_value": ["1"],
        "doseQuantity_unit": ["tablet"],
        "frequencyBare_clean": "once per week",
        "frequencyBare_frequency": ["1"],
        "frequencyBare_period_unit": ["week"],
        "methodDirect_clean": "take",
        "methodDirect_verb": ["take"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    repeat = dosage["timing"]["repeat"]
    assert repeat["frequency"] == 1
    assert repeat["period"] == 1
    assert repeat["periodUnit"] == "wk"


def test_fhir_frequency_once_per_fortnight():
    """frequencyBare: 'once per fortnight' → frequency=1, period=2, periodUnit=wk."""
    row = {
        "dosage": "take 1 tablet once every fortnight",
        "mapped": "True",
        "doseQuantity_clean": "1 tablet",
        "doseQuantity_value": ["1"],
        "doseQuantity_unit": ["tablet"],
        "frequencyBare_clean": "once per fortnight",
        "frequencyBare_frequency": ["1"],
        "frequencyBare_period_unit": ["fortnight"],
        "methodDirect_clean": "take",
        "methodDirect_verb": ["take"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    repeat = dosage["timing"]["repeat"]
    assert repeat["frequency"] == 1
    assert repeat["period"] == 2
    assert repeat["periodUnit"] == "wk"


def test_fhir_frequency_up_to_4_times_a_day():
    """frequencyBare with max: 'up to 4 times per day' → frequency=4, frequencyMax=4, period=1, periodUnit=d."""
    row = {
        "dosage": "1-2 tablets up to 4 times a day",
        "mapped": "True",
        "doseRange_clean": "1 to 2 tablets",
        "doseRange_low": ["1"],
        "doseRange_high": ["2"],
        "doseRange_lowunit": ["tablet"],
        "doseRange_highunit": ["tablet"],
        "frequencyBare_clean": "up to 4 times per day",
        "frequencyBare_frequency": ["4"],
        "frequencyBare_frequencyMax": ["4"],
        "frequencyBare_period_unit": ["day"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    repeat = dosage["timing"]["repeat"]
    assert repeat["frequency"] == 4
    assert repeat["frequencyMax"] == 4
    assert repeat["period"] == 1
    assert repeat["periodUnit"] == "d"


# ---------------------------------------------------------------------------
# Timing / repeat mapping tests — count scenarios
# ---------------------------------------------------------------------------


def test_fhir_count_once():
    """count: 'take 2 tablets once' → count=1, no frequency/period."""
    row = {
        "dosage": "take 2 tablets once",
        "mapped": "True",
        "doseQuantity_clean": "2 tablets",
        "doseQuantity_value": ["2"],
        "doseQuantity_unit": ["tablet"],
        "count_clean": "once",
        "count_count": ["1"],
        "count_countMax": [""],
        "methodDirect_clean": "take",
        "methodDirect_verb": ["take"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    repeat = dosage["timing"]["repeat"]
    assert repeat["count"] == 1
    assert "frequency" not in repeat
    assert "period" not in repeat
    assert "periodUnit" not in repeat


# ---------------------------------------------------------------------------
# Timing / repeat mapping tests — combined period + duration
# ---------------------------------------------------------------------------


def test_fhir_period_with_bounds_duration():
    """periodElement + boundsDuration: 'once every day for 3 weeks'."""
    row = {
        "dosage": "take 1 tablet per day for 3 weeks",
        "mapped": "True",
        "doseQuantity_clean": "1 tablet",
        "doseQuantity_value": ["1"],
        "doseQuantity_unit": ["tablet"],
        "periodElement_clean": "once every day",
        "periodElement_period": ["1"],
        "periodElement_periodMax": [""],
        "periodElement_period_units": ["day"],
        "periodElement_frequency": ["1"],
        "boundsDuration_clean": "for 3 weeks",
        "boundsDuration_value": ["3"],
        "boundsDuration_unit": ["week"],
        "methodDirect_clean": "take",
        "methodDirect_verb": ["take"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    repeat = dosage["timing"]["repeat"]
    assert repeat["frequency"] == 1
    assert repeat["period"] == 1
    assert repeat["periodUnit"] == "d"
    assert repeat["boundsDuration"]["value"] == 3
    assert repeat["boundsDuration"]["unit"] == "week"
    assert repeat["boundsDuration"]["system"] == "http://unitsofmeasure.org"
    assert repeat["boundsDuration"]["code"] == "wk"


# ---------------------------------------------------------------------------
# Site extension tests
# ---------------------------------------------------------------------------


def test_site_each_nostril_extension_structure():
    """'each nostril' should produce a nested sctdescid extension on the site coding."""
    import json

    row = {
        "mapped": "True",
        "doseQuantity_clean": "2 sprays",
        "doseQuantity_value": ["2"],
        "doseQuantity_unit": ["spray"],
        "periodElement_clean": "2 times per day",
        "periodElement_period": ["1"],
        "periodElement_periodMax": [""],
        "periodElement_period_units": ["day"],
        "periodElement_frequency": ["2"],
        "site_clean": "each nostril",
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    coding = dosage["site"]["coding"][0]

    assert coding["code"] == "45206002"
    assert coding["display"] == "Nasal cavity structure"

    ext_outer = coding["extension"]
    assert len(ext_outer) == 1
    assert (
        ext_outer[0]["url"]
        == "https://fhir.hl7.org.uk/STU3/StructureDefinition/Extension-coding-sctdescid"
    )

    ext_inner = ext_outer[0]["extension"]
    assert len(ext_inner) == 1
    assert ext_inner[0]["url"] == "descriptionDisplay"
    assert ext_inner[0]["valueString"] == "Each nostril"


# ---------------------------------------------------------------------------
# Route FHIR output tests
# ---------------------------------------------------------------------------


def test_fhir_route_oral_snomed():
    """Oral route maps to SNOMED 26643006."""
    from dosage_instructions.data_enrichment.fhir_logic import _build_route

    result = _build_route({"route_clean": "oral"})
    assert result["coding"][0]["system"] == "http://snomed.info/sct"
    assert result["coding"][0]["code"] == "26643006"
    assert result["coding"][0]["display"] == "Oral"


def test_fhir_route_subcutaneous_snomed():
    """Subcutaneous route maps to SNOMED 34206005."""
    from dosage_instructions.data_enrichment.fhir_logic import _build_route

    result = _build_route({"route_clean": "subcutaneous"})
    assert result["coding"][0]["code"] == "34206005"


def test_fhir_route_inhalation_snomed():
    """Inhalation route maps to SNOMED."""
    from dosage_instructions.data_enrichment.fhir_logic import _build_route

    result = _build_route({"route_clean": "inhalation"})
    assert result["coding"][0]["code"] == "18679011000001101"


def test_fhir_route_unknown_text_fallback():
    """Unknown route falls back to text-only."""
    from dosage_instructions.data_enrichment.fhir_logic import _build_route

    result = _build_route({"route_clean": "some unknown route"})
    assert "text" in result
    assert "coding" not in result


def test_fhir_route_none_returns_none():
    """Missing route_clean returns None."""
    from dosage_instructions.data_enrichment.fhir_logic import _build_route

    assert _build_route({}) is None
    assert _build_route({"route_clean": None}) is None
    assert _build_route({"route_clean": ""}) is None


# ---------------------------------------------------------------------------
# _build_indication_concept tests (new — INDICATION_TO_SNOMED)
# ---------------------------------------------------------------------------


def test_build_indication_pain_snomed():
    """'for pain' maps to SNOMED 22253000 Pain."""
    from dosage_instructions.data_enrichment.fhir_logic import _build_indication_concept

    result = _build_indication_concept("for pain")
    assert result["coding"][0]["code"] == "22253000"
    assert result["coding"][0]["display"] == "Pain"
    assert result["coding"][0]["system"] == "http://snomed.info/sct"
    assert result["text"] == "for pain"


def test_build_indication_neuropathic_pain_wins_over_pain():
    """'for neuropathic pain' must match neuropathic pain (57676002) not bare pain (22253000).
    Tests longest-key-first ordering."""
    from dosage_instructions.data_enrichment.fhir_logic import _build_indication_concept

    result = _build_indication_concept("for neuropathic pain")
    assert result["coding"][0]["code"] == "57676002"
    assert result["coding"][0]["display"] == "Neuropathic pain"


def test_build_indication_high_bp_wins_over_bp():
    """'for high blood pressure' → Hypertension (38341003) not bare blood pressure."""
    from dosage_instructions.data_enrichment.fhir_logic import _build_indication_concept

    result = _build_indication_concept("for high blood pressure")
    assert result["coding"][0]["code"] == "38341003"
    assert result["coding"][0]["display"] == "Hypertension"


def test_build_indication_anxiety():
    from dosage_instructions.data_enrichment.fhir_logic import _build_indication_concept

    result = _build_indication_concept("for anxiety")
    assert result["coding"][0]["code"] == "48694002"


def test_build_indication_diabetes():
    from dosage_instructions.data_enrichment.fhir_logic import _build_indication_concept

    result = _build_indication_concept("for diabetes")
    assert result["coding"][0]["code"] == "73211009"


def test_build_indication_cholesterol():
    from dosage_instructions.data_enrichment.fhir_logic import _build_indication_concept

    result = _build_indication_concept("for your cholesterol")
    assert result["coding"][0]["code"] == "13644009"
    assert result["coding"][0]["display"] == "Hypercholesterolaemia"


def test_build_indication_unknown_text_fallback():
    """Unknown phrase falls back to text-only, no coding key."""
    from dosage_instructions.data_enrichment.fhir_logic import _build_indication_concept

    result = _build_indication_concept("for some unknown condition xyz")
    assert result == {"text": "for some unknown condition xyz"}
    assert "coding" not in result


def test_build_indication_none_returns_none():
    from dosage_instructions.data_enrichment.fhir_logic import _build_indication_concept

    assert _build_indication_concept(None) is None
    assert _build_indication_concept("") is None


# ---------------------------------------------------------------------------
# _build_as_needed — all branches
# ---------------------------------------------------------------------------


def test_fhir_as_needed_boolean_only():
    """asNeededBoolean only (no indication) → asNeededBoolean: True."""
    row = {
        "dosage": "1 tablet as required",
        "mapped": "True",
        "asNeededBoolean_clean": "as needed",
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    assert dosage["asNeededBoolean"] is True
    assert "asNeededCodeableConcept" not in dosage


def test_fhir_as_needed_cc_only():
    """asNeededCodeableConcept only (no boolean) → asNeededCodeableConcept with SNOMED."""
    row = {
        "dosage": "1 tablet for pain",
        "mapped": "True",
        "asNeededCodeableConcept_clean": "for pain",
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    assert "asNeededBoolean" not in dosage
    ancc = dosage["asNeededCodeableConcept"]
    assert ancc["coding"][0]["code"] == "22253000"


def test_fhir_as_needed_boolean_with_cc_prefers_cc():
    """When both boolean and CC are present, CC wins (asNeededCodeableConcept returned)."""
    row = {
        "dosage": "1 tablet as needed for pain",
        "mapped": "True",
        "asNeededBoolean_clean": "as needed",
        "asNeededCodeableConcept_clean": "for pain",
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    assert "asNeededBoolean" not in dosage
    assert dosage["asNeededCodeableConcept"]["coding"][0]["code"] == "22253000"


# ---------------------------------------------------------------------------
# _classify_when — meal compounds, prefix phrases, whole-word option matching
# ---------------------------------------------------------------------------


def test_classify_when_meal_compounds_are_additional_text():
    """Meal compounds (evening meal, morning meal, main meal) → additional_text, NOT timing."""
    from dosage_instructions.data_enrichment.fhir_logic import _classify_when

    for phrase in [
        "with evening meal",
        "after evening meal",
        "before evening meal",
        "with morning meal",
        "with main meal",
        "after main meal",
        "before main meal",
        "with the evening meal",
        "after the main meal",
    ]:
        cat, _ = _classify_when(phrase)
        assert (
            cat == "additional_text"
        ), f"Expected additional_text for {phrase!r}, got {cat!r}"


def test_classify_when_with_meal_is_timing_c():
    """'with meal' (bare) → timing C."""
    from dosage_instructions.data_enrichment.fhir_logic import _classify_when

    cat, val = _classify_when("with meal")
    assert cat == "timing"
    assert val == "C"


def test_classify_when_before_meal_is_timing_ac():
    from dosage_instructions.data_enrichment.fhir_logic import _classify_when

    cat, val = _classify_when("before meal")
    assert cat == "timing"
    assert val == "AC"


def test_classify_when_evening_bare_is_timing_eve():
    """Bare 'in the evening' (no meal) → timing EVE."""
    from dosage_instructions.data_enrichment.fhir_logic import _classify_when

    cat, val = _classify_when("in the evening")
    assert cat == "timing"
    assert val == "EVE"


def test_classify_when_morning_bare_is_timing_morn():
    from dosage_instructions.data_enrichment.fhir_logic import _classify_when

    cat, val = _classify_when("in the morning")
    assert cat == "timing"
    assert val == "MORN"


def test_classify_when_with_food_snomed():
    """'with food' → additional_snomed."""
    from dosage_instructions.data_enrichment.fhir_logic import _classify_when

    cat, val = _classify_when("with food")
    assert cat == "additional_snomed"
    assert val["code"] == "1116481000001105"


def test_classify_when_after_food_snomed():
    from dosage_instructions.data_enrichment.fhir_logic import _classify_when

    cat, val = _classify_when("after food")
    assert cat == "additional_snomed"
    assert val["code"] == "225758001"


def test_classify_when_empty_stomach_additional_text():
    from dosage_instructions.data_enrichment.fhir_logic import _classify_when

    cat, _ = _classify_when("on an empty stomach")
    assert cat == "additional_text"


def test_classify_when_with_breakfast_timing_cm():
    from dosage_instructions.data_enrichment.fhir_logic import _classify_when

    cat, val = _classify_when("with breakfast")
    assert cat == "timing"
    assert val == "CM"


def test_classify_when_before_sleep_timing_hs():
    from dosage_instructions.data_enrichment.fhir_logic import _classify_when

    cat, val = _classify_when("before sleep")
    assert cat == "timing"
    assert val == "HS"


def test_classify_when_at_night_timing_night():
    from dosage_instructions.data_enrichment.fhir_logic import _classify_when

    cat, val = _classify_when("at night")
    assert cat == "timing"
    assert val == "NIGHT"


# ---------------------------------------------------------------------------
# _build_additional_instructions tests
# ---------------------------------------------------------------------------


def test_fhir_additional_instruction_as_directed_snomed():
    """'as directed' → additionalInstruction with SNOMED 1116431000001106."""
    row = {
        "dosage": "take as directed",
        "mapped": "True",
        "extrasAsDirected_clean": "as directed",
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    ai = dosage["additionalInstruction"]
    assert any(
        c.get("code") == "1116431000001106"
        for entry in ai
        for c in entry.get("coding", [])
    )


def test_fhir_additional_instruction_sparingly_snomed():
    """'sparingly' → additionalInstruction with SNOMED 420883007."""
    row = {
        "dosage": "apply sparingly",
        "mapped": "True",
        "extras_clean": "sparingly",
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    ai = dosage["additionalInstruction"]
    assert any(
        c.get("code") == "420883007" for entry in ai for c in entry.get("coding", [])
    )


def test_fhir_additional_instruction_with_food_snomed():
    """'with food' when element → additionalInstruction SNOMED 1116481000001105.
    The FHIR builder calls _classify_when on whenBare_clean (the full phrase),
    which is what drives the SNOMED routing — not the sub-field array."""
    from dosage_instructions.data_enrichment.fhir_logic import _classify_when

    cat, val = _classify_when("with food")
    assert cat == "additional_snomed"
    assert val["code"] == "1116481000001105"
    assert val["display"] == "With food"


def test_fhir_additional_instruction_text_only():
    """Unknown extras → additionalInstruction as text-only."""
    row = {
        "dosage": "take regularly",
        "mapped": "True",
        "extras_clean": "regularly",
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    ai = dosage["additionalInstruction"]
    texts = [e.get("text") for e in ai]
    assert "regularly" in texts


# ---------------------------------------------------------------------------
# _build_site — coded + text fallback
# ---------------------------------------------------------------------------


def test_fhir_site_left_eye_snomed():
    """Left eye maps to SNOMED 8966001."""
    row = {"mapped": "True", "site_clean": "left eye"}
    dosage = json.loads(row_to_fhir_dosage(row))
    coding = dosage["site"]["coding"][0]
    assert coding["code"] == "8966001"
    assert coding["display"] == "Left eye structure"


def test_fhir_site_right_eye_snomed():
    row = {"mapped": "True", "site_clean": "right eye"}
    dosage = json.loads(row_to_fhir_dosage(row))
    assert dosage["site"]["coding"][0]["code"] == "18944008"


def test_fhir_site_both_eyes_snomed():
    row = {"mapped": "True", "site_clean": "Both eyes"}
    dosage = json.loads(row_to_fhir_dosage(row))
    assert dosage["site"]["coding"][0]["code"] == "40638003"


def test_fhir_site_tongue_snomed():
    row = {"mapped": "True", "site_clean": "tongue"}
    dosage = json.loads(row_to_fhir_dosage(row))
    assert dosage["site"]["coding"][0]["code"] == "21974007"


def test_fhir_site_affected_area_snomed():
    row = {"mapped": "True", "site_clean": "affected area"}
    dosage = json.loads(row_to_fhir_dosage(row))
    assert dosage["site"]["coding"][0]["code"] == "22201000087104"


def test_fhir_site_unknown_text_fallback():
    """Unrecognised site → text-only."""
    row = {"mapped": "True", "site_clean": "the wrist"}
    dosage = json.loads(row_to_fhir_dosage(row))
    assert dosage["site"].get("text") == "the wrist"
    assert "coding" not in dosage["site"]


# ---------------------------------------------------------------------------
# maxDosePerAdministration and maxDosePerLifetime
# ---------------------------------------------------------------------------


def test_fhir_max_dose_per_administration():
    """maxDosePerAdministration populates doseQuantity in FHIR."""
    row = {
        "dosage": "up to a maximum of 4 puffs per dose",
        "mapped": "True",
        "maxDosePerAdministration_clean": "up to a maximum of 4 puffs per dose",
        "maxDosePerAdministration_value": ["4"],
        "maxDosePerAdministration_unit": ["puff"],
        "maxDosePerAdministration_unit_code": "415215001",
        "maxDosePerAdministration_unit_display": "Puff",
        "maxDosePerAdministration_unit_system": "http://snomed.info/sct",
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    mdpa = dosage["maxDosePerAdministration"]
    assert mdpa["value"] == 4
    assert mdpa["unit"] == "Puff"
    assert mdpa["system"] == "http://snomed.info/sct"
    assert mdpa["code"] == "415215001"


def test_fhir_max_dose_per_lifetime():
    """maxDosePerLifetime populates doseQuantity in FHIR."""
    row = {
        "dosage": "up to a maximum of 2 tablets for the lifetime of patient",
        "mapped": "True",
        "maxDosePerLifetime_clean": "up to a maximum of 2 tablets for the lifetime of patient",
        "maxDosePerLifetime_value": ["2"],
        "maxDosePerLifetime_unit": ["tablet"],
        "maxDosePerLifetime_unit_code": "428673006",
        "maxDosePerLifetime_unit_display": "Tablet",
        "maxDosePerLifetime_unit_system": "http://snomed.info/sct",
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    mdpl = dosage["maxDosePerLifetime"]
    assert mdpl["value"] == 2
    assert mdpl["unit"] == "Tablet"
    assert mdpl["code"] == "428673006"


# ---------------------------------------------------------------------------
# _build_rate tests
# ---------------------------------------------------------------------------


def test_fhir_rate_ratio():
    """rateRatio builds a Ratio with numerator and denominator."""
    row = {
        "dosage": "at a rate of 4 per day",
        "mapped": "True",
        "rateRatio_clean": "at a rate of 4 per day",
        "rateRatio_numerator": ["4"],
        "rateRatio_numerator_unit": ["tablet"],
        "rateRatio_denominator": ["1"],
        "rateRatio_periodUnit": ["day"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    rr = dosage["rateRatio"]
    assert rr["numerator"]["value"] == 4
    assert rr["denominator"]["value"] == 1
    assert rr["denominator"]["unit"] == "day"


def test_fhir_rate_quantity():
    """rateQuantity builds a Quantity."""
    row = {
        "dosage": "at a rate of 5 litres per minute",
        "mapped": "True",
        "rateQuantity_clean": "at a rate of 5 litres per minute",
        "rateQuantity_value": ["5"],
        "rateQuantity_unit": ["litre"],
        "rateQuantity_period_unit": ["minute"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    assert "rateQuantity" in dosage
    rq = dosage["rateQuantity"]
    assert rq["value"] == 5


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])


# ---------------------------------------------------------------------------
# Instil / Instill method SNOMED mapping
# ---------------------------------------------------------------------------


def test_fhir_instil_british_maps_to_snomed():
    """British spelling 'instil' maps to SNOMED 738994005 (Instill)."""
    row = {
        "dosage": "instil 1 drop every 4 hours",
        "mapped": "True",
        "methodDirect_clean": "instil",
        "methodDirect_verb": ["instil"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    assert dosage["method"]["coding"][0]["code"] == "738994005"
    assert dosage["method"]["coding"][0]["display"] == "Instill"


def test_fhir_instill_american_maps_to_snomed():
    """American spelling 'instill' (from spaCy lemma) maps to SNOMED 738994005."""
    row = {
        "dosage": "instill 1 drop every 4 hours",
        "mapped": "True",
        "methodDirect_clean": "instill",
        "methodDirect_verb": ["instill"],
    }
    dosage = json.loads(row_to_fhir_dosage(row))
    assert dosage["method"]["coding"][0]["code"] == "738994005"
    assert dosage["method"]["coding"][0]["display"] == "Instill"
