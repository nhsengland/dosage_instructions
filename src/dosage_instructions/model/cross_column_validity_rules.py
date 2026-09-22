"""
Cross-column validity rules for dosage instruction rows.

These rules compare values across multiple resolved columns to detect
logically inconsistent or implausible combinations that passed individual
element extraction and numeric validation.

Rows that fail any rule are excluded (mapped=False) with the failing rule
numbers recorded in the `cross_column_fail` column.

Rule numbering (CC = cross-column, VC = value-specific constraints):
    CC1  - Fortnight must be singular
    CC2  - Dose unit singular/plural mismatch
    CC3  - Milligram range units incompatible or inverted
    CC4  - Max dose less than regular dose
    CC5  - Period÷frequency != timing cycle (dayOfWeek/when/timeOfDay conflict);
           also count > 1 with singular when; count == 1 with multi-per-day when
    CC6  - Singular timing (dayOfWeek/when/timeOfDay) without frequency/period
    CC7  - Period exceeds bounds duration
    CC8  - Event date with period > 1 day
    CC9  - Event + boundsDuration clash; or count + boundsDuration clash
    CC10 - Frequency ≤1/day with multi-per-day when (e.g. "1 a day with meals")
    CC11 - Duration > 1 hour with specific timing point (when/timeOfDay)
    CC12 - periodElement (implied frequency=1) with dose != 1, null, or range
    CC13 - "each/every <time-of-day>" when contradicts non-day period unit
    VC1  - Period or duration exceeds 365 days
    VC2  - Dose implausibly high for unit-dose forms
    VC3  - Frequency exceeds 12 per day
"""

import re

import pandas as pd
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.functions import pandas_udf
from pyspark.sql.types import StringType

import dosage_instructions.model.constants as myconstants

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _unwrap(val):
    """Unwrap a value from common Spark UDF serialization artifacts.

    Handles:
    - None → None
    - Python list → first element (or None if empty)
    - Stringified list e.g. "[1.25]", "['mg']" → inner value
    - "null", "none", "[]" strings → None
    """
    if val is None:
        return None
    if isinstance(val, (list,)):
        return val[0] if val else None
    # Handle stringified arrays from Spark struct → pandas UDF serialization
    s = str(val).strip()
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        # Strip surrounding quotes: 'mg' or "mg"
        if len(inner) >= 2 and (
            (inner[0] == "'" and inner[-1] == "'")
            or (inner[0] == '"' and inner[-1] == '"')
        ):
            inner = inner[1:-1]
        return inner if inner else None
    return val


def _num(val):
    """Safely convert a value to float, returning None on failure."""
    val = _unwrap(val)
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _str(val):
    """Safely extract a string value."""
    val = _unwrap(val)
    if val is None:
        return None
    s = str(val).strip().lower()
    if not s or s in ("null", "none"):
        return None
    return s


# ---------------------------------------------------------------------------
# Individual Rule Functions
#
# Each returns a reason string if the rule FAILS, or None if it passes.
# ---------------------------------------------------------------------------


def rule_cc1_fortnight_singular(row) -> str | None:
    """CC1: Fortnight must only pair with period value of 1 (or no period value)."""
    # Check periodElement
    period_unit = _str(row.get("periodElement_period_units"))
    period_val = _num(row.get("periodElement_period"))
    if period_unit == "fortnight" and period_val is not None and period_val != 1:
        return "fortnight must be singular"

    # Check frequency period_unit (frequencyBare / frequencyWithMethod)
    for prefix in ("frequencyBare", "frequencyWithMethod"):
        freq_unit = _str(row.get(f"{prefix}_period_unit"))
        if freq_unit == "fortnight":
            # For frequency, the period is implicitly 1 (e.g. "twice a fortnight")
            # so we only flag if there's an explicit period > 1
            freq_period = _num(row.get(f"{prefix}_period"))
            if freq_period is not None and freq_period != 1:
                return "fortnight must be singular"

    return None


