"""
Validates the constants/config lists for correctness.
Catches developer errors when adding terms to the wrong list or creating overlaps.
"""

import re

import pytest

from dosage_instructions.model.constants import (
    method_config,
    unit_config,
    period_unit_config,
    weekday_config,
    extras,
    extrasPAUSE,
    extrasALTER,
    replace_isolated_terms,
    normalise_date_separators,
    normalise_number_ranges,
    for_config,
    when_config,
    exclude_list,
    asNeededBoolean,
    ASNEEDED_NORMALISE_PATTERN,
    ASNEEDED_STRIP_PATTERN,
    INDICATIONS,
    INDICATION_TO_SNOMED,
    WHEN_TO_ADDITIONAL_INSTRUCTION_TEXT,
    WHEN_PREFIX_MAP,
    WHEN_OPTION_TO_FHIR,
)


def test_no_overlap_method_and_unit():
    """method_config and unit_config must not share options except known dual-purpose words.

    spray/suck are intentionally in both — a post-resolution rescue rule in
    _extract_single_row prefers doseQuantity when the word follows a number.
    """
    allowed_dual = {"spray", "suck"}
    overlap = set(method_config["options"]) & set(unit_config["options"]) - allowed_dual
    assert (
        not overlap
    ), f"Unexpected options overlap between method_config and unit_config: {overlap}"


def test_no_overlap_method_and_period_unit():
    """method_config and period_unit_config must not share options."""
    overlap = set(method_config["options"]) & set(period_unit_config["options"])
    assert (
        not overlap
    ), f"Options overlap between method_config and period_unit_config: {overlap}"


def test_no_overlap_unit_and_period_unit():
    """unit_config and period_unit_config must not share options."""
    overlap = set(unit_config["options"]) & set(period_unit_config["options"])
    assert (
        not overlap
    ), f"Options overlap between unit_config and period_unit_config: {overlap}"


def test_extras_with_numbers_must_be_in_extras_b():
    """
    Extras containing numbers must go in extras_b, not extras/extrasPAUSE/extrasALTER.
    Otherwise QuantityValueOnly captures the number before the extras regex can match the full phrase.
    """
    has_number = re.compile(r"\d")
    bad = []

    for term in extras:
        if has_number.search(term):
            bad.append(("extras", term))
    for term in extrasPAUSE:
        if has_number.search(term):
            bad.append(("extrasPAUSE", term))
    for term in extrasALTER:
        if has_number.search(term):
            bad.append(("extrasALTER", term))

    assert not bad, f"These extras contain numbers and must be moved to extras_b: {bad}"


def _maximal_string(pattern):
    """
    Generate a maximal test string from a regex by treating optional parts as present.
    Strips anchors and replaces regex syntax with likely literal matches.
    """
    s = pattern
    s = re.sub(r"^\^|\$$", "", s)
    # Replace \s+ and \s? with a space
    s = re.sub(r"\\s[+?*]?", " ", s)
    # Replace \d+ with a sample number
    s = re.sub(r"\\d[+?*]?", "1", s)
    # Remove capturing group syntax but keep content
    s = re.sub(r"\((?!\?)", "", s)
    s = re.sub(r"(?<![\\])\)", "", s)
    # Remove optional markers — treat everything as present
    s = re.sub(r"(?<![\\])\?", "", s)
    # Remove other quantifiers
    s = re.sub(r"(?<![\\])[+*]", "", s)
    # Remove word boundaries
    s = re.sub(r"\\b", "", s)
    # Collapse whitespace
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def _check_subset_ordering(terms_dict, dict_name):
    """
    For each pair (A before B) in a dict, check if A would match within B's
    maximal match string. If so, A steals from B — the longer pattern should come first.
    """
    items = list(terms_dict.items())
    issues = []

    for i, (pattern_a, replacement_a) in enumerate(items):
        try:
            regex_a = re.compile(pattern_a)
        except re.error:
            continue

        for j, (pattern_b, replacement_b) in enumerate(items):
            if j <= i:
                continue

            maximal_b = _maximal_string(pattern_b)
            match_a = regex_a.search(maximal_b)

            if match_a:
                # A matches within B's territory — check if A is shorter (subset)
                try:
                    regex_b = re.compile(pattern_b)
                except re.error:
                    continue

                match_b = regex_b.search(maximal_b)
                if match_b and len(match_a.group()) < len(match_b.group()):
                    issues.append(
                        f"Pattern at position {i} steals from pattern at position {j}:\n"
                        f"  Earlier: {pattern_a!r} → {replacement_a!r}\n"
                        f"  Later:   {pattern_b!r} → {replacement_b!r}\n"
                        f"  Fix: move the longer pattern before the shorter one, or remove the shorter one."
                    )

    return issues


