import re
from dataclasses import dataclass

import pandas as pd
from pyspark.sql import DataFrame
from pyspark.sql.functions import (
    col as col_,
    lit,
    pandas_udf,
    regexp_replace,
    trim,
    when,
    expr,
)
from dosage_instructions.model.constants import (
    EMERGENCY_NUMBERS,
    NUMERIC_VALIDATION_RULES,
    YEAR_RANGE,
)

# ---------------------------------------------------------------------------
# Constants: Element Groups
# ---------------------------------------------------------------------------

DOSE_GROUP = frozenset(
    {
        "doseQuantity",
        "doseRange",
        "dose_QuantityValueOnly",
        "dose_QuantityValueAndMaxOnly",
        "doseXMilliValueOnly",
        "milligramValue",
        "milligramMax",
    }
)

FREQUENCY_GROUP = frozenset(
    {
        "frequencyBare",
        "frequencyWithMethod",
        "periodElement",
        "count",
    }
)

AS_NEEDED_GROUP = frozenset(
    {
        "asNeededBoolean",
        "asNeededCodeableConcept",
    }
)

ACTION_GROUP = frozenset(
    {
        "methodDirect",
        "methodPassive",
    }
)

DURATION_GROUP = frozenset(
    {
        "durationValue",
        "durationMax",
        "boundsDuration",
        "boundsPeriod",
        "boundsAPeriodStartEnd",
    }
)

MAX_DOSE_GROUP = frozenset(
    {
        "maxDosePerPeriod",
        "maxDosePerAdministration",
        "maxDosePerLifetime",
    }
)

TIMING_GROUP = frozenset(
    {
        "asNeededBoolean",
        "asNeededCodeableConcept",
        "event",
        "forElement",
        "frequencyBare",
        "frequencyWithMethod",
        "count",
        "periodElement",
        "whenBare",
        "whenWithMethod",
        "dayOfWeek",
        "timeOfDay",
        "boundsDuration",
        "boundsPeriod",
        "boundsAPeriodStartEnd",
    }
)

TO_BE_TAKEN_GROUP = frozenset(
    {
        "methodPassive",
        "frequencyWithMethod",
        "whenWithMethod",
    }
)

LOGICAL_GROUPS = {
    "Dose": DOSE_GROUP,
    "Frequency": FREQUENCY_GROUP,
    "AsNeeded": AS_NEEDED_GROUP,
    "Action": ACTION_GROUP,
    "Duration": DURATION_GROUP,
    "MaxDose": MAX_DOSE_GROUP,
    "ToBeTaken": TO_BE_TAKEN_GROUP,
}

CLARIFICATION_ELEMENTS = frozenset({"milligramValue", "milligramMax"})
CLARIFICATION_TARGETS = frozenset(
    {"doseQuantity", "dose_QuantityValueOnly", "doseRange"}
)

# ---------------------------------------------------------------------------
# Token Parser
# ---------------------------------------------------------------------------


@dataclass
class Token:
    name: str | None
    bracketed: bool
    sentence_idx: int = 0


TOKEN_RE = re.compile(
    r"\(\*(\w+)\*\)"  # group 1: bracketed element
    r"|\*(\w+)\*"  # group 2: bare element
    r"|\."  # full stop (sentence boundary)
    r"|[,]"  # comma (boundary marker)
    r"|(?<!\w)-(?!\w)"  # dash as separator (not part of element name)
)