def rule_cc2_dose_unit_mismatch(row) -> str | None:
    """CC2: Dose value must agree with unit singular/plural form.

    - value == 1 → unit must be singular (not "1 tablets")
    - value > 1 → unit must be plural (not "3 tablet")

    Units containing "(s)" are deliberately ambiguous (valid for any quantity)
    and are skipped.
    """
    # Check doseQuantity
    dose_val = _num(row.get("doseQuantity_quantity"))
    dose_unit = _str(row.get("doseQuantity_units"))

    if dose_val is not None and dose_unit is not None and "(s)" not in dose_unit:
        if dose_unit in myconstants.ALL_SINGULAR or dose_unit in myconstants.ALL_PLURAL:
            if dose_val == 1 and dose_unit in myconstants.ALL_PLURAL:
                return "singular/plural mismatch: 1 with plural unit"
            if dose_val > 1 and dose_unit in myconstants.ALL_SINGULAR:
                return "singular/plural mismatch: >1 with singular unit"

    # Check doseRange high
    range_high = _num(row.get("doseRange_high"))
    range_unit = _str(row.get("doseRange_units"))

    if range_high is not None and range_unit is not None and "(s)" not in range_unit:
        if (
            range_unit in myconstants.ALL_SINGULAR
            or range_unit in myconstants.ALL_PLURAL
        ):
            if range_high == 1 and range_unit in myconstants.ALL_PLURAL:
                return "singular/plural mismatch: 1 with plural unit"
            if range_high > 1 and range_unit in myconstants.ALL_SINGULAR:
                return "singular/plural mismatch: >1 with singular unit"

    return None


def rule_cc5_freq_period_vs_timing(row) -> str | None:
    """CC5: period÷frequency (dose interval in days) must equal the timing cycle.

    Converts period_in_days ÷ frequency to get the interval between individual
    doses, then compares against the implied timing cycle:
    - dayOfWeek → 7 days
    - when (specific point: night, morning, bedtime etc.) → 1 day
    - timeOfDay → 1 day

    Generic when values (food, meals, empty stomach) are not timing points — they
    don't imply a cycle, so this rule does not apply to them.

    Uses frequencyMax when present (whether or not frequency is also set), since
    "up to 3 times a day at night" and "1 to 3 times a day at night" are both
    nonsensical — if the max doesn't fit the timing cycle, the instruction is broken.

    E.g. "once a week on mondays" → 7÷1=7, timing=7 → FINE
         "twice a fortnight on mondays" → 14÷2=7, timing=7 → FINE
         "twice a week on mondays" → 7÷2=3.5, timing=7 → EXCLUDE
         "once a day at night" → 1÷1=1, timing=1 → FINE
         "twice a day at night" → 1÷2=0.5, timing=1 → EXCLUDE
         "7 times every day on monday" → 1÷7≈0.14, timing=7 → EXCLUDE

    Also handles count (total administrations without a period):
    - count with timeOfDay or singular when must be 1, otherwise ambiguous
    - count with dayOfWeek is allowed (e.g. "2 times on mondays" is fine)
    - count == 1 with multi-per-day when (e.g. "with meals") is contradictory
    - count > 1 with multi-per-day when is fine (consistent)

    E.g. "once at night" → count=1, timing=daily → FINE
         "3 times at night" → count=3, timing=daily → EXCLUDE
         "once at 8am" → count=1, timing=daily → FINE
         "3 times at 8am" → count=3, timing=daily → EXCLUDE
         "2 times on mondays" → count=2, timing=weekly → FINE (allowed)
         "1 time with meals" → count=1, multi-per-day when → EXCLUDE
         "3 times with meals" → count=3, multi-per-day when → FINE
    """
    # --- Sub-rule: count with timing ---
    # count has no period, so we can't compute an interval. Instead:
    # if timing is daily (timeOfDay or singular when), count must be 1.
    # dayOfWeek timing is exempt — "2 times on mondays" is acceptable.
    count_val = _num(row.get("count_count"))
    if count_val is not None:
        # Only apply if no frequency/period is also present (avoid double-fire)
        has_freq = False
        for prefix in ("frequencyBare", "frequencyWithMethod"):
            if (
                _num(row.get(f"{prefix}_frequency")) is not None
                or _num(row.get(f"{prefix}_frequencyMax")) is not None
            ):
                has_freq = True
                break
        if not has_freq and _num(row.get("periodElement_frequency")) is not None:
            has_freq = True

        if not has_freq:
            # Check if timing is daily (timeOfDay or specific singular when)
            time_val = _str(row.get("timeOfDay_value"))
            when_val = _str(row.get("whenBare_when")) or _str(
                row.get("whenWithMethod_when")
            )

            has_daily_timing = False
            if time_val is not None:
                has_daily_timing = True
            elif (
                when_val is not None
                and _is_specific_timing(when_val)
                and not _is_plural_timing(when_val)
            ):
                has_daily_timing = True

            if has_daily_timing and count_val > 1:
                return f"count ({int(count_val)}) > 1 with daily timing point"

            # Check multi-per-day when (e.g. "with meals") — count must be > 1
            # because the plural timing implies multiple daily occurrences.
            if (
                when_val is not None
                and _is_multi_per_day_when(when_val)
                and count_val <= 1
            ):
                return f"count ({int(count_val)}) with multi-per-day when '{when_val}'"

            # Return None — count with dayOfWeek or plural when is fine
            return None

    # --- Main sub-rule: frequency/period with timing ---
    # Get frequency and period — prefer frequencyMax when present
    freq_val = None
    period_unit = None
    for prefix in ("frequencyBare", "frequencyWithMethod"):
        # Use frequencyMax if present, otherwise frequency
        v = _num(row.get(f"{prefix}_frequencyMax"))
        if v is None:
            v = _num(row.get(f"{prefix}_frequency"))
        if v is not None:
            freq_val = v
            period_unit = _str(row.get(f"{prefix}_period_unit"))
            break

    # Also check periodElement (which defaults frequency to 1)
    if freq_val is None:
        freq_val = _num(row.get("periodElement_frequency"))
        if freq_val is not None:
            period_unit = _str(row.get("periodElement_period_units"))

    if freq_val is None or period_unit is None:
        return None  # No frequency/period — CC6 handles this case

    period_val = None
    for col in (
        "periodElement_period",
        "frequencyBare_period",
        "frequencyWithMethod_period",
    ):
        v = _num(row.get(col))
        if v is not None:
            period_val = v
            break
    if period_val is None:
        period_val = 1

    # Convert period to days
    period_in_days = period_val * myconstants.PERIOD_UNIT_TO_DAYS.get(period_unit, 1)

    # Dose interval = period ÷ frequency
    dose_interval = period_in_days / freq_val

    # Determine timing cycle from dayOfWeek / when / timeOfDay
    timing = _get_timing_cycle(row)
    if timing is None:
        return None  # No timing point present, rule doesn't apply

    if dose_interval != timing:
        return f"period÷freq ({period_in_days}÷{freq_val}={dose_interval}) != timing cycle ({timing})"

    return None


