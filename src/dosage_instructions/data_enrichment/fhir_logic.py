import json
import re

import numpy as np

import dosage_instructions.model.constants as myconstants

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _has(row, col_name):
    """Check if a row has a non-empty value for a column."""

    val = row.get(col_name)
    if val is None:
        return False
    if isinstance(val, float) and (val != val):
        return False
    if isinstance(val, str):
        return val.strip() != ""
    if isinstance(val, (list, np.ndarray)):
        return len(val) > 0 and any(v for v in val)
    return bool(val)


def _first(row, col_name):
    """Extract first value from a column (handles arrays and numpy arrays from Spark)."""

    val = row.get(col_name)
    if val is None:
        return None
    if isinstance(val, float) and (val != val):
        return None
    if isinstance(val, np.ndarray):
        if len(val) == 0:
            return None
        elem = val[0]
        return elem.item() if isinstance(elem, np.generic) else elem
    if isinstance(val, list):
        return val[0] if val else None
    if isinstance(val, np.generic):
        return val.item()
    return val


def _num(val):
    """Convert value to numeric."""
    if val is None:
        return None
    try:
        f = float(val)
        return int(f) if f == int(f) else f
    except (ValueError, TypeError):
        return None


def _apply_dose_coding(qty_dict, unit, spoonsize=None):
    """Attach unit/system/code to a FHIR quantity dict in-place."""
    coding = _unit_coding(unit, spoonsize=spoonsize)
    if coding:
        qty_dict["unit"] = coding["display"]
        if coding["system"]:
            qty_dict["system"] = coding["system"]
        if coding["code"]:
            qty_dict["code"] = coding["code"]


def _unit_coding(raw_unit, spoonsize=None):
    """Return {system, code, display} for a unit — SNOMED for dose forms, UCUM for metric.

    For spoonful units, if a spoonsize (e.g. "5" or "2.5") is provided the size-specific
    SNOMED concept is used where one exists, or display-only where it does not.
    """
    if not raw_unit:
        return None
    unit_lower = raw_unit.lower().strip()

    # Spoonful with a known size — use size-specific coding
    if unit_lower in ("spoon", "spoons", "spoonful", "spoonfuls") and spoonsize:
        size_key = str(spoonsize).strip()
        size_entry = myconstants.SPOON_SIZE_TO_SNOMED.get(size_key)
        if size_entry:
            if size_entry["code"]:
                return {
                    "system": "http://snomed.info/sct",
                    "code": size_entry["code"],
                    "display": size_entry["display"],
                }
            else:
                # No code available — display only
                return {
                    "system": None,
                    "code": None,
                    "display": size_entry["display"],
                }

    snomed = myconstants.DOSE_FORM_TO_SNOMED.get(unit_lower)
    if snomed:
        return {
            "system": "http://snomed.info/sct",
            "code": snomed["code"],
            "display": snomed["display"],
        }

    ucum = myconstants.METRIC_UNIT_TO_UCUM.get(unit_lower)
    if ucum:
        return {
            "system": "http://unitsofmeasure.org",
            "code": ucum,
            "display": ucum,
        }

    return {
        "system": "http://unitsofmeasure.org",
        "code": raw_unit,
        "display": raw_unit,
    }


def _classify_when(when_text, has_offset=False):
    """Classify a when phrase into its FHIR routing category.

    Returns a tuple of (category, value) where:
      - ("additional_snomed", {code, display}) — move to additionalInstruction with SNOMED
      - ("additional_text", text) — move to additionalInstruction as free text
      - ("timing", fhir_code) — keep in timing.repeat.when
      - ("none", None) — no mapping found

    When has_offset=True and the phrase would normally be category 1 (additional
    with SNOMED), it is downgraded to category 3 (additional text only) because
    the offset makes the instruction more specific than the SNOMED code captures.
    E.g. "before food" → SNOMED 311500009, but "30 minutes before food" → text only.
    """
    if not when_text:
        return ("none", None)
    text = when_text.lower().strip()

    # Category 1: additionalInstruction with SNOMED code
    # (downgraded to text-only if an offset is present)
    for keyword, snomed in myconstants.WHEN_TO_ADDITIONAL_INSTRUCTION_SNOMED.items():
        if keyword in text:
            if has_offset:
                return ("additional_text", when_text)
            return ("additional_snomed", snomed)

    # Category 3: additionalInstruction text only (explicit keywords checked early)
    for keyword in myconstants.WHEN_TO_ADDITIONAL_INSTRUCTION_TEXT:
        if keyword in text:
            return ("additional_text", when_text)

    # Category 2: timing.repeat.when — prefix-based
    # Match "prefix option" as a phrase (not independently) to avoid false positives
    # e.g. "with evening meal" contains both "with" and "meal" but is NOT "with meal"
    for (prefix, option), code in myconstants.WHEN_PREFIX_MAP.items():
        if f"{prefix} {option}" in text:
            return ("timing", code)

    # Category 2: timing.repeat.when — option-only
    for option, code in myconstants.WHEN_OPTION_TO_FHIR.items():
        if option in text:
            return ("timing", code)

    # Fallback: anything else that was captured as a when element but doesn't
    # match a known FHIR timing code → additionalInstruction as text.
    return ("additional_text", when_text)