def parse_elements(s: str):
    """
    Parse a dosage_elements string into tokens.

    Returns (tokens, has_free_text, punctuation_map).
    - tokens: ordered list of Token objects
    - has_free_text: True if non-element content found
    - punctuation_map: dict mapping token index -> set of preceding punctuation chars
    """
    if not s or not s.strip():
        return [], False, {}

    tokens = []
    punctuation_map = {}
    sentence_idx = 0
    pending_punct = set()
    has_free_text = False

    remainder = s
    last_end = 0

    for match in TOKEN_RE.finditer(s):
        start, end = match.span()

        gap = s[last_end:start].strip()
        if gap:
            has_free_text = True

        if match.group(1):
            tokens.append(
                Token(name=match.group(1), bracketed=True, sentence_idx=sentence_idx)
            )
            if pending_punct:
                punctuation_map[len(tokens) - 1] = pending_punct
                pending_punct = set()
        elif match.group(2):
            tokens.append(
                Token(name=match.group(2), bracketed=False, sentence_idx=sentence_idx)
            )
            if pending_punct:
                punctuation_map[len(tokens) - 1] = pending_punct
                pending_punct = set()
        elif match.group(0) == ".":
            sentence_idx += 1
            pending_punct.add(".")
        elif match.group(0) == ",":
            pending_punct.add(",")
        else:
            pending_punct.add("-")

        last_end = end

    trailing = s[last_end:].strip()
    if trailing:
        has_free_text = True

    return tokens, has_free_text, punctuation_map


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def get_active_elements(tokens: list[Token]) -> list[str]:
    return [t.name for t in tokens if not t.bracketed and t.name]


def get_sentence_elements(tokens: list[Token]) -> list[list[str]]:
    sentences = {}
    for t in tokens:
        if not t.bracketed and t.name:
            sentences.setdefault(t.sentence_idx, []).append(t.name)
    max_idx = max((t.sentence_idx for t in tokens), default=0)
    return [sentences.get(i, []) for i in range(max_idx + 1)]


def get_active_tokens(tokens: list[Token]) -> list[Token]:
    return [t for t in tokens if not t.bracketed and t.name]


def in_different_sentences(tok_a: Token, tok_b: Token) -> bool:
    return tok_a.sentence_idx != tok_b.sentence_idx


def has_punct_between(
    idx_a: int, idx_b: int, punctuation_map: dict, chars: set
) -> bool:
    lo, hi = min(idx_a, idx_b), max(idx_a, idx_b)
    for i in range(lo + 1, hi + 1):
        if i in punctuation_map and punctuation_map[i] & chars:
            return True
    return False


# ---------------------------------------------------------------------------
# Rule Checkers
# ---------------------------------------------------------------------------


def check_rule_1a(tokens: list[Token]) -> str | None:
    """At most one element from the 'to be taken' group per sentence."""
    sentence_elements = get_sentence_elements(tokens)
    for sent in sentence_elements:
        count = sum(1 for e in sent if e in TO_BE_TAKEN_GROUP)
        if count > 1:
            return "1a"
    return None


def check_rule_1b(tokens: list[Token]) -> str | None:
    """MethodDirect + 'to be taken' element: methodDirect must come first and not adjacent."""
    active = get_active_elements(tokens)
    if "methodDirect" not in active:
        return None
    tbt_indices = [i for i, e in enumerate(active) if e in TO_BE_TAKEN_GROUP]
    if not tbt_indices:
        return None
    md_idx = active.index("methodDirect")
    for tbt_idx in tbt_indices:
        if md_idx > tbt_idx:
            return "1b"
        if tbt_idx == md_idx + 1:
            return "1b"
    return None


def check_rule_1c(tokens: list[Token]) -> str | None:
    """MethodDirect + MethodPassive is always invalid."""
    active = get_active_elements(tokens)
    if "methodDirect" in active and "methodPassive" in active:
        return "1c"
    return None


def check_rule_2(tokens: list[Token]) -> str | None:
    """MethodDirect must not follow a dose element (per sentence)."""
    sentence_elements = get_sentence_elements(tokens)
    for sent in sentence_elements:
        if "methodDirect" not in sent:
            continue
        md_idx = sent.index("methodDirect")
        for i in range(md_idx):
            if sent[i] in DOSE_GROUP:
                return "2"
    return None


def check_rule_3(tokens: list[Token]) -> str | None:
    """Only one element per logical group (full instruction, with clarification exception)."""
    active = get_active_elements(tokens)
    active_tokens = get_active_tokens(tokens)

    for group_name, members in LOGICAL_GROUPS.items():
        found = [e for e in active if e in members]
        if len(found) <= 1:
            continue
        if group_name == "Dose" and _is_clarification(found, active, active_tokens):
            continue
        return "3"
    return None