def rule_cc6_singular_timing_without_frequency(row) -> str | None:
    """CC6: Singular timing (dayOfWeek/when/timeOfDay) without frequency/period → EXCLUDE.

    Plural forms (mondays, nights, bedtimes) imply repeating and are allowed without frequency.
    Singular forms (monday, night, bedtime) without frequency are incomplete — can't determine
    the dosing pattern.

    Count does NOT suppress this rule — "2 times on monday" (singular) is still
    ambiguous because we can't tell if it's repeating without a period.

    E.g. "take on monday" → EXCLUDE (singular, no freq)
         "take on mondays" → FINE (plural implies repeating)
         "take at night" → EXCLUDE (singular, no freq)
         "take at nights" → FINE (plural)
         "take 2 times on monday" → EXCLUDE (singular dayOfWeek, no period)
    """
    # Check if any frequency/period is present
    has_freq = False
    for col in (
        "frequencyBare_frequency",
        "frequencyWithMethod_frequency",
        "periodElement_period_units",
    ):
        if _str(row.get(col)) is not None or _num(row.get(col)) is not None:
            has_freq = True
            break

    if has_freq:
        return None  # CC5 handles this case

    # Check dayOfWeek
    day_val = _str(row.get("dayOfWeek_value"))
    if day_val is not None:
        if not _is_plural_timing(day_val):
            return "singular dayOfWeek without frequency/period"

    # Check when
    when_val = _str(row.get("whenBare_when")) or _str(row.get("whenWithMethod_when"))
    if when_val is not None and _is_specific_timing(when_val):
        if not _is_plural_timing(when_val):
            return "singular when without frequency/period"

    # Check timeOfDay
    time_val = _str(row.get("timeOfDay_value"))
    if time_val is not None:
        # timeOfDay is always singular (e.g. "at 8am") — no plural form
        return "singular timeOfDay without frequency/period"

    return None


# ---------------------------------------------------------------------------
# Timing helpers for Rules 9 and 10
# ---------------------------------------------------------------------------


def _is_specific_timing(when_text: str) -> bool:
    """Return True if the when text refers to a specific point in the day."""
    for specific in myconstants.SPECIFIC_WHEN_KEYWORDS:
        if specific in when_text:
            return True
    return False


def _is_multi_per_day_when(when_text: str) -> bool:
    """Return True if the when text implies multiple occurrences per day."""
    for keyword in myconstants.MULTI_PER_DAY_WHEN_KEYWORDS:
        if keyword in when_text:
            return True
    return False