def _map_when_to_fhir(when_text):
    """Map when text to FHIR EventTiming code (backwards-compatible wrapper)."""
    category, value = _classify_when(when_text)
    if category == "timing":
        return value
    return None


def _offset_to_minutes(value, period_unit):
    """Convert offset value + period unit to minutes."""
    if not value:
        return None
    val = _num(value)
    if val is None:
        return None
    multipliers = {"minute": 1, "hour": 60, "day": 1440, "week": 10080}
    mult = multipliers.get(period_unit, 1) if period_unit else 1
    return int(val * mult)


def _parse_days_of_week(text):
    """Parse days of week text into FHIR day codes."""
    if not text:
        return None
    days = []
    for word in re.split(r"[,\s]+", text.lower()):
        if word in myconstants.DAY_TO_FHIR:
            days.append(myconstants.DAY_TO_FHIR[word])
    return days if days else None


def _parse_times_of_day(text):
    """Parse time of day text into 24-hour HH:MM format.

    Handles:
      - "at 15:30" → "15:30"
      - "at 5pm" / "at 5 pm" → "17:00"
      - "at 12 noon" → "12:00"
      - "at 8am" / "at 8 am" → "08:00"

    Strips any "at " prefix — output is just the 24-hour clock value.
    """
    if not text:
        return None
    text_lower = text.lower().strip()
    times = []

    # 24-hour format: HH:MM
    for match in re.finditer(r"(\d{1,2}):(\d{2})", text_lower):
        times.append(f"{int(match.group(1)):02d}:{match.group(2)}")

    # 12-hour format: Xam / Xpm (with optional space)
    for match in re.finditer(r"(\d{1,2})\s*(am|pm)", text_lower):
        hour = int(match.group(1))
        if match.group(2) == "pm" and hour != 12:
            hour += 12
        elif match.group(2) == "am" and hour == 12:
            hour = 0
        times.append(f"{hour:02d}:00")

    # "noon" without am/pm
    if not times and "noon" in text_lower:
        times.append("12:00")

    return times if times else None


# ---------------------------------------------------------------------------
# Builder Functions
# ---------------------------------------------------------------------------