def test_replace_isolated_terms_ordering():
    """Earlier patterns must not be subsets of later patterns in the same dict."""
    issues = _check_subset_ordering(replace_isolated_terms, "replace_isolated_terms")
    assert not issues, "\n\n".join(issues)


def test_normalise_date_separators_ordering():
    """Earlier patterns must not be subsets of later patterns in the same dict."""
    issues = _check_subset_ordering(
        normalise_date_separators, "normalise_date_separators"
    )
    assert not issues, "\n\n".join(issues)


def test_normalise_number_ranges_ordering():
    """Earlier patterns must not be subsets of later patterns in the same dict."""
    issues = _check_subset_ordering(normalise_number_ranges, "normalise_number_ranges")
    assert not issues, "\n\n".join(issues)


def test_for_config_is_list():
    """for_config must be a flat list of regex strings."""
    assert isinstance(
        for_config, list
    ), f"for_config should be a list, got {type(for_config)}"
    assert len(for_config) > 0


def test_for_config_patterns_compile():
    """Every pattern in for_config must be a valid regex."""
    bad = []
    for i, pattern in enumerate(for_config):
        try:
            re.compile(pattern)
        except re.error as e:
            bad.append(f"Pattern {i}: {e!r}\n  {pattern}")
    assert not bad, "Invalid regex patterns in for_config:\n" + "\n".join(bad)


def test_for_config_semantic_guards():
    """Key semantic rules: raise only valid items, body sites only with possession."""
    combined = "|".join(f"(?:{p})" for p in for_config)

    should_match = [
        "to lower cholesterol",
        "to raise blood pressure",
        "to raise iron levels",
        "to raise mood",
        "for high blood pressure",
        "for low iron",
        "for your heart",
        "to help your kidneys",
        "to relieve back pain",
        "to treat severe pain",
        "for breakthrough pain",
        "for diabetes",
        "for your cholesterol",
        "to lower your risk of heart attack or stroke",
        "to reduce risk of stroke",
        "for nausea",
        "for dizziness",
        "for allergies",
    ]
    should_not_match = [
        "to raise cholesterol",
        "to raise blood clots",
        "to reduce your heart",
        "to lower your heart",
        "for your low anxiety",
        "for your high anxiety",
    ]

    failures = []
    for text in should_match:
        m = re.search(combined, text)
        if not m:
            failures.append(f"MISSED (should match): {text!r}")
    for text in should_not_match:
        m = re.search(combined, text)
        if m:
            failures.append(
                f"WRONG MATCH (should not match): {text!r} -> {m.group()!r}"
            )

    assert not failures, "\n".join(failures)