def _is_clarification(
    found: list[str], active: list[str], active_tokens: list[Token]
) -> bool:
    clar = [e for e in found if e in CLARIFICATION_ELEMENTS]
    targets = [e for e in found if e in CLARIFICATION_TARGETS]
    others = [
        e
        for e in found
        if e not in CLARIFICATION_ELEMENTS and e not in CLARIFICATION_TARGETS
    ]

    if not clar or not targets or others:
        return False
    if len(targets) > 1:
        return False

    for ce in clar:
        ce_positions = [i for i, e in enumerate(active) if e == ce]
        target_positions = [
            i for i, e in enumerate(active) if e in CLARIFICATION_TARGETS
        ]
        adjacent = any(
            abs(cp - tp) == 1 for cp in ce_positions for tp in target_positions
        )
        if not adjacent:
            return False
    return True


def check_rule_9a(tokens: list[Token], punctuation_map: dict) -> str | None:
    """ExtrasALTER present -> INVALID (unless rescued by brackets, full stop, comma, or dash)."""
    active_tokens = get_active_tokens(tokens)
    se_tokens = [t for t in active_tokens if t.name == "extrasALTER"]
    if not se_tokens:
        return None

    for se_tok in se_tokens:
        other_core = [
            t
            for t in active_tokens
            if t.name != "extrasALTER"
            and t.name not in ("extrasPAUSE", "extras", "extras_b")
        ]
        if not other_core:
            return "9a"
        se_all_idx = tokens.index(se_tok)
        for ct in other_core:
            if in_different_sentences(se_tok, ct):
                continue
            ct_all_idx = tokens.index(ct)
            if has_punct_between(se_all_idx, ct_all_idx, punctuation_map, {",", "-"}):
                continue
            return "9a"
    return None


def check_rule_10(tokens: list[Token]) -> str | None:
    """Singular DayOfWeek + any Frequency element -> INVALID."""
    active = get_active_elements(tokens)
    if "dayOfWeek" in active and any(e in FREQUENCY_GROUP for e in active):
        return "10"
    return None


def check_rule_0(tokens: list[Token]) -> str | None:
    """Must have (Amount OR Action) AND Timing."""
    active = get_active_elements(tokens)
    has_amount = any(e in DOSE_GROUP for e in active)
    has_action = any(e in ACTION_GROUP for e in active)
    has_timing = any(e in TIMING_GROUP for e in active)

    if not ((has_amount or has_action) and has_timing):
        return "0"
    return None


def check_rule_4(tokens: list[Token], punctuation_map: dict) -> str | None:
    """Dose before frequency (rescued by full stop or comma/dash at boundary)."""
    active_tokens = get_active_tokens(tokens)
    freq_indices = [i for i, t in enumerate(active_tokens) if t.name in FREQUENCY_GROUP]
    dose_indices = [i for i, t in enumerate(active_tokens) if t.name in DOSE_GROUP]

    if not freq_indices or not dose_indices:
        return None

    for f_idx in freq_indices:
        for d_idx in dose_indices:
            if f_idx < d_idx:
                f_tok = active_tokens[f_idx]
                d_tok = active_tokens[d_idx]
                if in_different_sentences(f_tok, d_tok):
                    continue
                all_tok_f_idx = tokens.index(f_tok)
                all_tok_d_idx = tokens.index(d_tok)
                if has_punct_between(
                    all_tok_f_idx, all_tok_d_idx, punctuation_map, {",", "-"}
                ):
                    continue
                return "4"
    return None


def check_rule_7(tokens: list[Token], punctuation_map: dict) -> str | None:
    """WhenBare/Site before any dose element -> AMBIGUOUS (rescued by full stop or comma/dash)."""
    active_tokens = get_active_tokens(tokens)
    problematic = {"whenBare", "site"}
    prob_indices = [i for i, t in enumerate(active_tokens) if t.name in problematic]
    dose_indices = [i for i, t in enumerate(active_tokens) if t.name in DOSE_GROUP]

    if not prob_indices or not dose_indices:
        return None

    for p_idx in prob_indices:
        for d_idx in dose_indices:
            if p_idx < d_idx:
                p_tok = active_tokens[p_idx]
                d_tok = active_tokens[d_idx]
                if in_different_sentences(p_tok, d_tok):
                    continue
                all_tok_p_idx = tokens.index(p_tok)
                all_tok_d_idx = tokens.index(d_tok)
                if has_punct_between(
                    all_tok_p_idx, all_tok_d_idx, punctuation_map, {",", "-"}
                ):
                    continue
                return "7"
    return None