def _is_plural_timing(text: str) -> bool:
    """Return True if the timing text is plural (e.g. mondays, nights, bedtimes)."""
    # Check if any word ends with 's' suggesting plural
    words = text.strip().split()
    last_word = words[-1] if words else ""
    return last_word.endswith("s") and last_word not in (
        "this",
        "was",
        "is",
        "as",
        "has",
        "plus",
    )


def _get_timing_cycle(row) -> float | None:
    """Determine the timing cycle in days from dayOfWeek/when/timeOfDay.

    Returns:
        7 if dayOfWeek is present
        1 if a specific when or timeOfDay is present
        None if no timing point or only generic when (food, meals)
    """
    # dayOfWeek → weekly cycle
    day_val = _str(row.get("dayOfWeek_value"))
    if day_val is not None:
        return 7

    # Specific when → daily cycle
    when_val = _str(row.get("whenBare_when")) or _str(row.get("whenWithMethod_when"))
    if when_val is not None and _is_specific_timing(when_val):
        return 1

    # timeOfDay → daily cycle
    time_val = _str(row.get("timeOfDay_value"))
    if time_val is not None:
        return 1

    return None


def rule_vc1_exceeds_365_days(row) -> str | None:
    """VC1: Period or duration value > 365 when unit is day/days is implausible."""
    checks = [
        ("periodElement_period", "periodElement_period_units"),
        ("periodElement_periodMax", "periodElement_period_units"),
        ("durationValue_value", "durationValue_period_units"),
        ("durationMax_value", "durationMax_period_units"),
        ("boundsDuration_value", "boundsDuration_unit"),
        ("boundsDuration_valueMax", "boundsDuration_unit"),
    ]

    for val_field, unit_field in checks:
        val = _num(row.get(val_field))
        unit = _str(row.get(unit_field))
        if val is not None and unit in ("day", "days") and val > 365:
            return f"value exceeds 365 days ({val_field}={val})"

    return None


def rule_vc2_dose_implausibly_high(row) -> str | None:
    """VC2: Dose > 10 for unit-dose forms (tablets, capsules, puffs etc.) is implausible."""
    dose_val = _num(row.get("doseQuantity_quantity"))
    dose_unit = _str(row.get("doseQuantity_units"))

    if (
        dose_val is not None
        and dose_val > 10
        and dose_unit in myconstants.UNIT_DOSE_FORMS
    ):
        return f"dose implausibly high: {dose_val} {dose_unit}"

    # Also check range high
    range_high = _num(row.get("doseRange_high"))
    range_unit = _str(row.get("doseRange_units"))

    if (
        range_high is not None
        and range_high > 10
        and range_unit in myconstants.UNIT_DOSE_FORMS
    ):
        return f"dose implausibly high: {range_high} {range_unit}"

    return None


def rule_vc3_frequency_exceeds_max(row) -> str | None:
    """VC3: Frequency > 12 per day is implausible."""
    for prefix in ("frequencyBare", "frequencyWithMethod"):
        freq_val = _num(row.get(f"{prefix}_frequency"))
        freq_unit = _str(row.get(f"{prefix}_period_unit"))

        if freq_val is not None and freq_unit in ("day", "days") and freq_val > 12:
            return f"frequency exceeds 12 per day ({freq_val})"

    return None


def _units_comparable(u1, u2):
    """Check if two units belong to the same measurement category."""
    if u1 == u2:
        return True
    if u1 in myconstants.MASS_UNITS and u2 in myconstants.MASS_UNITS:
        return True
    if u1 in myconstants.VOLUME_UNITS and u2 in myconstants.VOLUME_UNITS:
        return True
    return False


def rule_cc3_milligram_range_consistency(row) -> str | None:
    """CC3: When milligramMax has both low_unit and high_unit (pattern2), validate consistency.

    Either:
    - Units must be the same, OR
    - If units differ but are in the same category (both mass or both volume),
      the low total must be <= high total when converted to a common base.

    E.g. 500mg to 1g is valid (500000 < 1000000 micrograms)
         2g to 500mg is invalid (2000000 > 500000 micrograms)
    """
    low_val = _num(row.get("milligramMax_value"))
    high_val = _num(row.get("milligramMax_valueMax"))
    low_unit = _str(row.get("milligramMax_low_unit"))
    high_unit = _str(row.get("milligramMax_milligram_units"))

    # Only applies when both values are present
    if low_val is None or high_val is None:
        return None
    if high_unit is None:
        return None

    # If low_unit is absent (pattern1) or same as high_unit, do raw numeric check
    if low_unit is None or low_unit == high_unit:
        if low_val > high_val:
            return f"milligram range inverted: {low_val} > {high_val} ({high_unit})"
        return None

    # Units differ — check if they're comparable
    if not _units_comparable(low_unit, high_unit):
        return f"milligram range units incompatible: {low_unit} vs {high_unit}"

    # Convert to common base and check low <= high
    low_factor = myconstants.UNIT_TO_MICROGRAMS.get(low_unit)
    high_factor = myconstants.UNIT_TO_MICROGRAMS.get(high_unit)

    if low_factor is None or high_factor is None:
        return None  # Unknown unit, can't validate

    low_total = low_val * low_factor
    high_total = high_val * high_factor
    if low_total > high_total:
        return f"milligram range inverted: {low_val}{low_unit} > {high_val}{high_unit}"

    return None