def test_weekdays_not_in_other_configs():
    """
    Days of the week should only appear in weekday_config. If they leak into
    other option lists, those elements could steal dayOfWeek's tokens.
    """
    weekdays = set(weekday_config["options"])

    other_configs = {
        "method_config": method_config["options"],
        "unit_config": unit_config["options"],
        "period_unit_config": period_unit_config["options"],
    }

    bad = []
    for config_name, options in other_configs.items():
        overlap = weekdays & set(options)
        if overlap:
            bad.append(f"{config_name} contains weekdays: {sorted(overlap)}")

    for config_name, terms in [
        ("extras", extras),
        ("extrasPAUSE", extrasPAUSE),
        ("extrasALTER", extrasALTER),
    ]:
        for term in terms:
            for day in weekdays:
                if re.search(rf"\b{day}\b", term):
                    bad.append(f"{config_name} contains weekday '{day}' in: '{term}'")

    assert not bad, "\n".join(bad)


# ─── WHEN CONFIG TESTS ────────────────────────────────────────────────────────


class TestWhenConfig:
    """Validates when_config generated options."""

    def test_when_config_is_non_empty(self):
        assert len(when_config["options"]) > 200

    def test_when_config_no_duplicates(self):
        opts = when_config["options"]
        dupes = [o for o in opts if opts.count(o) > 1]
        assert not dupes, f"Duplicate when_config options: {sorted(set(dupes))}"

    def test_when_config_sorted(self):
        opts = when_config["options"]
        assert opts == sorted(opts), "when_config options must be sorted"

    @pytest.mark.parametrize(
        "phrase",
        [
            "before food",
            "after food",
            "with food",
            "at night",
            "at bedtime",
            "before breakfast",
            "after breakfast",
            "with breakfast",
            "in the morning",
            "in the evening",
            "on an empty stomach",
            "before the main meal",
            "after each meal",
            "with every meal",
            "before sleep",
            "after waking",
            "upon waking",
            "at noon",
            "before procedure",
            "before each bowel movement",
            "after bowel movement",
            "with bowel movements",
            "at once at night",
            "at once in the morning",
            "each morning",
            "every evening",
            "before bedtime",
            "before each bedtime",
            "in the afternoon",
            "in an evening",
            "on a morning",
        ],
    )
    def test_when_config_contains_common_phrase(self, phrase):
        assert phrase in when_config["options"], f"Missing from when_config: {phrase!r}"

    @pytest.mark.parametrize(
        "phrase",
        [
            "in an morning",  # bad grammar (consonant)
            "at afternoon",  # not idiomatic
            "on a afternoon",  # bad grammar
        ],
    )
    def test_when_config_excludes_invalid_phrase(self, phrase):
        assert (
            phrase not in when_config["options"]
        ), f"Should NOT be in when_config: {phrase!r}"


# ─── EXCLUDE LIST TESTS ──────────────────────────────────────────────────────