def _build_dose(row):
    """Build the dose[x] FHIR element (STU3: doseQuantity or doseRange directly on Dosage)."""
    dar = {}

    if _has(row, "doseQuantity_clean"):
        val = _first(row, "doseQuantity_value")
        unit = _first(row, "doseQuantity_unit")
        spoonsize = _first(row, "doseQuantity_spoonsize")
        dar["doseQuantity"] = {}
        if val:
            dar["doseQuantity"]["value"] = _num(val)
        if unit:
            _apply_dose_coding(dar["doseQuantity"], unit, spoonsize=spoonsize)

    elif _has(row, "doseRange_clean"):
        low = _first(row, "doseRange_low")
        high = _first(row, "doseRange_high")
        low_unit = _first(row, "doseRange_lowunit")
        high_unit = _first(row, "doseRange_highunit")
        spoonsize = _first(row, "doseRange_spoonsize")
        dar["doseRange"] = {}
        if low:
            dar["doseRange"]["low"] = {"value": _num(low)}
            if low_unit:
                _apply_dose_coding(
                    dar["doseRange"]["low"], low_unit, spoonsize=spoonsize
                )
        if high:
            dar["doseRange"]["high"] = {"value": _num(high)}
            if high_unit:
                _apply_dose_coding(
                    dar["doseRange"]["high"], high_unit, spoonsize=spoonsize
                )

    elif _has(row, "dose_QuantityValueAndMaxOnly_clean"):
        low = _first(row, "doseRange_low")
        high = _first(row, "doseRange_high")
        dar["doseRange"] = {}
        if low:
            dar["doseRange"]["low"] = {"value": _num(low)}
        if high:
            dar["doseRange"]["high"] = {"value": _num(high)}

    elif _has(row, "doseXMilliValueOnly_clean"):
        val = _first(row, "doseXMilli_value")
        milli_val = _first(row, "doseXMilli_valMilli")
        milli_unit = _first(row, "doseXMilli_milli")
        dar["doseQuantity"] = {}
        if milli_val:
            dar["doseQuantity"]["value"] = _num(milli_val)
        elif val:
            dar["doseQuantity"]["value"] = _num(val)
        if milli_unit:
            _apply_dose_coding(dar["doseQuantity"], milli_unit)

    elif _has(row, "dose_QuantityValueOnly_clean"):
        val = _first(row, "doseQuantity_value")
        dar["doseQuantity"] = {}
        if val:
            dar["doseQuantity"]["value"] = _num(val)

    if not dar:
        if _has(row, "milligramValue_clean"):
            val = _first(row, "doseQuantity_value")
            unit = _first(row, "doseQuantity_unit")
            dar["doseQuantity"] = {}
            if val:
                dar["doseQuantity"]["value"] = _num(val)
            if unit:
                _apply_dose_coding(dar["doseQuantity"], unit)

        elif _has(row, "milligramMax_clean"):
            low = _first(row, "doseRange_low")
            high = _first(row, "doseRange_high")
            low_unit = _first(row, "doseRange_lowunit")
            high_unit = _first(row, "doseRange_highunit")
            dar["doseRange"] = {}
            if low:
                dar["doseRange"]["low"] = {"value": _num(low)}
                if low_unit:
                    _apply_dose_coding(dar["doseRange"]["low"], low_unit)
            if high:
                dar["doseRange"]["high"] = {"value": _num(high)}
                if high_unit:
                    _apply_dose_coding(dar["doseRange"]["high"], high_unit)

    return dar if dar else None


def _build_rate(row):
    """Build the rate[x] FHIR element (STU3: rateRatio/rateRange/rateQuantity directly on Dosage)."""
    if _has(row, "rateRatio_clean"):
        num = _first(row, "rateRatio_numerator")
        denom = _first(row, "rateRatio_denominator")
        period_unit = _first(row, "rateRatio_period_unit") or _first(
            row, "rateRatio_periodUnit"
        )
        ucum_pu = (
            myconstants.PERIOD_UNIT_TO_UCUM.get(period_unit, period_unit)
            if period_unit
            else None
        )
        rate = {
            "rateRatio": {
                "numerator": {"value": _num(num)},
                "denominator": {"value": _num(denom) if denom else 1},
            }
        }
        if ucum_pu:
            rate["rateRatio"]["denominator"]["unit"] = period_unit
            rate["rateRatio"]["denominator"]["system"] = "http://unitsofmeasure.org"
            rate["rateRatio"]["denominator"]["code"] = ucum_pu
        return rate

    elif _has(row, "rateRange_clean"):
        low = _first(row, "rateRange_low")
        high = _first(row, "rateRange_high")
        unit = _first(row, "rateRange_special_unit") or _first(row, "rateRange_unit")
        rate = {"rateRange": {}}
        if low:
            rate["rateRange"]["low"] = {"value": _num(low)}
            if unit:
                rate["rateRange"]["low"]["unit"] = unit
        if high:
            rate["rateRange"]["high"] = {"value": _num(high)}
            if unit:
                rate["rateRange"]["high"]["unit"] = unit
        return rate

    elif _has(row, "rateQuantity_clean"):
        val = _first(row, "rateQuantity_value")
        unit = _first(row, "rateQuantity_special_unit") or _first(
            row, "rateQuantity_unit"
        )
        rate = {"rateQuantity": {"value": _num(val)}}
        if unit:
            rate["rateQuantity"]["unit"] = unit
        return rate

    return None