def rule_cc4_max_dose_less_than_regular(row) -> str | None:
    """CC4: Max dose per period numerator should not be less than regular dose quantity."""
    max_num = _num(row.get("maxDosePerPeriod_num_value"))
    if max_num is None:
        return None

    # Compare against doseQuantity
    dose_val = _num(row.get("doseQuantity_quantity"))
    if dose_val is not None and max_num < dose_val:
        return f"max dose ({max_num}) less than regular dose ({dose_val})"

    # Compare against doseRange high
    range_high = _num(row.get("doseRange_high"))
    if range_high is not None and max_num < range_high:
        return f"max dose ({max_num}) less than dose range high ({range_high})"

    return None


def rule_cc7_freq_period_exceeds_duration(row) -> str | None:
    """CC7: period (in days) must not exceed boundsDuration (in days).

    If the dosing period is longer than the treatment course, the instruction
    is nonsensical — e.g. "once a week for 5 days" (period=7 > duration=5).

    Only the period matters, not frequency — "12 times a day for 5 days" is
    fine because the period is 1 day, well within the 5-day course.

    Uses strict > so borderline cases like "once a week for 7 days" are allowed.
    When boundsDuration has a range (value to valueMax), the max is used.
    """
    # Get period unit and value
    period_unit = None
    period_val = None
    for prefix in ("frequencyBare", "frequencyWithMethod"):
        pu = _str(row.get(f"{prefix}_period_unit"))
        if pu is not None:
            period_unit = pu
            period_val = _num(row.get(f"{prefix}_period")) or 1
            break

    if period_unit is None:
        pu = _str(row.get("periodElement_period_units"))
        if pu is not None:
            period_unit = pu
            period_val = _num(row.get("periodElement_period")) or 1

    if period_unit is None:
        return None  # No period to check

    # Convert period to days
    period_in_days = period_val * myconstants.PERIOD_UNIT_TO_DAYS.get(period_unit, 1)

    # Get boundsDuration in days — use valueMax if available, else value
    duration_val = _num(row.get("boundsDuration_valueMax")) or _num(
        row.get("boundsDuration_value")
    )
    duration_unit = _str(row.get("boundsDuration_unit"))

    if duration_val is None or duration_unit is None:
        return None  # No bounds duration present

    duration_days = duration_val * myconstants.PERIOD_UNIT_TO_DAYS.get(duration_unit, 1)

    if period_in_days > duration_days:
        return (
            f"period ({period_in_days} days) > bounds duration ({duration_days} days)"
        )

    return None


def rule_cc8_event_with_period_gt_1_day(row) -> str | None:
    """CC8: Event date with a period > 1 day is nonsensical.

    An event is a specific date (e.g. "on 2.12.2024") — a single day.
    Frequency within that day is fine (e.g. "3 times a day on 2.12.2024"),
    but a period longer than 1 day makes no sense with a single date.

    E.g. "once every 3 days on 2.12.2024" → period = 3 days > 1 → EXCLUDE
         "once a week on 2.12.2024" → period = 7 days > 1 → EXCLUDE
         "3 times a day on 2.12.2024" → period = 1 day → FINE
         "every 4 hours on 2.12.2024" → period = 1/6 day → FINE
    """
    event_val = _str(row.get("event_value"))
    if event_val is None:
        return None

    # Get the period unit and value
    period_unit = None
    period_val = None

    for prefix in ("frequencyBare", "frequencyWithMethod"):
        pu = _str(row.get(f"{prefix}_period_unit"))
        if pu is not None:
            period_unit = pu
            period_val = _num(row.get(f"{prefix}_period")) or 1
            break

    if period_unit is None:
        pu = _str(row.get("periodElement_period_units"))
        if pu is not None:
            period_unit = pu
            period_val = _num(row.get("periodElement_period")) or 1

    if period_unit is None:
        return None  # No period present, nothing to check

    period_in_days = period_val * myconstants.PERIOD_UNIT_TO_DAYS.get(period_unit, 1)

    if period_in_days > 1:
        return f"event date with period > 1 day ({period_in_days} days)"

    return None