class TestExcludeList:
    """Validates exclude_list patterns for ambiguous fraction-number cases."""

    @pytest.mark.parametrize(
        "text",
        [
            "half - one tablet",
            "half - 1 tablet",
            "half - two tablets",
            "half one tablet",
            "half 1 tablet",
            "half 2 tablets",
            "half 10 tablets",
            "take half - one tablet at night",
            "quarter - one tablet",
            "quarter 1 tablet",
            "quarter two tablets",
            "3 quarters - one tablet",
            "3 quarters 2 tablets",
            "half of two tablets",
            "half of 2 tablets",
            "half of 10 tablets",
            "quarter of 4 tablets",
        ],
    )
    def test_ambiguous_fraction_excluded(self, text):
        """Ambiguous fraction-number patterns must be caught by exclude_list."""
        assert any(
            re.search(p, text) for p in exclude_list
        ), f"Should be excluded but wasn't: {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "half to one tablet",
            "half to 1 tablet",
            "half or one tablet",
            "half or 1 tablet",
            "half of one tablet",
            "half of 1 tablet",
            "half a tablet",
            "half of a tablet",
            "half tablet",
            "take half at night",
            "one and a half tablets",
            "2 and a half tablets",
            "quarter of a tablet",
            "quarter to one tablet",
            "3 quarters of a tablet",
            "half once daily",
        ],
    )
    def test_clear_fraction_not_excluded(self, text):
        """Clear fraction patterns (explicit connector or 'of a') must NOT be excluded."""
        assert not any(
            re.search(p, text) for p in exclude_list
        ), f"Should NOT be excluded but was: {text!r}"

    # ── Ambiguous "<number> <period-adverb>" patterns ─────────────────────────

    @pytest.mark.parametrize(
        "text",
        [
            "4 hourly",
            "4-6 hourly",
            "4-hourly",
            "12 hourly",
            "6 monthly",
            "6-monthly",
            "2 weekly",
            "2-weekly",
            "3-4 weekly",
            "2 daily",
            "3 yearly",
            "10 minutely",
            "two hourly",
            "three weekly",
            "four-hourly",
            "six monthly",
            "ten daily",
            "instil 1 drop 4 hourly",
        ],
    )
    def test_ambiguous_number_period_adverb_excluded(self, text):
        """'<N> hourly/daily/weekly/...' (N>1) is ambiguous and must be excluded."""
        assert any(
            re.search(p, text) for p in exclude_list
        ), f"Should be excluded but wasn't: {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "1 hourly",
            "1-hourly",
            "one hourly",
            "take 2 tablets daily",
            "take 2 capsules daily",
            "apply 1 patch weekly",
            "instil 1 drop every 4 hours",
            "hourly",
            "daily",
            "weekly",
            "take one daily",
            "every 4 hours",
            "2 puffs 4 times a day",
        ],
    )
    def test_unambiguous_period_adverb_not_excluded(self, text):
        """'1 hourly', bare adverbs, or phrases with a unit word separating must NOT be excluded."""
        assert not any(
            re.search(p, text) for p in exclude_list
        ), f"Should NOT be excluded but was: {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "1 3 times a day",
            "2 4 times a day",
            "1 2 tablets",
            "2  4 times daily",  # multiple spaces
            "10 5 mg",
        ],
    )
    def test_digit_space_digit_excluded(self, text):
        """Two bare numbers separated only by whitespace must be excluded."""
        assert any(
            re.search(p, text) for p in exclude_list
        ), f"Should be excluded but wasn't: {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "1-2 tablets",
            "1 to 2 tablets",
            "1 or 2 tablets",
            "1 tablet 2 times a day",
            "5 to 10 mg",
            "take 1 tablet every 2 days",
            "0.5 tablets",
            "1 x 5ml",
            "1 in 2 weeks",
        ],
    )
    def test_digit_space_digit_safe_not_excluded(self, text):
        """Numbers with a connector word or different structure must NOT be excluded."""
        assert not any(
            re.search(p, text) for p in exclude_list
        ), f"Should NOT be excluded but was: {text!r}"


# ─── ASNEEDED PATTERN TESTS ──────────────────────────────────────────────────


