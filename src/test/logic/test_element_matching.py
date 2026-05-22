"""
Data-driven element matching tests.

Test cases are defined in dosage_repo/to_test.py under `element_specific`.
Add new cases there — they'll be picked up automatically on next pytest run.

Three test types:
  - test_element_captures: input text SHOULD match the element, producing expected _clean value
  - test_element_ignores:  input text should NOT match the element (result is None)
  - test_element_partial:  element captures part of the input but not all of it

All tests run each element in isolation (its own Matcher instance) so that
priority interactions don't interfere with pattern-level verification.
Elements in ISOLATED_ELEMENTS (from constants) specifically require this
because a higher-priority sub-part would claim their tokens in the full pipeline
— see PRIORITY_EXCEPTIONS in constants for details.
"""

import re

import pytest

from dosage_instructions.to_test import element_specific
from dosage_instructions.model.matcher_classes import _extract_single_row
from dosage_instructions.model.constants import ISOLATED_ELEMENTS
from test.logic.test_regex_elements import REGEX_ELEMENTS

# ─── Collect test cases from to_test.py ───────────────────────────────────────


def collect_capture_cases():
    cases = []
    for elem_key, tests in element_specific.items():
        if elem_key in REGEX_ELEMENTS:
            continue
        for input_text, expected in tests.get("capture", {}).items():
            cases.append(
                pytest.param(
                    elem_key,
                    input_text,
                    expected,
                    id=f"{elem_key} | capture | {input_text}",
                )
            )
    return cases


def collect_ignore_cases():
    cases = []
    for elem_key, tests in element_specific.items():
        if elem_key in REGEX_ELEMENTS:
            continue
        for input_text in tests.get("ignore", []):
            cases.append(
                pytest.param(
                    elem_key,
                    input_text,
                    id=f"{elem_key} | ignore | {input_text}",
                )
            )
    return cases


def collect_partial_cases():
    cases = []
    for elem_key, tests in element_specific.items():
        if elem_key in REGEX_ELEMENTS:
            continue
        for input_text, parts in tests.get("partial", {}).items():
            cases.append(
                pytest.param(
                    elem_key,
                    input_text,
                    parts[0],
                    parts[1],
                    id=f"{elem_key} | partial | {input_text}",
                )
            )
    return cases


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _run_isolated(elem_key, input_text, nlp):
    """Run extraction with only the target element registered (no priority conflicts)."""
    from spacy.matcher import Matcher as SpacyMatcher
    from dosage_instructions.model.matcher_classes import classes

    iso_matcher = SpacyMatcher(nlp.vocab)
    cls = next(c for c in classes if c.element_key == elem_key)
    inst = cls(nlp, iso_matcher)
    instances = [inst]
    by_key = {inst.element_key: inst}
    pri = {inst.element_key: 0}
    return _extract_single_row(input_text, instances, by_key, pri, nlp, iso_matcher)


def _run_full(
    elem_key, input_text, all_instances, instances_by_key, priority_map, nlp, matcher
):
    """Run extraction with all elements (full priority resolution)."""
    return _extract_single_row(
        input_text, all_instances, instances_by_key, priority_map, nlp, matcher
    )


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("elem_key,input_text,expected", collect_capture_cases())
def test_element_captures(
    elem_key,
    input_text,
    expected,
    all_instances,
    instances_by_key,
    priority_map,
    nlp,
    matcher,
):
    """Element should match the input and produce the expected _clean value."""
    if elem_key in ISOLATED_ELEMENTS:
        result = _run_isolated(elem_key, input_text, nlp)
    else:
        result = _run_full(
            elem_key,
            input_text,
            all_instances,
            instances_by_key,
            priority_map,
            nlp,
            matcher,
        )
    actual = result[f"{elem_key}_clean"]
    assert actual == expected, (
        f"\n  Element:  {elem_key}"
        f"\n  Input:    '{input_text}'"
        f"\n  Expected: '{expected}'"
        f"\n  Got:      '{actual}'"
    )


@pytest.mark.parametrize("elem_key,input_text", collect_ignore_cases())
def test_element_ignores(
    elem_key, input_text, all_instances, instances_by_key, priority_map, nlp, matcher
):
    """Element should NOT match this input (_clean should be None)."""
    if elem_key in ISOLATED_ELEMENTS:
        result = _run_isolated(elem_key, input_text, nlp)
    else:
        result = _run_full(
            elem_key,
            input_text,
            all_instances,
            instances_by_key,
            priority_map,
            nlp,
            matcher,
        )
    actual = result[f"{elem_key}_clean"]
    assert actual is None, (
        f"\n  Element:  {elem_key}"
        f"\n  Input:    '{input_text}'"
        f"\n  Expected: None (no match)"
        f"\n  Got:      '{actual}'"
    )


@pytest.mark.parametrize(
    "elem_key,input_text,not_captured,captured", collect_partial_cases()
)
def test_element_partial(elem_key, input_text, not_captured, captured, nlp):
    """Element captures part of the input in isolation; the rest is spare text.
    Always runs isolated — partial tests verify what ONE element does alone."""
    result = _run_isolated(elem_key, input_text, nlp)
    actual_clean = result[f"{elem_key}_clean"]
    spare = re.sub(r"\*\w+\*", "", result["dosage_elements"]).strip()
    assert actual_clean == captured, (
        f"\n  Element:  {elem_key}"
        f"\n  Input:    '{input_text}'"
        f"\n  Expected captured: '{captured}'"
        f"\n  Got captured:      '{actual_clean}'"
    )
    assert spare == not_captured, (
        f"\n  Element:  {elem_key}"
        f"\n  Input:    '{input_text}'"
        f"\n  Expected spare: '{not_captured}'"
        f"\n  Got spare:      '{spare}'"
    )