def rule_cc9_event_or_count_with_bounds_duration(row) -> str | None:
    """CC9: Event + boundsDuration or count + boundsDuration → EXCLUDE.

    Two sub-rules:

    1. Event + boundsDuration: An event is a specific date (e.g. "on 2.12.2024").
       Adding a duration ("for 5 days") contradicts a single-date event — you can't
       have both a fixed date and a multi-day course.

    2. Count + boundsDuration: Count is a total number of administrations (e.g.
       "3 times"). Adding a duration makes the instruction ambiguous — "take 3 times
       for 5 days" could mean 3 total over 5 days, or 3/day for 5 days.

    E.g. "on 2.12.2024 for 5 days" → event + duration → EXCLUDE
         "take 3 times for 5 days" → count + duration → EXCLUDE
         "take once for 5 days" → count + duration → EXCLUDE
         "take 3 times a day for 5 days" → frequency + duration → FINE (CC7 handles)
         "as required for 5 days" → PRN + duration → FINE
    """
    # Check if boundsDuration is present
    duration_val = _num(row.get("boundsDuration_value"))
    if duration_val is None:
        return None

    # Sub-rule 1: event + boundsDuration
    event_val = _str(row.get("event_value"))
    if event_val is not None:
        return "event date with boundsDuration"

    # Sub-rule 2: count + boundsDuration
    count_val = _num(row.get("count_count"))
    if count_val is not None:
        return f"count ({int(count_val)}) with boundsDuration"

    return None


def rule_cc11_duration_gt_1_hour_with_timing_point(row) -> str | None:
    """CC11: Duration > 1 hour with a when or timeOfDay value → EXCLUDE.

    Duration (durationValue/durationMax) describes how long a single administration
    takes (e.g. "infuse over 2 hours"). If the duration exceeds 1 hour, pairing it
    with a specific timing point is contradictory — the action spans longer than a
    single moment in the day.

    E.g. "over 2 hours at 8am" → duration=2h > 1h, has timeOfDay → EXCLUDE
         "over 3 days at night" → duration=3d > 1h, has when → EXCLUDE
         "over 30 minutes at 8am" → duration=0.5h ≤ 1h → FINE
         "over 1 hour at 8am" → duration=1h ≤ 1h → FINE
         "over 2 hours every day" → no when/timeOfDay → FINE
    """
    # Gather duration values (check both durationValue and durationMax)
    duration_checks = [
        ("durationValue_value", "durationValue_period_units"),
        ("durationMax_value", "durationMax_period_units"),
    ]

    max_duration_hours = None
    for val_field, unit_field in duration_checks:
        val = _num(row.get(val_field))
        unit = _str(row.get(unit_field))
        if val is None or unit is None:
            continue
        # Convert to hours
        days = val * myconstants.PERIOD_UNIT_TO_DAYS.get(unit, 1)
        hours = days * 24
        if max_duration_hours is None or hours > max_duration_hours:
            max_duration_hours = hours

    if max_duration_hours is None or max_duration_hours <= 1:
        return None  # No duration or ≤ 1 hour — fine

    # Check if a timing point is present
    time_val = _str(row.get("timeOfDay_value"))
    when_val = _str(row.get("whenBare_when")) or _str(row.get("whenWithMethod_when"))

    if time_val is not None:
        return f"duration ({max_duration_hours}h) > 1 hour with timeOfDay"
    if when_val is not None and _is_specific_timing(when_val):
        return f"duration ({max_duration_hours}h) > 1 hour with when '{when_val}'"

    return None