def check_rule_8(tokens: list[Token], punctuation_map: dict) -> str | None:
    """ForElement/AsNeeded before both dose AND frequency -> AMBIGUOUS."""
    active_tokens = get_active_tokens(tokens)
    early_elements = {"forElement", "asNeededBoolean", "asNeededCodeableConcept"}

    early_indices = [i for i, t in enumerate(active_tokens) if t.name in early_elements]
    dose_indices = [i for i, t in enumerate(active_tokens) if t.name in DOSE_GROUP]
    freq_indices = [i for i, t in enumerate(active_tokens) if t.name in FREQUENCY_GROUP]

    if not early_indices or not dose_indices or not freq_indices:
        return None

    for e_idx in early_indices:
        e_tok = active_tokens[e_idx]
        before_all_dose = all(e_idx < d for d in dose_indices)
        before_all_freq = all(e_idx < f for f in freq_indices)

        if before_all_dose and before_all_freq:
            dose_tok = active_tokens[min(dose_indices)]
            if in_different_sentences(e_tok, dose_tok):
                continue
            all_tok_e_idx = tokens.index(e_tok)
            all_tok_d_idx = tokens.index(dose_tok)
            if has_punct_between(
                all_tok_e_idx, all_tok_d_idx, punctuation_map, {",", "-"}
            ):
                continue
            return "8"
    return None


def check_rule_9b(tokens: list[Token], punctuation_map: dict) -> str | None:
    """ExtrasPAUSE present -> AMBIGUOUS (unless rescued by brackets, full stop, comma, or dash)."""
    active_tokens = get_active_tokens(tokens)
    info_tokens = [t for t in active_tokens if t.name == "extrasPAUSE"]
    if not info_tokens:
        return None

    for info_tok in info_tokens:
        other_core = [
            t
            for t in active_tokens
            if t.name not in ("extrasPAUSE", "extrasALTER", "extras", "extras_b")
        ]
        if not other_core:
            return "9b"
        info_all_idx = tokens.index(info_tok)
        for ct in other_core:
            if in_different_sentences(info_tok, ct):
                continue
            ct_all_idx = tokens.index(ct)
            if has_punct_between(info_all_idx, ct_all_idx, punctuation_map, {",", "-"}):
                continue
            return "9b"
    return None


def check_rule_9c(tokens: list[Token], punctuation_map: dict) -> str | None:
    """extras_b present -> AMBIGUOUS (unless rescued by brackets or full stop)."""
    active_tokens = get_active_tokens(tokens)
    info_tokens = [t for t in active_tokens if t.name == "extras_b"]
    if not info_tokens:
        return None

    num_sentences = max((t.sentence_idx for t in tokens), default=0) + 1
    if num_sentences <= 1:
        return "9c"

    for info_tok in info_tokens:
        other_core = [
            t
            for t in active_tokens
            if t.name not in ("extrasPAUSE", "extrasALTER", "extras", "extras_b")
        ]
        if not other_core:
            return "9c"
        all_in_different = all(
            in_different_sentences(info_tok, ct) for ct in other_core
        )
        if not all_in_different:
            return "9c"
    return None


def check_rule_11(tokens: list[Token]) -> str | None:
    """Frequency/Count as first element in sentence with no dose/action -> AMBIGUOUS."""
    sentence_elements = get_sentence_elements(tokens)
    for sent in sentence_elements:
        if not sent:
            continue
        first = sent[0]
        if first in FREQUENCY_GROUP or first == "count":
            has_dose = any(e in DOSE_GROUP for e in sent)
            has_action = any(e in ACTION_GROUP for e in sent)
            if not has_dose and not has_action:
                return "11"
    return None


