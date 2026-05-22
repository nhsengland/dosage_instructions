from pyspark.sql import DataFrame
from pyspark.sql.functions import (
    coalesce,
    col as col_,
    lit,
    when,
)


def _coalesce_to(df, target_col, *source_cols):
    """Create target_col as coalesce of source columns that have content.

    For array columns: treats empty arrays as null before coalescing.
    For string columns: treats empty strings as null before coalescing.
    Skips source columns not present in the DataFrame.
    """
    from pyspark.sql.types import ArrayType as SparkArrayType
    from pyspark.sql.functions import size

    present = [c for c in source_cols if c in df.columns]
    if not present:
        return df.withColumn(target_col, lit(None))

    schema_map = {f.name: f.dataType for f in df.schema.fields}
    exprs = []
    for c in present:
        dtype = schema_map.get(c)
        if isinstance(dtype, SparkArrayType):
            exprs.append(when(size(col_(c)) > 0, col_(c)))
        else:
            exprs.append(when(_non_empty(col_(c)), col_(c)))

    if len(exprs) == 1:
        return df.withColumn(target_col, exprs[0])
    return df.withColumn(target_col, coalesce(*exprs))


def _non_empty(col_expr):
    """Returns a Column expression that is non-null and non-empty-string."""
    return col_expr.isNotNull() & (col_expr != lit(""))