def _build_timing(row):
    """Build the timing FHIR element."""
    repeat = {}

    freq_source = None
    if _has(row, "frequencyBare_clean"):
        freq_source = "frequencyBare"
    elif _has(row, "frequencyWithMethod_clean"):
        freq_source = "frequencyWithMethod"

    if freq_source:
        freq = _first(row, f"{freq_source}_frequency") or _first(row, "frequency_value")
        freq_max = _first(row, f"{freq_source}_frequencyMax") or _first(
            row, "frequency_valueMax"
        )
        period_unit = _first(row, f"{freq_source}_period_unit") or _first(
            row, "frequency_periodUnit"
        )
        freq_num = _num(freq)
        if freq_num is not None:
            repeat["frequency"] = int(freq_num)
        freq_max_num = _num(freq_max)
        if freq_max_num is not None:
            repeat["frequencyMax"] = int(freq_max_num)
        if period_unit:
            ucum = myconstants.PERIOD_UNIT_TO_UCUM.get(period_unit, period_unit)
            if period_unit == "fortnight":
                repeat["period"] = 2
            else:
                repeat.setdefault("period", 1)
            repeat["periodUnit"] = ucum

    if _has(row, "periodElement_clean"):
        period = _first(row, "periodElement_period") or _first(row, "period_value")
        period_max = _first(row, "periodElement_periodMax") or _first(
            row, "period_valueMax"
        )
        period_units = _first(row, "periodElement_period_units") or _first(
            row, "period_units"
        )
        period_num = _num(period)
        if period_num is not None:
            repeat["period"] = int(period_num)
        period_max_num = _num(period_max)
        if period_max_num is not None:
            repeat["periodMax"] = int(period_max_num)
        if period_units:
            repeat["periodUnit"] = myconstants.PERIOD_UNIT_TO_UCUM.get(
                period_units, period_units
            )
        # Default frequency to 1 if no frequency element was captured
        if "frequency" not in repeat:
            period_freq = _first(row, "periodElement_frequency")
            freq_num = _num(period_freq)
            if freq_num is not None:
                repeat["frequency"] = int(freq_num)

    if _has(row, "count_clean"):
        count_val = _first(row, "count_count")
        count_max = _first(row, "count_countMax")
        count_num = _num(count_val)
        if count_num is not None:
            repeat["count"] = int(count_num)
        count_max_num = _num(count_max)
        if count_max_num is not None:
            repeat["countMax"] = int(count_max_num)

    if _has(row, "durationValue_clean"):
        val = _first(row, "durationValue_value") or _first(row, "duration_value")
        units = _first(row, "durationValue_period_units") or _first(
            row, "duration_units"
        )
        if val:
            repeat["duration"] = _num(val)
        if units:
            repeat["durationUnit"] = myconstants.PERIOD_UNIT_TO_UCUM.get(units, units)

    if _has(row, "durationMax_clean"):
        val = _first(row, "durationMax_value") or _first(row, "duration_valueMax")
        units = _first(row, "durationMax_period_units") or _first(row, "duration_units")
        if val:
            repeat["durationMax"] = _num(val)
        if units:
            repeat.setdefault(
                "durationUnit", myconstants.PERIOD_UNIT_TO_UCUM.get(units, units)
            )

    when_source = None
    if _has(row, "whenBare_clean"):
        when_source = "whenBare"
    elif _has(row, "whenWithMethod_clean"):
        when_source = "whenWithMethod"

    if when_source:
        when_text = _first(row, f"{when_source}_when")
        offset = _first(row, f"{when_source}_offset")
        offset_period_unit = _first(row, f"{when_source}_period_unit")
        has_offset = bool(offset)

        category, value = _classify_when(when_text, has_offset=has_offset)
        if category == "timing":
            repeat["when"] = [value]
            if offset:
                offset_minutes = _offset_to_minutes(offset, offset_period_unit)
                if offset_minutes:
                    repeat["offset"] = offset_minutes
        # Categories "additional_snomed" and "additional_text" are handled
        # in _build_additional_instructions — not placed in timing.

    if _has(row, "dayOfWeek_clean"):
        days_text = _first(row, "dayOfWeek_value")
        days = _parse_days_of_week(days_text)
        if days:
            repeat["dayOfWeek"] = days

    if _has(row, "timeOfDay_clean"):
        time_text = _first(row, "timeOfDay_value")
        times = _parse_times_of_day(time_text)
        if times:
            repeat["timeOfDay"] = times

    if _has(row, "boundsDuration_clean"):
        val = _first(row, "boundsDuration_value")
        unit = _first(row, "boundsDuration_unit")
        low = _first(row, "boundsDuration_low")
        high = _first(row, "boundsDuration_high")
        low_unit = _first(row, "boundsDuration_low_unit")
        high_unit = _first(row, "boundsDuration_high_unit")

        if val and unit:
            ucum = myconstants.PERIOD_UNIT_TO_UCUM.get(unit, unit)
            repeat["boundsDuration"] = {
                "value": _num(val),
                "unit": unit,
                "system": "http://unitsofmeasure.org",
                "code": ucum,
            }
        elif low or high:
            raw_unit = low_unit or high_unit
            ucum_unit = (
                myconstants.PERIOD_UNIT_TO_UCUM.get(raw_unit, raw_unit)
                if raw_unit
                else None
            )
            bounds_range = {}
            if low:
                bounds_range["low"] = {"value": _num(low)}
                if raw_unit:
                    bounds_range["low"]["unit"] = raw_unit
                    bounds_range["low"]["system"] = "http://unitsofmeasure.org"
                    bounds_range["low"]["code"] = ucum_unit
            if high:
                bounds_range["high"] = {"value": _num(high)}
                if raw_unit:
                    bounds_range["high"]["unit"] = raw_unit
                    bounds_range["high"]["system"] = "http://unitsofmeasure.org"
                    bounds_range["high"]["code"] = ucum_unit
            repeat["boundsRange"] = bounds_range

    if _has(row, "boundsPeriod_clean"):
        start = _first(row, "boundsPeriod_start")
        end = _first(row, "boundsPeriod_end")
        bp = {}
        if start:
            bp["start"] = start
        if end:
            bp["end"] = end
        if bp:
            repeat["boundsPeriod"] = bp

    if _has(row, "boundsAPeriodStartEnd_clean"):
        start = _first(row, "boundsAPeriodStartEnd_start")
        end = _first(row, "boundsAPeriodStartEnd_end")
        bp = repeat.get("boundsPeriod", {})
        if start:
            bp["start"] = start
        if end:
            bp["end"] = end
        if bp:
            repeat["boundsPeriod"] = bp

    # Ensure period defaults to 1 when periodUnit is set (FHIR requires both)
    if "periodUnit" in repeat and "period" not in repeat:
        repeat["period"] = 1

    timing = {}
    if repeat:
        timing["repeat"] = repeat

    if _has(row, "event_clean"):
        event_val = _first(row, "event_value")
        if event_val:
            timing["event"] = [event_val]

    return timing if timing else None