def check_rule_12(tokens: list[Token]) -> str | None:
    """DayOfWeek without frequencyBare or frequencyWithMethod -> INVALID."""
    active = get_active_elements(tokens)
    if "dayOfWeek" not in active:
        return None
    if "frequencyBare" in active or "frequencyWithMethod" in active:
        return None
    return "12"


# ---------------------------------------------------------------------------
# Core Evaluator
# ---------------------------------------------------------------------------


def evaluate_rules(elements_str: str | None) -> str | None:
    """Evaluate all rules against a dosage_elements string. Returns exclusion reason or None."""
    if not elements_str or not elements_str.strip():
        return None

    tokens, has_free_text, punctuation_map = parse_elements(elements_str)

    if has_free_text:
        return "not fully captured"

    if not tokens:
        return "empty field"

    failures = []

    result = check_rule_1a(tokens)
    if result:
        failures.append(result)

    result = check_rule_1b(tokens)
    if result:
        failures.append(result)

    result = check_rule_1c(tokens)
    if result:
        failures.append(result)

    result = check_rule_2(tokens)
    if result:
        failures.append(result)

    result = check_rule_3(tokens)
    if result:
        failures.append(result)

    result = check_rule_9a(tokens, punctuation_map)
    if result:
        failures.append(result)

    result = check_rule_10(tokens)
    if result:
        failures.append(result)

    result = check_rule_0(tokens)
    if result:
        failures.append(result)

    result = check_rule_4(tokens, punctuation_map)
    if result:
        failures.append(result)

    result = check_rule_7(tokens, punctuation_map)
    if result:
        failures.append(result)

    result = check_rule_8(tokens, punctuation_map)
    if result:
        failures.append(result)

    result = check_rule_9b(tokens, punctuation_map)
    if result:
        failures.append(result)

    result = check_rule_9c(tokens, punctuation_map)
    if result:
        failures.append(result)

    result = check_rule_11(tokens)
    if result:
        failures.append(result)

    result = check_rule_12(tokens)
    if result:
        failures.append(result)

    return ", ".join(failures) if failures else None


def build_numeric_validation_conditions(rules_config, array_fields):
    """
    Build a list of (spark_condition, reason_string) from NUMERIC_VALIDATION_RULES.
    Each condition is a Column expression that is True when the rule FAILS.
    Only fields present in array_fields are checked.
    """
    emergency_vals = ", ".join(f"'{v}'" for v in EMERGENCY_NUMBERS)
    year_lo, year_hi = YEAR_RANGE

    conditions = []
    for field, rules in rules_config.items():
        if field not in array_fields:
            continue
        # Collect rules explicitly disabled via (rule_name, False)
        suppressed = {r[0] for r in rules if len(r) > 1 and r[1] is False}
        for rule_spec in rules:
            rule_name = rule_spec[0]
            if len(rule_spec) > 1 and rule_spec[1] is False:
                continue
            if rule_name in suppressed:
                continue
            reason = f"{rule_name}({field})"

            if rule_name == "no_negatives":
                cond = expr(f"exists(`{field}`, x -> cast(x as double) < 0)")
            elif rule_name == "avoid_zero":
                cond = expr(f"exists(`{field}`, x -> cast(x as double) = 0)")
            elif rule_name == "below":
                threshold = rule_spec[1]
                cond = expr(f"exists(`{field}`, x -> cast(x as double) > {threshold})")
            elif rule_name == "must_be_whole_num":
                cond = expr(
                    f"exists(`{field}`, x -> cast(x as double) != "
                    f"floor(cast(x as double)))"
                )
            elif rule_name == "must_be_greater_than":
                other_field = rule_spec[1]
                if other_field not in array_fields:
                    continue
                cond = expr(
                    f"exists(zip_with(`{other_field}`, `{field}`, "
                    f"(a, b) -> cast(b as double) <= cast(a as double)), x -> x = true)"
                )
            elif rule_name == "avoid_emergency_numbers":
                cond = expr(f"exists(`{field}`, x -> x in ({emergency_vals}))")
            elif rule_name == "avoid_years":
                cond = expr(
                    f"exists(`{field}`, x -> cast(x as double) >= {year_lo} "
                    f"and cast(x as double) <= {year_hi} "
                    f"and cast(x as double) = floor(cast(x as double)))"
                )
            elif rule_name == "avoid_times":
                cond = expr(
                    f"exists(`{field}`, x -> "
                    f"(cast(x as int) >= 100 "
                    f"and cast(x as int) <= 2359 "
                    f"and cast(x as int) % 100 in (15, 30, 45) "
                    f"and length(x) >= 3) "
                    f"or (x like '0%' and length(x) >= 2 "
                    f"and x rlike '^[0-9]+$' "
                    f"and cast(x as int) <= 2359))"
                )
            elif rule_name == "only_halfs_and_quarters":
                cond = expr(
                    f"exists(`{field}`, x -> "
                    f"cast(x as double) != floor(cast(x as double)) "
                    f"and cast(x as double) % 1 not in (0.25, 0.5, 0.75))"
                )
            else:
                continue
            conditions.append((cond, reason))
    return conditions


