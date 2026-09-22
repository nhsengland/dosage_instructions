import re

import numpy as np
from pyspark.sql import DataFrame

from pyspark.sql import functions as F

from pyspark.sql.types import ArrayType, StringType

from dosage_instructions.data_enrichment.fhir_logic import (
    row_to_fhir_dosage,
    _map_when_to_fhir,
    _unit_coding,
)
import dosage_instructions.model.constants as myconstants

# ---------------------------------------------------------------------------
# Spark UDFs for FHIR coding lookups
# ---------------------------------------------------------------------------


def _scalar(val):
    """Extract a plain Python string from a value that may be a list or numpy array."""
    if val is None:
        return None
    if isinstance(val, (list, np.ndarray)):
        val = val[0] if len(val) > 0 else None
    if val is None:
        return None
    if isinstance(val, np.generic):
        val = val.item()
    return str(val) if not isinstance(val, str) else val


@F.udf(StringType())
def _unit_code(unit, spoonsize=None):
    unit = _scalar(unit)
    spoonsize = _scalar(spoonsize)
    if not unit:
        return None
    coding = _unit_coding(unit, spoonsize=spoonsize)
    return coding["code"] if coding else None


@F.udf(StringType())
def _unit_display(unit, spoonsize=None):
    unit = _scalar(unit)
    spoonsize = _scalar(spoonsize)
    if not unit:
        return None
    coding = _unit_coding(unit, spoonsize=spoonsize)
    return coding["display"] if coding else unit


@F.udf(StringType())
def _unit_system(unit, spoonsize=None):
    unit = _scalar(unit)
    spoonsize = _scalar(spoonsize)
    if not unit:
        return None
    coding = _unit_coding(unit, spoonsize=spoonsize)
    return coding["system"] if coding else None


@F.udf(StringType())
def _method_code(verb):
    verb = _scalar(verb)
    if not verb:
        return None
    m = myconstants.METHOD_TO_SNOMED.get(verb.lower().strip())
    return m["code"] if m else None


@F.udf(StringType())
def _method_display(verb):
    verb = _scalar(verb)
    if not verb:
        return None
    m = myconstants.METHOD_TO_SNOMED.get(verb.lower().strip())
    return m["display"] if m else verb


@F.udf(StringType())
def _route_code(route):
    route = _scalar(route)
    if not route:
        return None
    r = route.lower().strip()
    for key, snomed in myconstants.ROUTE_TO_SNOMED.items():
        if key in r:
            return snomed["code"]
    return None


@F.udf(StringType())
def _route_display(route):
    route = _scalar(route)
    if not route:
        return None
    r = route.lower().strip()
    for key, snomed in myconstants.ROUTE_TO_SNOMED.items():
        if key in r:
            return snomed["display"]
    return route


@F.udf(StringType())
def _period_ucum(unit):
    unit = _scalar(unit)
    if not unit:
        return None
    return myconstants.PERIOD_UNIT_TO_UCUM.get(unit.lower().strip())


@F.udf(StringType())
def _day_fhir(day_text):
    day_text = _scalar(day_text)
    if not day_text:
        return None
    days = [
        myconstants.DAY_TO_FHIR[w]
        for w in re.split(r"[,\s]+", day_text.lower())
        if w in myconstants.DAY_TO_FHIR
    ]
    return ", ".join(days) if days else None


@F.udf(StringType())
def _when_fhir(when_text):
    when_text = _scalar(when_text)
    return _map_when_to_fhir(when_text)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _coalesce_to(df, target_col, *source_cols):
    """Create target_col as coalesce of source columns that have content."""

    present = [c for c in source_cols if c in df.columns]
    if not present:
        return df.withColumn(target_col, F.lit(None))

    schema_map = {f.name: f.dataType for f in df.schema.fields}
    exprs = []
    for c in present:
        dtype = schema_map.get(c)
        if isinstance(dtype, ArrayType):
            exprs.append(F.when(F.size(F.col(c)) > 0, F.col(c)))
        else:
            exprs.append(F.when(_non_empty(F.col(c)), F.col(c)))

    if len(exprs) == 1:
        return df.withColumn(target_col, exprs[0])
    return df.withColumn(target_col, F.coalesce(*exprs))