def _build_method(row):
    """Build the method FHIR element."""
    verb = None
    if _has(row, "methodDirect_clean"):
        verb = _first(row, "methodDirect_verb")
    elif _has(row, "methodPassive_clean"):
        verb = _first(row, "methodPassive_verb")

    if not verb:
        return None

    verb_lower = verb.lower().strip()
    if verb_lower in myconstants.METHOD_TO_SNOMED:
        snomed = myconstants.METHOD_TO_SNOMED[verb_lower]
        return {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": snomed["code"],
                    "display": snomed["display"],
                }
            ]
        }
    return {"text": verb}


def _build_route(row):
    """Build the route FHIR element."""
    if not _has(row, "route_clean"):
        return None

    route_text = row["route_clean"].lower().strip()

    for key, snomed in myconstants.ROUTE_TO_SNOMED.items():
        if key in route_text:
            return {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": snomed["code"],
                        "display": snomed["display"],
                    }
                ]
            }
    return {"text": row["route_clean"]}


def _build_site(row):
    """Build the site FHIR element with SNOMED coding where available."""
    if not _has(row, "site_clean"):
        return None

    site_text = row["site_clean"].lower().strip()

    for keyword, entry in myconstants.SITE_TO_SNOMED.items():
        if keyword in site_text:
            coding = {
                "system": "http://snomed.info/sct",
                "code": entry["code"],
                "display": entry["display"],
            }
            if entry.get("descriptionDisplay"):
                coding["extension"] = [
                    {
                        "url": "https://fhir.hl7.org.uk/STU3/StructureDefinition/Extension-coding-sctdescid",
                        "extension": [
                            {
                                "url": "descriptionDisplay",
                                "valueString": entry["descriptionDisplay"],
                            }
                        ],
                    }
                ]
            return {"coding": [coding]}

    return {"text": row["site_clean"]}