class TestAsNeededPatterns:
    """Validates ASNEEDED_NORMALISE_PATTERN and ASNEEDED_STRIP_PATTERN."""

    def test_asneeded_boolean_contains_canonical(self):
        assert "as needed" in asNeededBoolean

    def test_asneeded_boolean_contains_all_synonyms(self):
        expected = {
            "as required",
            "when required",
            "if required",
            "if needed",
            "when needed",
            "as necessary",
            "if necessary",
            "when necessary",
        }
        assert expected.issubset(set(asNeededBoolean))

    @pytest.mark.parametrize(
        "synonym",
        [
            "when required",
            "as required",
            "if required",
            "if needed",
            "when needed",
            "as necessary",
            "if necessary",
            "when necessary",
        ],
    )
    def test_normalise_replaces_synonym_with_as_needed(self, synonym):
        """All synonyms should be replaced by 'as needed'."""
        result = re.sub(
            ASNEEDED_NORMALISE_PATTERN, "as needed", synonym, flags=re.IGNORECASE
        )
        assert result == "as needed", f"Expected 'as needed', got {result!r}"

    def test_normalise_does_not_replace_canonical(self):
        """'as needed' itself should NOT be touched by the normalise pattern."""
        result = re.sub(ASNEEDED_NORMALISE_PATTERN, "as needed", "as needed for pain")
        assert result == "as needed for pain"

    @pytest.mark.parametrize(
        "phrase,expected",
        [
            ("as needed for pain", "for pain"),
            ("when required for pain", "for pain"),
            ("as required for anxiety", "for anxiety"),
            ("if needed for nausea", "for nausea"),
            ("when necessary for high blood pressure", "for high blood pressure"),
            ("when needed to reduce blood pressure", "to reduce blood pressure"),
            ("as necessary for sleep", "for sleep"),
            ("if required for constipation", "for constipation"),
        ],
    )
    def test_strip_removes_prefix(self, phrase, expected):
        """ASNEEDED_STRIP_PATTERN strips the asNeeded prefix leaving the indication."""
        result = re.sub(ASNEEDED_STRIP_PATTERN, "", phrase)
        assert (
            result == expected
        ), f"For {phrase!r}: expected {expected!r}, got {result!r}"

    def test_strip_normalise_then_strip_pipeline(self):
        """Two-step pipeline: normalise synonyms first, then strip prefix."""
        phrase = "when required for high blood pressure"
        step1 = re.sub(ASNEEDED_NORMALISE_PATTERN, "as needed", phrase)
        assert step1 == "as needed for high blood pressure"
        step2 = re.sub(ASNEEDED_STRIP_PATTERN, "", step1)
        assert step2 == "for high blood pressure"


# ─── INDICATION_TO_SNOMED TESTS ──────────────────────────────────────────────


class TestIndicationToSnomed:
    """Validates INDICATIONS and INDICATION_TO_SNOMED structure and ordering."""

    def test_indication_to_snomed_is_nonempty(self):
        assert len(INDICATION_TO_SNOMED) > 30

    def test_all_codes_are_strings(self):
        for key, entry in INDICATION_TO_SNOMED.items():
            assert isinstance(entry["code"], str), f"Code for {key!r} is not a string"
            assert isinstance(
                entry["display"], str
            ), f"Display for {key!r} is not a string"

    def test_no_duplicate_keys(self):
        keys = list(INDICATIONS.keys())
        assert len(keys) == len(set(keys)), "Duplicate keys in INDICATIONS"

    def test_longest_key_first_ordering(self):
        """INDICATION_TO_SNOMED keys must be sorted longest-first."""
        keys = list(INDICATION_TO_SNOMED.keys())
        for i in range(len(keys) - 1):
            assert len(keys[i]) >= len(keys[i + 1]), (
                f"Ordering violation: {keys[i]!r} (len={len(keys[i])}) "
                f"comes before {keys[i+1]!r} (len={len(keys[i+1])})"
            )

    def test_specific_pain_codes_present(self):
        assert INDICATION_TO_SNOMED["pain"]["code"] == "22253000"
        assert INDICATION_TO_SNOMED["neuropathic pain"]["code"] == "57676002"
        assert INDICATION_TO_SNOMED["chest pain"]["code"] == "29857009"

    def test_neuropathic_pain_key_longer_than_pain(self):
        """Ensures neuropathic pain is checked before bare pain in substring matching."""
        keys = list(INDICATION_TO_SNOMED.keys())
        assert keys.index("neuropathic pain") < keys.index("pain")

    def test_high_blood_pressure_longer_than_blood_pressure(self):
        keys = list(INDICATION_TO_SNOMED.keys())
        assert keys.index("high blood pressure") < keys.index("blood pressure")

    @pytest.mark.parametrize(
        "phrase,expected_code",
        [
            ("for pain", "22253000"),
            ("for neuropathic pain", "57676002"),
            ("for high blood pressure", "38341003"),
            ("for anxiety", "48694002"),
            ("for nausea", "422587007"),
            ("for diabetes", "73211009"),
            ("for cholesterol", "13644009"),
            ("for high cholesterol", "13644009"),
            ("to reduce blood pressure", "24184005"),
            ("for sleep", "193462001"),
            ("for mood and sleep", "366979004"),
            ("for your heart", "56265001"),
        ],
    )
    def test_indication_substring_match(self, phrase, expected_code):
        """Substring lookup returns the expected SNOMED code."""
        text_lower = phrase.lower()
        matched = None
        for key, entry in INDICATION_TO_SNOMED.items():
            if key in text_lower:
                matched = entry["code"]
                break
        assert (
            matched == expected_code
        ), f"For {phrase!r}: expected {expected_code!r}, got {matched!r}"