# ---------------------------------------------------------------------------
# Main Function
# ---------------------------------------------------------------------------


def validate_dosage_elements(
    df: DataFrame,
    elements_col: str = "dosage_elements",
) -> DataFrame:
    """
    Validate dosage element sequences and add exclude/dosage_spare/mapped columns.

    Parameters
    ----------
    df : pyspark.sql.DataFrame
        Input DataFrame with a dosage_elements column.
    elements_col : str
        Name of the column containing the parsed element sequence string.

    Returns
    -------
    pyspark.sql.DataFrame
        DataFrame with added columns: exclude, dosage_spare, mapped.
    """

    @pandas_udf("string")
    def _evaluate_rules_udf(series: pd.Series) -> pd.Series:
        return series.apply(evaluate_rules)

    # 1. Grammar rules (preserve any pre-existing exclude)
    rules_result = _evaluate_rules_udf(col_(elements_col))
    if "exclude" in df.columns:
        df = df.withColumn(
            "exclude",
            when(col_("exclude").isNotNull(), col_("exclude")).otherwise(rules_result),
        )
    else:
        df = df.withColumn("exclude", rules_result)

    # 2. ValueXMilli exclusion
    df = df.withColumn(
        "exclude",
        when(
            col_("exclude").isNull() & col_("doseXMilliValueOnly_clean").isNotNull(),
            lit("ValueXmilli"),
        ).otherwise(col_("exclude")),
    )

    # 3. Numeric validation rules
    array_fields = {f.name for f in df.schema.fields if "ArrayType" in str(f.dataType)}
    validation_conditions = build_numeric_validation_conditions(
        NUMERIC_VALIDATION_RULES, array_fields
    )

    exclude_col = col_("exclude")
    for cond, reason in reversed(validation_conditions):
        exclude_col = when(cond & col_("exclude").isNull(), lit(reason)).otherwise(
            exclude_col
        )
    df = df.withColumn("exclude", exclude_col)

    # 4. Spare calculation
    spare = col_(elements_col)
    spare = regexp_replace(spare, r"\(\*\w+\*\)", "")
    spare = regexp_replace(spare, r"\*\w+\*\s*\.", "")
    spare = regexp_replace(spare, r"\*\w+\*\s*\-", "")
    spare = regexp_replace(spare, r"\*\w+\*\s?", "")
    spare = regexp_replace(spare, r"\s{2,}", " ")
    spare = regexp_replace(spare, r"^[\.\-\s]+$", "")
    spare = trim(spare)
    df = df.withColumn("dosage_spare", spare)

    # 5. Mapped column
    any_numeric_fail = lit(False)
    for cond, _ in validation_conditions:
        any_numeric_fail = any_numeric_fail | cond

    excluded_col = col_("excluded") if "excluded" in df.columns else lit(None)
    df = df.withColumn(
        "mapped",
        when(
            col_("doseXMilliValueOnly_clean").isNotNull() | any_numeric_fail,
            lit(False),
        )
        .when(
            col_("exclude").isNull()
            & (excluded_col.isNull() | (trim(excluded_col) == lit("")))
            & ((trim(col_("dosage_spare")) == lit("")) | col_("dosage_spare").isNull()),
            lit(True),
        )
        .otherwise(lit(False)),
    )

    return df