def rule_cc10_freq_leq_1_with_multi_per_day_when(row) -> str | None:
    """CC10: Frequency ≤1/day contradicts a multi-per-day when value.

    When values like "with meals", "after eating", "each meal", "bowel movements"
    imply the medication is taken multiple times per day (at each occurrence).
    A frequency of 1/day (or less) contradicts this.

    E.g. "1 a day with meals" → freq=1/day, when implies ≥2/day → EXCLUDE
         "once a day after eating" → freq=1/day, when implies ≥2/day → EXCLUDE
         "3 times a day with meals" → freq=3/day → FINE
         "once a day with food" → "food" (singular) is generic, not multi → FINE
         "once a day after breakfast" → breakfast is 1/day → FINE (not multi)

    Does not apply when no frequency/period is present (CC6 handles that).
    """
    # Get the when value
    when_val = _str(row.get("whenBare_when")) or _str(row.get("whenWithMethod_when"))
    if when_val is None:
        return None

    # Check if the when value implies multiple per day
    if not _is_multi_per_day_when(when_val):
        return None

    # Get frequency and period to compute doses per day
    freq_val = None
    period_unit = None
    for prefix in ("frequencyBare", "frequencyWithMethod"):
        v = _num(row.get(f"{prefix}_frequency"))
        if v is not None:
            freq_val = v
            period_unit = _str(row.get(f"{prefix}_period_unit"))
            break

    if freq_val is None:
        freq_val = _num(row.get("periodElement_frequency"))
        if freq_val is not None:
            period_unit = _str(row.get("periodElement_period_units"))

    if freq_val is None or period_unit is None:
        return None  # No frequency present — other rules handle this

    period_val = None
    for col in (
        "periodElement_period",
        "frequencyBare_period",
        "frequencyWithMethod_period",
    ):
        v = _num(row.get(col))
        if v is not None:
            period_val = v
            break
    if period_val is None:
        period_val = 1

    # Convert to doses per day
    period_in_days = period_val * myconstants.PERIOD_UNIT_TO_DAYS.get(period_unit, 1)
    if period_in_days == 0:
        return None
    doses_per_day = freq_val / period_in_days

    if doses_per_day <= 1:
        return f"frequency ({freq_val}/{period_val} {period_unit} = {doses_per_day}/day) with multi-per-day when '{when_val}'"

    return None


# ---------------------------------------------------------------------------
# Rule Registry
# ---------------------------------------------------------------------------


def rule_cc12_period_without_single_dose(row) -> str | None:
    """CC12: periodElement (implied frequency) requires dose == IMPLIED_ONLY_IF_DOSE.

    periodElement captures patterns like "every day", "every 4 hours" where no
    explicit frequency count is stated — the model assumes frequency=IMPLIED_FREQUENCY.
    See "Implied frequency rule" in constants.py for the full explanation of how
    the same rule is applied in two places (PeriodElement and _infer_period_for_daily_when).

    This assumption is only valid when the dose is exactly IMPLIED_ONLY_IF_DOSE
    (one tablet, one puff etc.).

    If dose is absent, >IMPLIED_ONLY_IF_DOSE, or a range, the assumption is unsafe
    and the row is excluded.

    Does NOT apply when an explicit frequency element (frequencyBare/frequencyWithMethod)
    is also present — in that case frequency is known, not assumed.

    E.g. "1 tablet every day" → dose=1, periodElement → FINE
         "2 tablets every day" → dose=2, periodElement → EXCLUDE
         "1-2 tablets every day" → range, periodElement → EXCLUDE
         "every day" (no dose) → null dose, periodElement → EXCLUDE
         "2 tablets twice a day" → has frequencyBare, not periodElement → FINE (rule N/A)
         "2 tablets 3 times a day every day" → has frequencyBare → FINE (rule N/A)
    """
    # Only applies when periodElement is the timing source
    if _str(row.get("periodElement_period_units")) is None:
        return None

    # Skip if an explicit frequency element is present (frequency is not assumed)
    for prefix in ("frequencyBare", "frequencyWithMethod"):
        if _num(row.get(f"{prefix}_frequency")) is not None:
            return None

    # Check doseQuantity (element_split: quantity, units, spoonsize)
    dose_val = _num(row.get("doseQuantity_quantity"))
    if dose_val is not None:
        if dose_val == myconstants.IMPLIED_ONLY_IF_DOSE:
            return None  # Valid: single dose with period
        return f"periodElement with dose != {myconstants.IMPLIED_ONLY_IF_DOSE} (doseQuantity={dose_val})"

    # Check dose_QuantityValueOnly (element_split: value)
    value_only = _num(row.get("dose_QuantityValueOnly_value"))
    if value_only is not None:
        if value_only == myconstants.IMPLIED_ONLY_IF_DOSE:
            return None  # Valid: single dose with period
        return f"periodElement with dose != {myconstants.IMPLIED_ONLY_IF_DOSE} (dose_QuantityValueOnly={value_only})"

    # If dose is a range, exclude
    if (
        _num(row.get("doseRange_low")) is not None
        or _num(row.get("doseRange_high")) is not None
    ):
        return "periodElement with dose range"

    if _num(row.get("dose_QuantityValueAndMaxOnly_value")) is not None:
        return "periodElement with dose range (ValueAndMax)"

    # No dose captured at all
    return "periodElement with no dose"


