"""
Checks that all element classes are registered in all the places they need to be.
If you add a new element class, this test will fail until you add it to:
- classes list (matcher_classes)
- bucket_order (constants)
- element_specific test cases (to_test.py)
"""

import pytest

from dosage_instructions.model.matcher_classes import classes
from dosage_instructions.model.constants import bucket_order
from dosage_instructions.to_test import element_specific

CLASS_ELEMENT_KEYS = {cls.element_key for cls in classes}

# Elements in bucket_order that are NOT matcher classes (handled by reg_extract_and_tag_element)
NON_CLASS_BUCKET_ELEMENTS = {
    "route",
    "site",
    "asNeededBoolean",
    "extras",
    "extras_b",
    "extrasPAUSE",
    "extrasALTER",
}


def test_all_classes_in_bucket_order():
    """Every matcher class element_key must appear in bucket_order."""
    missing = CLASS_ELEMENT_KEYS - set(bucket_order)
    assert not missing, f"Element classes missing from bucket_order: {sorted(missing)}"


def test_all_classes_have_test_cases():
    """Every matcher class element_key must have test cases in to_test.py with both captures and ignores."""
    missing = CLASS_ELEMENT_KEYS - set(element_specific.keys())
    assert (
        not missing
    ), f"Element classes missing from element_specific in to_test.py: {sorted(missing)}"

    missing_captures = [
        k
        for k in CLASS_ELEMENT_KEYS
        if k in element_specific and not element_specific[k].get("capture")
    ]
    assert (
        not missing_captures
    ), f"Element classes with no capture test cases in to_test.py: {sorted(missing_captures)}"

    missing_ignores = [
        k
        for k in CLASS_ELEMENT_KEYS
        if k in element_specific and not element_specific[k].get("ignore")
    ]
    assert (
        not missing_ignores
    ), f"Element classes with no ignore test cases in to_test.py: {sorted(missing_ignores)}"


def test_all_bucket_order_elements_accounted_for():
    """Every element in bucket_order should be either a class or a known non-class element."""
    all_known = CLASS_ELEMENT_KEYS | NON_CLASS_BUCKET_ELEMENTS
    unknown = set(bucket_order) - all_known
    assert (
        not unknown
    ), f"Elements in bucket_order not recognised as class or non-class: {sorted(unknown)}"


def test_no_duplicate_element_keys():
    """No two classes should share the same element_key."""
    keys = [cls.element_key for cls in classes]
    duplicates = [k for k in keys if keys.count(k) > 1]
    assert (
        not duplicates
    ), f"Duplicate element_keys in classes list: {sorted(set(duplicates))}"