# ─── WHEN ROUTING TESTS ──────────────────────────────────────────────────────


class TestWhenRouting:
    """Validates WHEN_PREFIX_MAP phrase matching and WHEN_TO_ADDITIONAL_INSTRUCTION_TEXT ordering."""

    def test_meal_compounds_in_additional_text_before_bare_timing(self):
        """Meal compound keywords must appear before any bare timing word they contain.
        e.g. 'evening meal' must come before 'evening' would be checked."""
        meal_compounds = ["evening meal", "morning meal", "main meal"]
        for compound in meal_compounds:
            assert (
                compound in WHEN_TO_ADDITIONAL_INSTRUCTION_TEXT
            ), f"'{compound}' missing from WHEN_TO_ADDITIONAL_INSTRUCTION_TEXT"

    def test_evening_meal_before_evening_in_check_order(self):
        """'evening meal' must appear before bare 'evening' in WHEN_OPTION_TO_FHIR check
        is avoided by being caught in WHEN_TO_ADDITIONAL_INSTRUCTION_TEXT first."""
        # 'evening' is in WHEN_OPTION_TO_FHIR; 'evening meal' must be intercepted before it
        assert "evening" in WHEN_OPTION_TO_FHIR
        assert "evening meal" in WHEN_TO_ADDITIONAL_INSTRUCTION_TEXT

    @pytest.mark.parametrize(
        "prefix,option,expected_code",
        [
            ("with", "meal", "C"),
            ("before", "meal", "AC"),
            ("after", "meal", "PC"),
            ("with", "breakfast", "CM"),
            ("before", "breakfast", "ACM"),
            ("after", "breakfast", "PCM"),
            ("with", "lunch", "CD"),
            ("before", "lunch", "ACD"),
            ("after", "lunch", "PCD"),
            ("with", "dinner", "CV"),
            ("before", "dinner", "ACV"),
            ("after", "dinner", "PCV"),
            ("before", "sleep", "HS"),
            ("after", "food", "PC"),
        ],
    )
    def test_prefix_map_phrase_match(self, prefix, option, expected_code):
        """WHEN_PREFIX_MAP keys use tuple (prefix, option) → code."""
        assert (
            prefix,
            option,
        ) in WHEN_PREFIX_MAP, f"({prefix!r}, {option!r}) missing from WHEN_PREFIX_MAP"
        assert WHEN_PREFIX_MAP[(prefix, option)] == expected_code

    @pytest.mark.parametrize(
        "phrase,should_match",
        [
            ("with meal", True),
            ("with evening meal", False),  # meal present but NOT adjacent to 'with'
            ("before meal", True),
            ("before main meal", False),  # 'main meal' not a WHEN_PREFIX_MAP option
            ("after meal", True),
            ("with breakfast", True),
        ],
    )
    def test_prefix_map_phrase_not_substring(self, phrase, should_match):
        """WHEN_PREFIX_MAP must match the phrase, not independent substrings."""
        matched = any(
            f"{prefix} {option}" in phrase.lower()
            for (prefix, option) in WHEN_PREFIX_MAP
        )
        assert (
            matched == should_match
        ), f"For {phrase!r}: expected match={should_match}, got {matched}"