def _non_empty(col_expr):
    """Returns a Column expression that is non-null and non-empty-string."""
    return col_expr.isNotNull() & (col_expr != F.lit(""))


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------


def refine_lookup_output_func(df: DataFrame) -> DataFrame:
    """Consolidate raw pipeline columns into the final FHIR-aligned output schema."""

    # ── Dose Quantity: doseQuantity + dose_QuantityValueOnly + milligramValue ──
    # SAFETY RULE: value and unit must come from the SAME element class. Mixing
    # value from one element with unit from another is dangerous.
    # e.g. "(300mg) 3 to be taken at night" → value=3, unit=mg would be WRONG
    # (interpreted as 3mg instead of 3 tablets at 300mg clarification).
    # Priority: doseQuantity > dose_QuantityValueOnly > milligramValue (whole element wins).

    def _arr_has(df, col_name):
        """True if column exists in df and has size > 0 (for ArrayType columns)."""
        if col_name in df.columns:
            return F.col(col_name).isNotNull() & (F.size(F.col(col_name)) > 0)
        return F.lit(False)

    _dq_has = _arr_has(df, "doseQuantity_quantity")
    _qvo_has = _arr_has(df, "dose_QuantityValueOnly_value")
    _mg_has = _arr_has(df, "milligramValue_value")
    df = df.withColumn(
        "doseQuantity_value",
        F.when(_dq_has, F.col("doseQuantity_quantity"))
        .when(_qvo_has, F.col("dose_QuantityValueOnly_value"))
        .when(_mg_has, F.col("milligramValue_value")),
    )
    # Unit only from the winning element (doseQuantity has units, dose_QuantityValueOnly has none,
    # milligramValue has milligram_units)
    _mg_unit_col = (
        F.col("milligramValue_milligram_units")
        if "milligramValue_milligram_units" in df.columns
        else F.lit(None)
    )
    df = df.withColumn(
        "doseQuantity_unit",
        F.when(
            _dq_has,
            (
                F.col("doseQuantity_units")
                if "doseQuantity_units" in df.columns
                else F.lit(None)
            ),
        )
        .when(_qvo_has, F.lit(None))
        .when(_mg_has, _mg_unit_col),
    )

    # ── Dose Range: doseRange + dose_QuantityValueAndMaxOnly + milligramMax ───
    # Same principle: all fields from the winning element only.
    #
    # IMPORTANT: We check the *original* doseRange_clean column (StringType, never
    # overwritten) rather than doseRange_low (ArrayType) because the subsequent
    # withColumn calls overwrite doseRange_low/high.  Spark Column expressions are
    # resolved lazily against the *current* DataFrame state, so checking a column
    # we are about to overwrite would give wrong results for later withColumn calls.
    _dr_has = (
        _non_empty(F.col("doseRange_clean"))
        if "doseRange_clean" in df.columns
        else F.lit(False)
    )
    _qvmo_has = _arr_has(df, "dose_QuantityValueAndMaxOnly_value")
    _mgmax_has = _arr_has(df, "milligramMax_value")
    df = df.withColumn(
        "doseRange_low",
        F.when(_dr_has, F.col("doseRange_low"))
        .when(_qvmo_has, F.col("dose_QuantityValueAndMaxOnly_value"))
        .when(_mgmax_has, F.col("milligramMax_value")),
    )
    df = df.withColumn(
        "doseRange_high",
        F.when(_dr_has, F.col("doseRange_high"))
        .when(_qvmo_has, F.col("dose_QuantityValueAndMaxOnly_valueMax"))
        .when(_mgmax_has, F.col("milligramMax_valueMax")),
    )
    _mgmax_unit_col = (
        F.col("milligramMax_milligram_units")
        if "milligramMax_milligram_units" in df.columns
        else F.lit(None)
    )
    df = df.withColumn(
        "doseRange_lowunit",
        F.when(
            _dr_has,
            (
                F.col("doseRange_units")
                if "doseRange_units" in df.columns
                else F.lit(None)
            ),
        )
        .when(_qvmo_has, F.lit(None))
        .when(_mgmax_has, _mgmax_unit_col),
    )
    df = df.withColumn(
        "doseRange_highunit",
        F.when(
            _dr_has,
            (
                F.col("doseRange_units")
                if "doseRange_units" in df.columns
                else F.lit(None)
            ),
        )
        .when(_qvmo_has, F.lit(None))
        .when(_mgmax_has, _mgmax_unit_col),
    )

    # Dose unit coding — if both doseQuantity_unit and doseRange_lowunit are present,
    # preserve both as an array [dose_unit, milli_unit] rather than silently dropping one.
    # If only one is present, the array will contain just that value.
    df = df.withColumn(
        "dose_unit_all",
        F.array_compact(
            F.array(F.col("doseQuantity_unit"), F.col("doseRange_lowunit"))
        ),
    )
    # Use first element (doseQuantity_unit if present, else doseRange_lowunit) for coding columns.
    # Coalesce spoonsize from doseQuantity then doseRange — whichever unit won also drives spoonsize.
    dose_unit_col = F.element_at(F.col("dose_unit_all"), 1)
    spoonsize_col = F.coalesce(
        F.col("doseQuantity_spoonsize"), F.col("doseRange_spoonsize")
    )
    df = df.withColumn("dose_unit_code", _unit_code(dose_unit_col, spoonsize_col))
    df = df.withColumn("dose_unit_display", _unit_display(dose_unit_col, spoonsize_col))
    df = df.withColumn("dose_unit_system", _unit_system(dose_unit_col, spoonsize_col))

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
    df = df.withColumn("method_snomed_code", _method_code(F.col("method_verb")))
    df = df.withColumn("method_snomed_display", _method_display(F.col("method_verb")))

    # ── Rate Ratio ───────────────────────────────────────────────────────────
    df = df.withColumnRenamed("rateRatio_period_unit", "rateRatio_periodUnit")
    df = df.withColumn(
        "rateRatio_periodUnit_ucum", _period_ucum(F.col("rateRatio_periodUnit"))
    )

    # ── Rate Range ───────────────────────────────────────────────────────────
    df = df.withColumnRenamed("rateRange_special_unit", "rateRange_unit")
    df = df.withColumn("rateRange_unit_code", _unit_code(F.col("rateRange_unit")))
    df = df.withColumn("rateRange_unit_display", _unit_display(F.col("rateRange_unit")))
    df = df.withColumn("rateRange_unit_system", _unit_system(F.col("rateRange_unit")))

    # ── Rate Quantity ────────────────────────────────────────────────────────
    df = df.withColumnRenamed("rateQuantity_special_unit", "rateQuantity_unit")
    df = df.withColumn("rateQuantity_unit_code", _unit_code(F.col("rateQuantity_unit")))
    df = df.withColumn(
        "rateQuantity_unit_display", _unit_display(F.col("rateQuantity_unit"))
    )
    df = df.withColumn(
        "rateQuantity_unit_system", _unit_system(F.col("rateQuantity_unit"))
    )

    # ── Frequency: frequencyBare + frequencyWithMethod + periodElement default ─
    df = _coalesce_to(
        df,
        "frequency_value",
        "frequencyBare_frequency",
        "frequencyWithMethod_frequency",
        "periodElement_frequency",
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
    df = df.withColumn(
        "frequency_periodUnit_ucum", _period_ucum(F.col("frequency_periodUnit"))
    )

    # ── Count (keep as-is) ───────────────────────────────────────────────────

    # ── Period (rename from periodElement) ───────────────────────────────────
    df = df.withColumnRenamed("periodElement_period", "period_value")
    df = df.withColumnRenamed("periodElement_periodMax", "period_valueMax")
    df = df.withColumnRenamed("periodElement_period_units", "period_units")
    df = df.withColumn("period_units_ucum", _period_ucum(F.col("period_units")))

    # ── Duration: durationValue + durationMax ────────────────────────────────
    df = df.withColumnRenamed("durationValue_value", "duration_value")
    df = df.withColumnRenamed("durationMax_value", "duration_valueMax")
    df = _coalesce_to(
        df,
        "duration_units",
        "durationValue_period_units",
        "durationMax_period_units",
    )
    df = df.withColumn("duration_units_ucum", _period_ucum(F.col("duration_units")))

    # ── When: whenBare + whenWithMethod ──────────────────────────────────────
    df = _coalesce_to(
        df,
        "when_value",
        "whenBare_when",
        "whenWithMethod_when",
    )
    df = df.withColumn("when_fhir", _when_fhir(F.col("when_value")))
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
    df = df.withColumn("when_periodUnit_ucum", _period_ucum(F.col("when_periodUnit")))

    # ── Day of Week ──────────────────────────────────────────────────────────
    df = df.withColumn("dayOfWeek_fhir", _day_fhir(F.col("dayOfWeek_value")))

    # ── Time of Day (keep as-is) ─────────────────────────────────────────────

    # ── Event (keep as-is) ───────────────────────────────────────────────────

    # ── Bounds Duration ──────────────────────────────────────────────────────
    df = df.withColumn(
        "boundsDuration_unit_ucum", _period_ucum(F.col("boundsDuration_unit"))
    )

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

    # ── Route ────────────────────────────────────────────────────────────────
    df = df.withColumn("route_snomed_code", _route_code(F.col("route_clean")))
    df = df.withColumn("route_snomed_display", _route_display(F.col("route_clean")))

    # ── Site (SNOMED coded via SITE_TO_SNOMED in fhir_logic._build_site) ────────

    # ── Max Dose ─────────────────────────────────────────────────────────────
    df = df.withColumn(
        "maxDosePerPeriod_num_unit_code", _unit_code(F.col("maxDosePerPeriod_num_unit"))
    )
    df = df.withColumn(
        "maxDosePerPeriod_num_unit_display",
        _unit_display(F.col("maxDosePerPeriod_num_unit")),
    )
    df = df.withColumn(
        "maxDosePerPeriod_num_unit_system",
        _unit_system(F.col("maxDosePerPeriod_num_unit")),
    )
    df = df.withColumn(
        "maxDosePerPeriod_denom_unit_ucum",
        _period_ucum(F.col("maxDosePerPeriod_denom_unit")),
    )
    df = df.withColumn(
        "maxDosePerAdministration_unit_code",
        _unit_code(F.col("maxDosePerAdministration_unit")),
    )
    df = df.withColumn(
        "maxDosePerAdministration_unit_display",
        _unit_display(F.col("maxDosePerAdministration_unit")),
    )
    df = df.withColumn(
        "maxDosePerAdministration_unit_system",
        _unit_system(F.col("maxDosePerAdministration_unit")),
    )
    df = df.withColumn(
        "maxDosePerLifetime_unit_code", _unit_code(F.col("maxDosePerLifetime_unit"))
    )
    df = df.withColumn(
        "maxDosePerLifetime_unit_display",
        _unit_display(F.col("maxDosePerLifetime_unit")),
    )
    df = df.withColumn(
        "maxDosePerLifetime_unit_system", _unit_system(F.col("maxDosePerLifetime_unit"))
    )

    # ── As Needed (keep as-is) ───────────────────────────────────────────────

    # ── Additional Information (keep as-is) ──────────────────────────────────

    # ── Generate FHIR JSON column ────────────────────────────────────────────
    @F.pandas_udf(StringType())
    def _fhir_udf(batch):
        def _process_row(row):
            mapped_val = row.get("mapped")
            if str(mapped_val).strip().lower() != "true":
                return None
            return row_to_fhir_dosage(row.to_dict())

        return batch.apply(_process_row, axis=1)

    df = df.withColumn(
        "fhir_json", _fhir_udf(F.struct(*[F.col(c) for c in df.columns]))
    )
    # fhir_json_no_text: same as fhir_json but with the "text" field removed.
    # fhir_json is unique per-row (because "text" contains the raw dosage string),
    # so it can't be used to deduplicate or compare FHIR structure. This column
    # allows grouping/comparing rows that produce identical FHIR structure.
    df = df.withColumn(
        "fhir_json_no_text",
        F.when(
            F.col("fhir_json").isNotNull(),
            F.regexp_replace(
                F.col("fhir_json"), r'^(\{"text": "(?:[^"\\]|\\.)*",?)', "{"
            ),
        ).otherwise(F.lit(None)),
    )

    # ── Flatten array columns to scalars (extras cols stay as arrays) ────────

    _extras_cols = {
        "extras_clean",
        "extrasPAUSE_clean",
        "extrasALTER_clean",
        "extras_b_clean",
        "extras_whenoffset",
        "forElement_clean",
        "dose_unit_all",
    }
    _schema_map = {f.name: f.dataType for f in df.schema.fields}
    for _col in list(df.columns):
        if _col not in _extras_cols and isinstance(_schema_map.get(_col), ArrayType):
            df = df.withColumn(_col, F.element_at(F.col(_col), 1))

    # ── Select final output columns ──────────────────────────────────────────
    output_cols = [
        # identifiers & metadata
        "dosage",
        "dosage_lower",
        "dosage_count",
        "dosage_elements",
        "exclude",
        "mapped",
        "buckets",
        "fhir_json",
        "fhir_json_no_text",
        "dosage_spare",
        # dose
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
        # method
        "method_verb",
        "method_snomed_code",
        "method_snomed_display",
        # rate
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
        # frequency
        "frequency_value",
        "frequency_valueMax",
        "frequency_periodUnit",
        "frequency_periodUnit_ucum",
        # count
        "count_count",
        "count_countMax",
        # period
        "period_value",
        "period_valueMax",
        "period_units",
        "period_units_ucum",
        # duration
        "duration_value",
        "duration_valueMax",
        "duration_units",
        "duration_units_ucum",
        # when
        "when_value",
        "when_fhir",
        "when_offset",
        "when_periodUnit",
        "when_periodUnit_ucum",
        # timing
        "dayOfWeek_value",
        "dayOfWeek_fhir",
        "timeOfDay_value",
        "event_value",
        # bounds
        "boundsDuration_value",
        "boundsDuration_unit",
        "boundsDuration_unit_ucum",
        "boundsDuration_low",
        "boundsDuration_high",
        "boundsDuration_low_unit",
        "boundsDuration_high_unit",
        "boundsPeriod_start",
        "boundsPeriod_end",
        # max dose
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
        # route & site
        "route_clean",
        "route_snomed_code",
        "route_snomed_display",
        "site_clean",
        # as needed
        "asNeededBoolean_clean",
        # additional information / purpose
        "extrasAsDirected_clean",
        "extras_clean",
        "extrasPAUSE_clean",
        "extrasALTER_clean",
        "extras_b_clean",
        "extras_whenoffset",
        "forElement_clean",
        # _clean gate columns needed by fhir_logic to detect presence of each element
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
    ]

    available = set(df.columns)
    select_cols = [c for c in output_cols if c in available]

    return df.select(select_cols)
