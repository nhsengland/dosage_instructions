import re
from dataclasses import dataclass

import pandas as pd
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.functions import pandas_udf

from dosage_instructions.model.matcher_classes import DASHABLE_GROUP
import dosage_instructions.model.constants as myconstants

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

RATE_GROUP = frozenset(
    {
        "rateRatio",
        "rateRange",
        "rateQuantity",
    }
)

FREQUENCY_GROUP = frozenset(
    {
        "frequencyBare",
        "frequencyWithMethod",
        "periodElement",
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
    }
)

BOUNDS_GROUP = frozenset(
    {
        "boundsDuration",
        "boundsPeriod",
        "boundsAPeriodStartEnd",
        "count",
        "event",
    }
)

WHEN_GROUP = frozenset(
    {
        "whenBare",
        "whenWithMethod",
    }
)

FOR_AS_NEEDED_GROUP = frozenset(
    {
        "forElement",
        "asNeededCodeableConcept",
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

DASHED_SUFFIX = "Dashed"
DASHED_GROUP = {f"{name}{DASHED_SUFFIX}" for name in DASHABLE_GROUP}

ENDS_WITH_DIGIT_GROUP = frozenset(
    {
        "dose_QuantityValueOnly",
        "dose_QuantityValueAndMaxOnly",
    }
)

STARTS_WITH_DIGIT_GROUP = frozenset(
    {
        "frequencyBare",
        "dose_QuantityValueOnly",
        "dose_QuantityValueAndMaxOnly",
        "doseRange",
        "doseXMilliValueOnly",
        "milligramMax",
        "milligramValue",
        "whenBare",
        "doseQuantity",
        "count",
    }
)


LOGICAL_GROUPS = {
    "Dose": DOSE_GROUP,
    "Rate": RATE_GROUP,
    "Frequency": FREQUENCY_GROUP,
    "AsNeeded": AS_NEEDED_GROUP,
    "Action": ACTION_GROUP,
    "Duration": DURATION_GROUP,
    "Bounds": BOUNDS_GROUP,  # includes count and event
    "When": WHEN_GROUP,
    "ForAsNeeded": FOR_AS_NEEDED_GROUP,
    "MaxDose": MAX_DOSE_GROUP,
    "ToBeTaken": TO_BE_TAKEN_GROUP,
}


# ---------------------------------------------------------------------------
# Token Parser
# ---------------------------------------------------------------------------


@dataclass
class Token:
    name: str | None
    bracketed: bool = (
        False  # Legacy field — always False now (parens treated as sentence boundaries)
    )
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

    Parenthesised elements like ``(*milligramValue*)`` are treated as active
    tokens in their own sentence — i.e. the opening parenthesis acts like a
    sentence boundary before the element and the closing parenthesis acts like
    one after.  This means:
      - They COUNT toward structural rules (S2, S3).
      - Ordering rules (O5, O6, O7) and extras rules (O8/O9/O10) are RESCUED
        by the sentence boundary, just as they would be across a full stop.
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
            # Parenthesised element: treat as its own sentence (boundary before & after)
            sentence_idx += 1
            tokens.append(
                Token(name=match.group(1), bracketed=False, sentence_idx=sentence_idx)
            )
            if pending_punct:
                punctuation_map[len(tokens) - 1] = pending_punct
                pending_punct = set()
            sentence_idx += 1
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


def is_dashed_name(name: str) -> bool:
    return isinstance(name, str) and name.endswith(DASHED_SUFFIX)


def base_name(name: str) -> str:
    return name[: -len(DASHED_SUFFIX)] if is_dashed_name(name) else name


def add_dashed_suffix(name: str) -> str:
    return f"{name}{DASHED_SUFFIX}" if not is_dashed_name(name) else name


# ---------------------------------------------------------------------------
# Rule Checkers
# ---------------------------------------------------------------------------
#
# IMPORTANT: base_name() convention
# ==================================
# Elements may appear in dosage_elements as either their base form (e.g.
# "doseRange") or with a "Dashed" suffix (e.g. "doseRangeDashed") when the
# element was captured via a dash-separated pattern (e.g. "1-2 tablets").
#
# When checking group membership (is this a dose? a frequency? etc.), ALWAYS
# use base_name(e) to strip the suffix so dashed variants are recognised:
#     base_name(e) in DOSE_GROUP        ← correct
#     e in DOSE_GROUP                   ← WRONG: misses doseRangeDashed
#
# When checking for a SPECIFIC element by exact name (e.g. "methodDirect",
# "dayOfWeek") where dashed variants cannot exist (the element is never in
# DASHABLE_GROUP), raw name comparison is safe:
#     "methodDirect" in active          ← safe: methodDirect is never dashed
#     "dayOfWeek" in active             ← safe: dayOfWeek is never dashed
#
# When checking if an element IS dashed (rules S5/S6), use the raw name
# intentionally — checking t.name in DASHED_GROUP is correct because we
# specifically want to know whether the token carries the suffix.
# ---------------------------------------------------------------------------


# ═══════════════════════════════════════════════════════════════════════════════
# STRUCTURAL RULES (S1–S8)
# These check whether the combination of elements forms a valid instruction.
# ═══════════════════════════════════════════════════════════════════════════════


def check_rule_S2(tokens: list[Token]) -> str | None:
    """S2: Must have (Amount OR Action) AND Timing, OR contain 'as directed'/'as needed'."""
    active = get_active_elements(tokens)
    has_amount = any(
        base_name(e) in DOSE_GROUP or base_name(e) in RATE_GROUP for e in active
    )
    has_action = any(base_name(e) in ACTION_GROUP for e in active)
    has_timing = any(base_name(e) in TIMING_GROUP for e in active)
    has_as_directed = any(base_name(e) == "extrasAsDirected" for e in active)
    has_as_needed = any(
        base_name(e) in {"asNeededBoolean", "asNeededCodeableConcept"} for e in active
    )

    if (has_amount or has_action) and has_timing:
        return None
    if has_as_directed or has_as_needed:
        return None
    return "S2"


def check_rule_S3(tokens: list[Token]) -> str | None:
    """S3: Only one element per logical group (full instruction).

    Parenthesised elements are now active (in their own sentence), so they
    count toward this rule for ALL groups — e.g. "20 drops (20mg)" has both
    doseQuantity and milligramValue, triggering S3.
    """
    active = get_active_elements(tokens)

    for group_name, members in LOGICAL_GROUPS.items():
        found = [e for e in active if base_name(e) in members]
        if len(found) <= 1:
            continue
        return "S3"
    return None


def check_rule_S5(tokens: list[Token], punctuation_map: dict) -> str | None:
    """S5: Dashed element present but no dose element — ambiguous.

    A dashed range (e.g. "1-2") exists but there is no dose element anywhere,
    so it's unclear whether "1 - 2 times every day" is a dose range or
    frequency range.
    """
    active_tokens = get_active_tokens(tokens)

    has_dashed = any(t.name in DASHED_GROUP for t in active_tokens)
    has_dose = any(base_name(t.name) in DOSE_GROUP for t in active_tokens)

    if has_dashed and not has_dose:
        return "S5"

    return None


def check_rule_S6(tokens: list[Token], punctuation_map: dict) -> str | None:
    """S6: Adjacent digit-ending + digit-starting elements separated by dash — ambiguous.

    If an ENDS_WITH_DIGIT_GROUP token is followed by a STARTS_WITH_DIGIT_GROUP
    token and the punctuation before the right-hand token includes a dash,
    it's unclear where one element ends and another begins.
    """
    active_tokens = get_active_tokens(tokens)

    token_to_idx = {id(tok): i for i, tok in enumerate(tokens)}

    for left_tok, right_tok in zip(active_tokens, active_tokens[1:]):
        if base_name(left_tok.name) not in ENDS_WITH_DIGIT_GROUP:
            continue
        if base_name(right_tok.name) not in STARTS_WITH_DIGIT_GROUP:
            continue
        right_all_idx = token_to_idx[id(right_tok)]
        punct_before_right = punctuation_map.get(right_all_idx, set())
        if "-" in punct_before_right:
            return "S6"

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# ORDERING RULES (O1–O10)
# These check that elements appear in a clinically logical sequence.
# ═══════════════════════════════════════════════════════════════════════════════


def check_rule_O1(tokens: list[Token]) -> str | None:
    """O1: At most one element from the 'to be taken' group per sentence."""
    sentence_elements = get_sentence_elements(tokens)
    for sent in sentence_elements:
        count = sum(1 for e in sent if e in TO_BE_TAKEN_GROUP)
        if count > 1:
            return "O1"
    return None


def check_rule_O2(tokens: list[Token]) -> str | None:
    """O2: MethodDirect + 'to be taken' element: methodDirect must come first and not adjacent."""
    active = get_active_elements(tokens)
    if "methodDirect" not in active:
        return None
    tbt_indices = [i for i, e in enumerate(active) if e in TO_BE_TAKEN_GROUP]
    if not tbt_indices:
        return None
    md_idx = active.index("methodDirect")
    for tbt_idx in tbt_indices:
        if md_idx > tbt_idx:
            return "O2"
        if tbt_idx == md_idx + 1:
            return "O2"
    return None


def check_rule_O3(tokens: list[Token]) -> str | None:
    """O3: MethodDirect + MethodPassive is always invalid."""
    active = get_active_elements(tokens)
    if "methodDirect" in active and "methodPassive" in active:
        return "O3"
    return None


def check_rule_O4(tokens: list[Token]) -> str | None:
    """O4: MethodDirect must not follow a dose element (per sentence)."""
    sentence_elements = get_sentence_elements(tokens)
    for sent in sentence_elements:
        if "methodDirect" not in sent:
            continue
        md_idx = sent.index("methodDirect")
        for i in range(md_idx):
            if base_name(sent[i]) in DOSE_GROUP:
                return "O4"
    return None


def check_rule_O5(tokens: list[Token], punctuation_map: dict) -> str | None:
    """O5: Dose before frequency (rescued by full stop or comma/dash at boundary)."""
    active_tokens = get_active_tokens(tokens)
    freq_indices = [
        i for i, t in enumerate(active_tokens) if base_name(t.name) in FREQUENCY_GROUP
    ]
    dose_indices = [
        i for i, t in enumerate(active_tokens) if base_name(t.name) in DOSE_GROUP
    ]

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
                return "O5"
    return None


def check_rule_O6(tokens: list[Token], punctuation_map: dict) -> str | None:
    """O6: WhenBare/Site before any dose element -> AMBIGUOUS (rescued by full stop or comma/dash)."""
    active_tokens = get_active_tokens(tokens)
    problematic = {"whenBare", "site"}
    prob_indices = [
        i for i, t in enumerate(active_tokens) if base_name(t.name) in problematic
    ]
    dose_indices = [
        i for i, t in enumerate(active_tokens) if base_name(t.name) in DOSE_GROUP
    ]

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
                return "O6"
    return None


def check_rule_O7(tokens: list[Token], punctuation_map: dict) -> str | None:
    """O7: ForElement/AsNeeded before both dose AND frequency -> AMBIGUOUS."""
    active_tokens = get_active_tokens(tokens)
    early_elements = {"forElement", "asNeededBoolean", "asNeededCodeableConcept"}

    early_indices = [
        i for i, t in enumerate(active_tokens) if base_name(t.name) in early_elements
    ]
    dose_indices = [
        i for i, t in enumerate(active_tokens) if base_name(t.name) in DOSE_GROUP
    ]
    freq_indices = [
        i for i, t in enumerate(active_tokens) if base_name(t.name) in FREQUENCY_GROUP
    ]

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
            return "O7"
    return None


def check_rule_O8(tokens: list[Token], punctuation_map: dict) -> str | None:
    """O8: ExtrasALTER present -> INVALID (unless rescued by full stop, comma, or dash)."""
    active_tokens = get_active_tokens(tokens)
    se_tokens = [t for t in active_tokens if base_name(t.name) == "extrasALTER"]
    if not se_tokens:
        return None

    for se_tok in se_tokens:
        other_core = [
            t
            for t in active_tokens
            if base_name(t.name) != "extrasALTER"
            and base_name(t.name)
            not in ("extrasPAUSE", "extras", "extrasAsDirected", "extras_b")
        ]
        if not other_core:
            return "O8"
        se_all_idx = tokens.index(se_tok)
        for ct in other_core:
            if in_different_sentences(se_tok, ct):
                continue
            ct_all_idx = tokens.index(ct)
            if has_punct_between(se_all_idx, ct_all_idx, punctuation_map, {",", "-"}):
                continue
            return "O8"
    return None


def check_rule_O9(tokens: list[Token], punctuation_map: dict) -> str | None:
    """O9: ExtrasPAUSE present -> AMBIGUOUS (unless rescued by full stop, comma, or dash)."""
    active_tokens = get_active_tokens(tokens)
    info_tokens = [t for t in active_tokens if base_name(t.name) == "extrasPAUSE"]
    if not info_tokens:
        return None

    for info_tok in info_tokens:
        other_core = [
            t
            for t in active_tokens
            if base_name(t.name)
            not in (
                "extrasPAUSE",
                "extrasALTER",
                "extras",
                "extrasAsDirected",
                "extras_b",
            )
        ]
        if not other_core:
            return "O9"
        info_all_idx = tokens.index(info_tok)
        for ct in other_core:
            if in_different_sentences(info_tok, ct):
                continue
            ct_all_idx = tokens.index(ct)
            if has_punct_between(info_all_idx, ct_all_idx, punctuation_map, {",", "-"}):
                continue
            return "O9"
    return None


def check_rule_O10(tokens: list[Token], punctuation_map: dict) -> str | None:
    """O10: extras_b present -> AMBIGUOUS (unless rescued by full stop only)."""
    active_tokens = get_active_tokens(tokens)
    info_tokens = [t for t in active_tokens if base_name(t.name) == "extras_b"]
    if not info_tokens:
        return None

    num_sentences = max((t.sentence_idx for t in tokens), default=0) + 1
    if num_sentences <= 1:
        return "O10"

    for info_tok in info_tokens:
        other_core = [
            t
            for t in active_tokens
            if base_name(t.name)
            not in (
                "extrasPAUSE",
                "extrasALTER",
                "extras",
                "extrasAsDirected",
                "extras_b",
            )
        ]
        if not other_core:
            return "O10"
        all_in_different = all(
            in_different_sentences(info_tok, ct) for ct in other_core
        )
        if not all_in_different:
            return "O10"
    return None


# ---------------------------------------------------------------------------
# Core Evaluator
# ---------------------------------------------------------------------------


def evaluate_rules(elements_str: str | None) -> str | None:
    """Evaluate all rules against a dosage_elements string. Returns exclusion reason or None."""
    if not elements_str or not elements_str.strip():
        return None

    tokens, has_free_text, punctuation_map = parse_elements(elements_str)

    if has_free_text:
        return "grammar_fail: S1"

    if not tokens:
        return "grammar_fail: S7"

    failures = []

    # ── Structural rules ──────────────────────────────────────────────────────
    result = check_rule_S2(tokens)
    if result:
        failures.append(result)

    result = check_rule_S3(tokens)
    if result:
        failures.append(result)

    result = check_rule_S5(tokens, punctuation_map)
    if result:
        failures.append(result)

    result = check_rule_S6(tokens, punctuation_map)
    if result:
        failures.append(result)

    # ── Ordering rules ────────────────────────────────────────────────────────
    result = check_rule_O1(tokens)
    if result:
        failures.append(result)

    result = check_rule_O2(tokens)
    if result:
        failures.append(result)

    result = check_rule_O3(tokens)
    if result:
        failures.append(result)

    result = check_rule_O4(tokens)
    if result:
        failures.append(result)

    result = check_rule_O5(tokens, punctuation_map)
    if result:
        failures.append(result)

    result = check_rule_O6(tokens, punctuation_map)
    if result:
        failures.append(result)

    result = check_rule_O7(tokens, punctuation_map)
    if result:
        failures.append(result)

    result = check_rule_O8(tokens, punctuation_map)
    if result:
        failures.append(result)

    result = check_rule_O9(tokens, punctuation_map)
    if result:
        failures.append(result)

    result = check_rule_O10(tokens, punctuation_map)
    if result:
        failures.append(result)

    return "grammar_fail: " + ", ".join(failures) if failures else None


def build_numeric_validation_conditions(rules_config, array_fields):
    """
    Build a list of (spark_condition, reason_string) from NUMERIC_VALIDATION_RULES.
    Each condition is a Column expression that is True when the rule FAILS.
    Only fields present in array_fields are checked.
    """
    emergency_vals = ", ".join(f"'{v}'" for v in myconstants.EMERGENCY_NUMBERS)
    year_lo, year_hi = myconstants.YEAR_RANGE

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
            reason = f"numeric_fail: {rule_name}({field})"

            if rule_name == "no_negatives":
                cond = F.expr(f"exists(`{field}`, x -> cast(x as double) < 0)")
            elif rule_name == "avoid_zero":
                cond = F.expr(f"exists(`{field}`, x -> cast(x as double) = 0)")
            elif rule_name == "below":
                threshold = rule_spec[1]
                cond = F.expr(
                    f"exists(`{field}`, x -> cast(x as double) > {threshold})"
                )
            elif rule_name == "must_be_whole_num":
                cond = F.expr(
                    f"exists(`{field}`, x -> cast(x as double) != floor(cast(x as double)))"
                )
            elif rule_name == "must_be_greater_than":
                other_field = rule_spec[1]
                if other_field not in array_fields:
                    continue
                cond = F.expr(
                    f"exists(zip_with(`{other_field}`, `{field}`, "
                    f"(a, b) -> cast(b as double) <= cast(a as double)), x -> x = true)"
                )
            elif rule_name == "avoid_emergency_numbers":
                cond = F.expr(f"exists(`{field}`, x -> x in ({emergency_vals}))")
            elif rule_name == "avoid_years":
                cond = F.expr(
                    f"exists(`{field}`, x -> cast(x as double) >= {year_lo} "
                    f"and cast(x as double) <= {year_hi} "
                    f"and cast(x as double) = floor(cast(x as double)))"
                )
            elif rule_name == "avoid_times":
                cond = F.expr(
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
                cond = F.expr(
                    f"exists(`{field}`, x -> "
                    f"cast(x as double) != floor(cast(x as double)) "
                    f"and cast(x as double) % 1 not in (0.25, 0.5, 0.75))"
                )
            elif rule_name == "must_be_at_least":
                minimum = rule_spec[1]
                cond = F.expr(f"exists(`{field}`, x -> cast(x as double) < {minimum})")
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
    rules_result = _evaluate_rules_udf(F.col(elements_col))
    if "exclude" in df.columns:
        df = df.withColumn(
            "exclude",
            F.when(F.col("exclude").isNotNull(), F.col("exclude")).otherwise(
                rules_result
            ),
        )
    else:
        df = df.withColumn("exclude", rules_result)

    # 2. S8: ValueXMilli exclusion
    df = df.withColumn(
        "exclude",
        F.when(
            F.col("exclude").isNull() & F.col("doseXMilliValueOnly_clean").isNotNull(),
            F.lit("grammar_fail: S8"),
        ).otherwise(F.col("exclude")),
    )

    # 3. Numeric validation rules
    array_fields = {f.name for f in df.schema.fields if "ArrayType" in str(f.dataType)}
    validation_conditions = build_numeric_validation_conditions(
        myconstants.NUMERIC_VALIDATION_RULES, array_fields
    )

    exclude_col = F.col("exclude")
    for cond, reason in reversed(validation_conditions):
        exclude_col = F.when(cond & F.col("exclude").isNull(), F.lit(reason)).otherwise(
            exclude_col
        )
    df = df.withColumn("exclude", exclude_col)

    # 4. Spare calculation
    spare = F.col(elements_col)
    spare = F.regexp_replace(spare, r"\(\*\w+\*\)", "")
    spare = F.regexp_replace(spare, r"\*\w+\*\s*\.", "")
    spare = F.regexp_replace(spare, r"\*\w+\*\s*\-", "")
    spare = F.regexp_replace(spare, r"\*\w+\*\s?", "")
    spare = F.regexp_replace(spare, r"\s{2,}", " ")
    spare = F.regexp_replace(spare, r"^[\.\-\s]+$", "")
    spare = F.trim(spare)
    df = df.withColumn("dosage_spare", spare)

    # 5. Empty elements exclusion
    _has_elements = F.col(elements_col).isNotNull() & (
        F.trim(F.col(elements_col)) != F.lit("")
    )
    df = df.withColumn(
        "exclude",
        F.when(
            F.col("exclude").isNull() & ~_has_elements,
            F.lit("general_fail: too empty"),
        ).otherwise(F.col("exclude")),
    )

    # 6. Mapped column
    any_numeric_fail = F.lit(False)
    for cond, _ in validation_conditions:
        any_numeric_fail = any_numeric_fail | cond

    _has_exclude = F.col("exclude").isNotNull() & (
        F.trim(F.col("exclude")) != F.lit("")
    )

    df = df.withColumn(
        "mapped",
        F.when(
            _has_exclude,
            F.lit(False),
        )
        .when(
            ~_has_elements,
            F.lit(False),
        )
        .when(
            F.col("doseXMilliValueOnly_clean").isNotNull() | any_numeric_fail,
            F.lit(False),
        )
        .when(
            (F.trim(F.col("dosage_spare")) == F.lit(""))
            | F.col("dosage_spare").isNull(),
            F.lit(True),
        )
        .otherwise(F.lit(False)),
    )
    return df