def _build_indication_concept(indication_text):
    """Build a CodeableConcept for an indication phrase using INDICATION_TO_SNOMED.

    Tries a longest-key-first substring match against the lowercased text.
    Returns a coded CodeableConcept if a SNOMED code is found, otherwise a
    text-only CodeableConcept.
    """
    if not indication_text:
        return None
    text_lower = indication_text.lower().strip()
    for key, snomed in myconstants.INDICATION_TO_SNOMED.items():
        if key in text_lower:
            return {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": snomed["code"],
                        "display": snomed["display"],
                    }
                ],
                "text": indication_text,
            }
    return {"text": indication_text}


def _build_as_needed(row):
    """Build the asNeeded FHIR element."""
    if _has(row, "asNeededBoolean_clean"):
        if _has(row, "asNeededCodeableConcept_clean"):
            concept_val = _first(row, "asNeededCodeableConcept_clean")
            return {"asNeededCodeableConcept": _build_indication_concept(concept_val)}
        return {"asNeededBoolean": True}

    if _has(row, "asNeededCodeableConcept_clean"):
        concept_val = _first(row, "asNeededCodeableConcept_clean")
        return {"asNeededCodeableConcept": _build_indication_concept(concept_val)}

    return None


def _build_max_dose(row):
    """Build the maxDose FHIR elements."""
    result = {}

    if _has(row, "maxDosePerPeriod_clean"):
        num_val = _first(row, "maxDosePerPeriod_num_value")
        num_unit = _first(row, "maxDosePerPeriod_num_unit")
        denom_val = _first(row, "maxDosePerPeriod_denom_value")
        denom_unit = _first(row, "maxDosePerPeriod_denom_unit")
        ratio = {}
        if num_val:
            ratio["numerator"] = {"value": _num(num_val)}
            if num_unit:
                coding = _unit_coding(num_unit)
                if coding:
                    ratio["numerator"]["unit"] = coding["display"]
                    if coding["system"]:
                        ratio["numerator"]["system"] = coding["system"]
                    if coding["code"]:
                        ratio["numerator"]["code"] = coding["code"]
        if denom_val or denom_unit:
            ratio["denominator"] = {}
            if denom_val:
                ratio["denominator"]["value"] = _num(denom_val)
            if denom_unit:
                ucum = myconstants.PERIOD_UNIT_TO_UCUM.get(denom_unit, denom_unit)
                ratio["denominator"]["unit"] = denom_unit
                ratio["denominator"]["system"] = "http://unitsofmeasure.org"
                ratio["denominator"]["code"] = ucum
        if ratio:
            result["maxDosePerPeriod"] = ratio

    if _has(row, "maxDosePerAdministration_clean"):
        val = _first(row, "maxDosePerAdministration_value")
        unit = _first(row, "maxDosePerAdministration_unit")
        qty = {}
        if val:
            qty["value"] = _num(val)
        if unit:
            coding = _unit_coding(unit)
            if coding:
                qty["unit"] = coding["display"]
                if coding["system"]:
                    qty["system"] = coding["system"]
                if coding["code"]:
                    qty["code"] = coding["code"]
        if qty:
            result["maxDosePerAdministration"] = qty

    if _has(row, "maxDosePerLifetime_clean"):
        val = _first(row, "maxDosePerLifetime_value")
        unit = _first(row, "maxDosePerLifetime_unit")
        qty = {}
        if val:
            qty["value"] = _num(val)
        if unit:
            coding = _unit_coding(unit)
            if coding:
                qty["unit"] = coding["display"]
                if coding["system"]:
                    qty["system"] = coding["system"]
                if coding["code"]:
                    qty["code"] = coding["code"]
        if qty:
            result["maxDosePerLifetime"] = qty

    return result if result else None