_DAILY_WHEN_WORDS = frozenset(
    {"morning", "afternoon", "evening", "night", "bedtime", "noon", "waking"}
)


def rule_cc13_each_every_when_with_non_day_period(row) -> str | None:
    """CC13: "each/every <time-of-day>" when contradicts non-day period.

    If the when element was originally "each morning", "every night", etc., the
    instruction implies a daily rhythm. If an explicit period is present and it's
    NOT "day" (e.g. "every week each morning"), the instruction is ambiguous.

    We detect this via whenBare_captured / whenWithMethod_captured which preserve
    the raw matched text before normalisation stripped "each/every".

    E.g. "take 1 every week each morning" → period=week, when=each morning → EXCLUDE
         "take 1 each morning"            → inferred period=day → FINE
         "take 1 a day each morning"      → period=day → FINE
    """

    _each_every_re = re.compile(r"^(each|every)\s+(\w+)$")

    # Check whenBare_captured first, then whenWithMethod_captured
    when_captured = None
    for col_name in ("whenBare_captured", "whenWithMethod_captured"):
        val = _str(row.get(col_name))
        if val:
            when_captured = val
            break

    if when_captured is None:
        return None

    m = _each_every_re.match(when_captured)
    if not m:
        return None

    time_word = m.group(2)
    if time_word not in _DAILY_WHEN_WORDS:
        return None

    # Check if period_units is present and NOT day
    period_units = _str(row.get("periodElement_period_units"))
    if period_units is None:
        return None  # No period — inference handles it or it's excluded elsewhere

    if period_units == "day":
        return None  # Consistent: daily period with daily when

    return f"'each/every {time_word}' (daily) contradicts period unit '{period_units}'"


ALL_RULES = [
    ("CC1", rule_cc1_fortnight_singular),
    ("CC2", rule_cc2_dose_unit_mismatch),
    ("CC3", rule_cc3_milligram_range_consistency),
    ("CC4", rule_cc4_max_dose_less_than_regular),
    ("CC5", rule_cc5_freq_period_vs_timing),
    ("CC6", rule_cc6_singular_timing_without_frequency),
    ("CC7", rule_cc7_freq_period_exceeds_duration),
    ("CC8", rule_cc8_event_with_period_gt_1_day),
    ("CC9", rule_cc9_event_or_count_with_bounds_duration),
    ("CC10", rule_cc10_freq_leq_1_with_multi_per_day_when),
    ("CC11", rule_cc11_duration_gt_1_hour_with_timing_point),
    ("CC12", rule_cc12_period_without_single_dose),
    ("CC13", rule_cc13_each_every_when_with_non_day_period),
    # ── Value-specific constraints (not cross-column, but kept here for now) ──
    ("VC1", rule_vc1_exceeds_365_days),
    ("VC2", rule_vc2_dose_implausibly_high),
    ("VC3", rule_vc3_frequency_exceeds_max),
]


# ---------------------------------------------------------------------------
# Applicator
# ---------------------------------------------------------------------------


def evaluate_cross_column_rules(row: dict) -> str | None:
    """Run all cross-column rules against a row dict.

    Returns a string like "cross_column_fail: CC1, CC3" listing all failing rule
    codes, or None if all rules pass.
    """
    failures = []
    for rule_code, rule_fn in ALL_RULES:
        result = rule_fn(row)
        if result is not None:
            failures.append(rule_code)
    if failures:
        return "cross_column_fail: " + ", ".join(failures)
    return None


def apply_cross_column_rules(df: DataFrame) -> DataFrame:
    """Apply cross-column validity rules to the DataFrame.

    Adds a `cross_column_fail` column with failing rule numbers (or None if passes).
    Rows that fail are excluded: `exclude` is set and `mapped` becomes False.
    """

    @pandas_udf(StringType())
    def _validate_udf(batch: pd.DataFrame) -> pd.Series:
        return batch.apply(
            lambda row: evaluate_cross_column_rules(row.to_dict()), axis=1
        )

    df = df.withColumn(
        "cross_column_fail",
        _validate_udf(F.struct(*[F.col(c) for c in df.columns])),
    )

    # Update exclude and mapped for failed rows
    df = df.withColumn(
        "exclude",
        F.when(
            F.col("cross_column_fail").isNotNull() & F.col("exclude").isNull(),
            F.col("cross_column_fail"),
        ).otherwise(F.col("exclude")),
    )

    df = df.withColumn(
        "mapped",
        F.when(F.col("cross_column_fail").isNotNull(), F.lit(False)).otherwise(
            F.col("mapped")
        ),
    )

    return df