def refine_lookup_output_func(df: DataFrame) -> DataFrame:
    """
    Consolidate raw pipeline columns into the final output schema.
    Merges sibling element classes into unified FHIR-aligned output columns.
    """

    # ── Dose Quantity: doseQuantity + dose_QuantityValueOnly ─────────────────
    df = _coalesce_to(
        df,
        "doseQuantity_value",
        "doseQuantity_quantity",
        "dose_QuantityValueOnly_value",
    )
    # units and spoonsize only come from doseQuantity (ValueOnly has no unit)
    df = df.withColumnRenamed("doseQuantity_units", "doseQuantity_unit")

    # ── Dose Range: doseRange + dose_QuantityValueAndMaxOnly ─────────────────
    df = _coalesce_to(
        df,
        "doseRange_low",
        "doseRange_low",
        "dose_QuantityValueAndMaxOnly_value",
    )
    df = _coalesce_to(
        df,
        "doseRange_high",
        "doseRange_high",
        "dose_QuantityValueAndMaxOnly_valueMax",
    )
    # units and spoonsize only come from doseRange (ValueAndMaxOnly has no unit)
    df = df.withColumnRenamed("doseRange_units", "doseRange_unit")

    # ── Dose x Milli (pipeline-specific, keep as-is) ────────────────────────
    df = df.withColumnRenamed("doseXMilliValueOnly_value", "doseXMilli_value")
    df = df.withColumnRenamed("doseXMilliValueOnly_val_milli", "doseXMilli_valMilli")
    df = df.withColumnRenamed("doseXMilliValueOnly_milli", "doseXMilli_milli")

    # ── Milligram: milligramValue + milligramMax ─────────────────────────────
    df = _coalesce_to(
        df,
        "milligram_value",
        "milligramValue_value",
        "milligramMax_value",
    )
    df = df.withColumnRenamed("milligramMax_valueMax", "milligram_valueMax")
    df = _coalesce_to(
        df,
        "milligram_units",
        "milligramValue_milligram_units",
        "milligramMax_milligram_units",
    )

    # ── Method: methodDirect + methodPassive ─────────────────────────────────
    df = _coalesce_to(
        df,
        "method_verb",
        "methodDirect_verb",
        "methodPassive_verb",
    )

    # ── Rate Ratio (keep as-is) ──────────────────────────────────────────────
    df = df.withColumnRenamed("rateRatio_period_unit", "rateRatio_periodUnit")

    # ── Rate Range (keep as-is) ──────────────────────────────────────────────
    df = df.withColumnRenamed("rateRange_special_unit", "rateRange_unit")

    # ── Rate Quantity (keep as-is) ───────────────────────────────────────────
    df = df.withColumnRenamed("rateQuantity_special_unit", "rateQuantity_unit")

    # ── Frequency: frequencyBare + frequencyWithMethod ───────────────────────
    df = _coalesce_to(
        df,
        "frequency_value",
        "frequencyBare_frequency",
        "frequencyWithMethod_frequency",
    )
    df = _coalesce_to(
        df,
        "frequency_valueMax",
        "frequencyBare_frequencyMax",
        "frequencyWithMethod_frequencyMax",
    )
    df = _coalesce_to(
        df,
        "frequency_periodUnit",
        "frequencyBare_period_unit",
        "frequencyWithMethod_period_unit",
    )

    # ── Count (keep as-is) ───────────────────────────────────────────────────

    # ── Period (rename from periodElement) ───────────────────────────────────
    df = df.withColumnRenamed("periodElement_period", "period_value")
    df = df.withColumnRenamed("periodElement_periodMax", "period_valueMax")
    df = df.withColumnRenamed("periodElement_period_units", "period_units")

    # ── Duration: durationValue + durationMax ────────────────────────────────
    # durationValue = "over 5 days"; durationMax = "max 3 days"
    # Mutually exclusive (Rule 3). Map: durationValue → duration_value,
    # durationMax → duration_valueMax (an upper-cap).
    df = df.withColumnRenamed("durationValue_value", "duration_value")
    df = df.withColumnRenamed("durationMax_value", "duration_valueMax")
    df = _coalesce_to(
        df,
        "duration_units",
        "durationValue_period_units",
        "durationMax_period_units",
    )

    # ── When: whenBare + whenWithMethod ──────────────────────────────────────
    df = _coalesce_to(
        df,
        "when_value",
        "whenBare_when",
        "whenWithMethod_when",
    )
    df = _coalesce_to(
        df,
        "when_offset",
        "whenBare_offset",
        "whenWithMethod_offset",
    )
    df = _coalesce_to(
        df,
        "when_periodUnit",
        "whenBare_period_unit",
        "whenWithMethod_period_unit",
    )

    # ── Day of Week (keep as-is) ─────────────────────────────────────────────

    # ── Time of Day (keep as-is) ─────────────────────────────────────────────

    # ── Event (keep as-is) ───────────────────────────────────────────────────

    # ── Bounds Duration (keep as-is) ────────────────────────────────────────
    # Has: value, unit, low, high, low_unit, high_unit (pattern-dependent)

    # ── Bounds Period: boundsPeriod + boundsAPeriodStartEnd ───────────────────
    df = _coalesce_to(
        df,
        "boundsPeriod_start",
        "boundsPeriod_start",
        "boundsAPeriodStartEnd_start",
    )
    df = _coalesce_to(
        df,
        "boundsPeriod_end",
        "boundsPeriod_end",
        "boundsAPeriodStartEnd_end",
    )

    # ── Max Dose (all three keep as-is) ──────────────────────────────────────

    # ── Route (keep as-is) ───────────────────────────────────────────────────

    # ── Site (keep as-is) ────────────────────────────────────────────────────

    # ── As Needed Boolean (keep as-is) ───────────────────────────────────────

    # ── As Needed Codeable Concept (keep as-is) ──────────────────────────────

    # ── Additional Information (grouped) ─────────────────────────────────────
    # extras_clean, extrasPAUSE_clean, extrasALTER_clean, extras_b_clean,
    # extras_whenoffset, and forElement_value are all kept as-is in output
    # (already exist as columns from the pipeline).

    # ── Select final output columns ─────────────────────────────────────────
    output_cols = [
        # identifiers & metadata
        "dosage",
        "dosage_lower",
        "dosage_count",
        "dosage_elements",
        "exclude",
        "mapped",
        "buckets",
        "dosage_spare",
        # dose
        "doseQuantity_value",
        "doseQuantity_unit",
        "doseQuantity_spoonsize",
        "doseRange_low",
        "doseRange_high",
        "doseRange_unit",
        "doseRange_spoonsize",
        "doseXMilli_value",
        "doseXMilli_valMilli",
        "doseXMilli_milli",
        "milligram_value",
        "milligram_valueMax",
        "milligram_units",
        # method
        "method_verb",
        # rate
        "rateRatio_numerator",
        "rateRatio_denominator",
        "rateRatio_periodUnit",
        "rateRange_low",
        "rateRange_high",
        "rateRange_unit",
        "rateQuantity_value",
        "rateQuantity_unit",
        # frequency
        "frequency_value",
        "frequency_valueMax",
        "frequency_periodUnit",
        # count
        "count_count",
        "count_countMax",
        # period
        "period_value",
        "period_valueMax",
        "period_units",
        # duration
        "duration_value",
        "duration_valueMax",
        "duration_units",
        # when
        "when_value",
        "when_offset",
        "when_periodUnit",
        # timing
        "dayOfWeek_value",
        "timeOfDay_value",
        "event_value",
        # bounds
        "boundsDuration_value",
        "boundsDuration_unit",
        "boundsDuration_low",
        "boundsDuration_high",
        "boundsDuration_low_unit",
        "boundsDuration_high_unit",
        "boundsPeriod_start",
        "boundsPeriod_end",
        # max dose
        "maxDosePerPeriod_num_value",
        "maxDosePerPeriod_num_unit",
        "maxDosePerPeriod_denom_value",
        "maxDosePerPeriod_denom_unit",
        "maxDosePerAdministration_value",
        "maxDosePerAdministration_unit",
        "maxDosePerLifetime_value",
        "maxDosePerLifetime_unit",
        # route & site
        "route_clean",
        "site_clean",
        # as needed
        "asNeededBoolean_clean",
        "asNeededCodeableConcept_value",
        # additional information
        "extras_clean",
        "extrasPAUSE_clean",
        "extrasALTER_clean",
        "extras_b_clean",
        "extras_whenoffset",
        "forElement_value",
    ]

    available = set(df.columns)
    select_cols = [c for c in output_cols if c in available]

    return df.select(select_cols)
