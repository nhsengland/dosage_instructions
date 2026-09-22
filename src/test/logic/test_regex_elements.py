"""
Tests for regex-extracted elements (route, site, extras, asNeededBoolean).

These elements use reg_extract_and_tag_element (regex, not spaCy matchers).
They grab text verbatim — no cleaning/formatting applied.

Test cases live in to_test.py under element_specific — same as spaCy elements.
"""

import re
import pytest

from dosage_instructions.to_test import element_specific
from dosage_instructions.model.constants import (
    route,
    site_config,
    asNeededBoolean,
    extras,
    extras_asDirected,
    extrasPAUSE,
    extrasALTER,
    extras_b,
    for_config,
)

# asNeededCodeableConcept patterns are the cross-product of asNeededBoolean × for_config,
# exactly as built in matcher_run._extract_regex_elements.
_asNeededCC = [aNB + " " + forE for forE in for_config for aNB in asNeededBoolean]

REGEX_ELEMENTS = {
    "route": route,
    "asNeededBoolean": asNeededBoolean,
    "asNeededCodeableConcept": _asNeededCC,
    "forElement": for_config,
    "extras": extras,
    "extrasAsDirected": extras_asDirected,
    "extrasALTER": extrasALTER,
    "extrasPAUSE": extrasPAUSE,
    "extras_b": extras_b,
}


def _build_pattern(options):
    return "|".join(options)


# ─── Collect parametrised cases ───────────────────────────────────────────────


def collect_regex_capture_cases():
    cases = []
    for elem_key, options in REGEX_ELEMENTS.items():
        tests = element_specific.get(elem_key, {})
        pattern = _build_pattern(options)
        for input_text, expected in tests.get("capture", {}).items():
            cases.append(
                pytest.param(
                    pattern,
                    input_text,
                    expected,
                    id=f"{elem_key} | capture | {input_text}",
                )
            )
    return cases


def collect_regex_ignore_cases():
    cases = []
    for elem_key, options in REGEX_ELEMENTS.items():
        tests = element_specific.get(elem_key, {})
        pattern = _build_pattern(options)
        for input_text in tests.get("ignore", []):
            cases.append(
                pytest.param(
                    pattern,
                    input_text,
                    id=f"{elem_key} | ignore | {input_text}",
                )
            )
    return cases


def collect_regex_partial_cases():
    cases = []
    for elem_key, options in REGEX_ELEMENTS.items():
        tests = element_specific.get(elem_key, {})
        pattern = _build_pattern(options)
        for input_text, parts in tests.get("partial", {}).items():
            cases.append(
                pytest.param(
                    pattern,
                    input_text,
                    parts[0],
                    parts[1],
                    id=f"{elem_key} | partial | {input_text}",
                )
            )
    return cases


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pattern,input_text,expected", collect_regex_capture_cases())
def test_regex_element_captures(pattern, input_text, expected):
    """Regex pattern should match and extract the expected substring."""
    match = re.search(pattern, input_text)
    assert (
        match is not None
    ), f"\n  Input:    '{input_text}'\n  Expected: '{expected}'\n  Got:      no match"
    assert (
        match.group(0) == expected
    ), f"\n  Input:    '{input_text}'\n  Expected: '{expected}'\n  Got:      '{match.group(0)}'"


@pytest.mark.parametrize("pattern,input_text", collect_regex_ignore_cases())
def test_regex_element_ignores(pattern, input_text):
    """Regex pattern should NOT match this input."""
    match = re.search(pattern, input_text)
    assert (
        match is None
    ), f"\n  Input:    '{input_text}'\n  Expected: no match\n  Got:      '{match.group(0)}'"


@pytest.mark.parametrize(
    "pattern,input_text,not_captured,captured", collect_regex_partial_cases()
)
def test_regex_element_partial(pattern, input_text, not_captured, captured):
    """Regex captures part of the input; the rest is left over."""
    match = re.search(pattern, input_text)
    assert (
        match is not None
    ), f"\n  Input:    '{input_text}'\n  Expected captured: '{captured}'\n  Got:      no match"
    assert (
        match.group(0) == captured
    ), f"\n  Input:    '{input_text}'\n  Expected captured: '{captured}'\n  Got captured:      '{match.group(0)}'"
    remainder = (input_text[: match.start()] + input_text[match.end() :]).strip()
    # Normalise multiple spaces — removing a mid-word match leaves a double space
    # which the real pipeline also normalises away.
    remainder = re.sub(r" {2,}", " ", remainder)
    assert (
        remainder == not_captured
    ), f"\n  Input:    '{input_text}'\n  Expected spare: '{not_captured}'\n  Got spare:      '{remainder}'"