def _build_additional_instructions(row):
    """Build the additionalInstruction FHIR element."""
    instructions = []

    # When elements routed to additionalInstruction (categories 1 and 3)
    when_source = None
    if _has(row, "whenBare_clean"):
        when_source = "whenBare"
    elif _has(row, "whenWithMethod_clean"):
        when_source = "whenWithMethod"

    if when_source:
        when_text = _first(row, f"{when_source}_when")
        offset = _first(row, f"{when_source}_offset")
        has_offset = bool(offset)
        category, value = _classify_when(when_text, has_offset=has_offset)
        if category == "additional_snomed":
            instructions.append(
                {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": value["code"],
                            "display": value["display"],
                        }
                    ]
                }
            )
        elif category == "additional_text":
            instructions.append({"text": str(value)})

    for col_name in (
        "extrasAsDirected_clean",
        "extras_clean",
        "extrasPAUSE_clean",
        "extrasALTER_clean",
        "extras_b_clean",
        "extras_whenoffset",
    ):
        if _has(row, col_name):
            val = _first(row, col_name)
            if val:
                val_lower = str(val).lower().strip()
                snomed = myconstants.EXTRAS_TO_SNOMED.get(val_lower)
                if snomed:
                    instructions.append(
                        {
                            "coding": [
                                {
                                    "system": "http://snomed.info/sct",
                                    "code": snomed["code"],
                                    "display": snomed["display"],
                                }
                            ]
                        }
                    )
                else:
                    instructions.append({"text": str(val)})

    if _has(row, "forElement_clean"):
        # forElement is extracted via reg_extract_and_tag_element (not the spaCy UDF),
        # so forElement_value is never populated — use forElement_clean directly.
        for_val = _first(row, "forElement_clean")
        if for_val:
            val_lower = str(for_val).lower().strip()
            snomed = myconstants.EXTRAS_TO_SNOMED.get(val_lower)
            if snomed:
                instructions.append(
                    {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": snomed["code"],
                                "display": snomed["display"],
                            }
                        ]
                    }
                )
            else:
                instructions.append({"text": for_val})

    return instructions if instructions else None


def _build_patient_instruction(row):
    """Build patientInstruction for milligram clarifications."""
    parts = []

    if _has(row, "milligramValue_clean") and (
        _has(row, "doseQuantity_clean")
        or _has(row, "dose_QuantityValueOnly_clean")
        or _has(row, "doseRange_clean")
    ):
        val = _first(row, "milligramValue_value")
        unit = _first(row, "milligramValue_milligram_units")
        if val:
            parts.append(f"({val} {unit or 'mg'})")

    if _has(row, "milligramMax_clean") and (
        _has(row, "doseQuantity_clean")
        or _has(row, "dose_QuantityValueOnly_clean")
        or _has(row, "doseRange_clean")
    ):
        low = _first(row, "milligramMax_value")
        high = _first(row, "milligramMax_valueMax")
        unit = _first(row, "milligramMax_milligram_units")
        if low and high:
            parts.append(f"({low}-{high} {unit or 'mg'})")
        elif low:
            parts.append(f"({low} {unit or 'mg'})")

    return " ".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Row Assembler
# ---------------------------------------------------------------------------


def row_to_fhir_dosage(row):
    """Convert a pipeline row to a FHIR STU3 Dosage JSON string.

    dose[x] and rate[x] are placed directly on the Dosage object
    (i.e. doseQuantity/doseRange/rateRatio/rateRange/rateQuantity at top level).
    """
    dosage = {"text": row.get("dosage", "")}

    dose = _build_dose(row)
    rate = _build_rate(row)
    timing = _build_timing(row)
    method = _build_method(row)
    route_val = _build_route(row)
    site_val = _build_site(row)
    as_needed = _build_as_needed(row)
    max_dose = _build_max_dose(row)
    additional = _build_additional_instructions(row)
    patient_instruction = _build_patient_instruction(row)

    if timing:
        dosage["timing"] = timing

    if dose:
        dosage.update(dose)
    if rate:
        dosage.update(rate)
    if method:
        dosage["method"] = method
    if route_val:
        dosage["route"] = route_val
    if site_val:
        dosage["site"] = site_val
    if as_needed is not None:
        dosage.update(as_needed)
    if max_dose:
        dosage.update(max_dose)
    if additional:
        dosage["additionalInstruction"] = additional
    if patient_instruction:
        dosage["patientInstruction"] = patient_instruction

    return json.dumps(dosage, ensure_ascii=False)
