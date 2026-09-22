"""
Checks that all element types are registered in all the places they need to be.
If you add a new element type, this test will fail until you add it to:
- element_types list (matcher_classes)
- bucket_order (constants)
- element_specific test cases (to_test.py)
"""

import pytest

from dosage_instructions.model.matcher_classes import element_types
from dosage_instructions.model.constants import bucket_order
from dosage_instructions.to_test import element_specific

ELEMENT_TYPE_KEYS = {et.element_key for et in element_types}

# Elements in bucket_order that are NOT in element_types (handled by reg_extract_and_tag_element)
REGEX_ONLY_ELEMENTS = {
    "route",
    "site",
    "asNeededBoolean",
    "asNeededCodeableConcept",
    "forElement",
    "extras",
    "extrasAsDirected",
    "extras_b",
    "extrasPAUSE",
    "extrasALTER",
}


def test_all_element_types_in_bucket_order():
    """Every element type's element_key must appear in bucket_order."""
    missing = ELEMENT_TYPE_KEYS - set(bucket_order)
    assert not missing, f"Element types missing from bucket_order: {sorted(missing)}"


def test_all_element_types_have_test_cases():
    """Every element type must have test cases in to_test.py with both captures and ignores."""
    missing = ELEMENT_TYPE_KEYS - set(element_specific.keys())
    assert (
        not missing
    ), f"Element types missing from element_specific in to_test.py: {sorted(missing)}"

    missing_captures = [
        k
        for k in ELEMENT_TYPE_KEYS
        if k in element_specific and not element_specific[k].get("capture")
    ]
    assert (
        not missing_captures
    ), f"Element types with no capture test cases in to_test.py: {sorted(missing_captures)}"

    missing_ignores = [
        k
        for k in ELEMENT_TYPE_KEYS
        if k in element_specific and not element_specific[k].get("ignore")
    ]
    assert (
        not missing_ignores
    ), f"Element types with no ignore test cases in to_test.py: {sorted(missing_ignores)}"


def test_all_bucket_order_elements_accounted_for():
    """Every element in bucket_order should be either an element type or a known regex-only element."""
    all_known = ELEMENT_TYPE_KEYS | REGEX_ONLY_ELEMENTS
    unknown = set(bucket_order) - all_known
    assert (
        not unknown
    ), f"Elements in bucket_order not recognised as element type or regex-only: {sorted(unknown)}"


def test_no_duplicate_element_keys():
    """No two element types should share the same element_key."""
    keys = [et.element_key for et in element_types]
    duplicates = [k for k in keys if keys.count(k) > 1]
    assert (
        not duplicates
    ), f"Duplicate element_keys in element_types list: {sorted(set(duplicates))}"
