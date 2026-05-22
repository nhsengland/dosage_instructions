"""
Priority order validation test.

Detects which element classes have overlapping patterns (i.e. both match
the same tokens on a probe phrase) and validates that the priority order
in the `classes` list resolves them correctly.

Normal case: the element matching the LONGER span has higher priority (wins).
This is auto-validated — no manual declaration needed.

Exception case: a sub-part element intentionally beats a compound element
(e.g. methodPassive beats frequencyWithMethod). These must be declared in
PRIORITY_EXCEPTIONS in constants.
"""

import pytest

from dosage_instructions.to_test import element_specific
from dosage_instructions.model.matcher_classes import classes
from dosage_instructions.model.constants import PRIORITY_EXCEPTIONS


def test_priority_order_is_correct(nlp, matcher, all_instances, priority_map):
    """
    For each probe phrase from to_test.py, run the raw matcher and find all
    classes whose patterns fire. If two classes overlap on the same tokens,
    verify the priority resolves correctly:
      - Longer span should have higher priority (auto-validated)
      - If shorter span has higher priority, it must be in PRIORITY_EXCEPTIONS
    """
    probe_phrases = set()
    for elem_key, cases in element_specific.items():
        for phrase in cases.get("capture", {}).keys():
            probe_phrases.add(phrase.lower())

    overlaps = {}

    for phrase in sorted(probe_phrases):
        doc = nlp(phrase)
        matches = matcher(doc)

        class_spans = {}
        for match_id, start, end in matches:
            label = doc.vocab.strings[match_id]
            for inst in all_instances:
                if label.startswith(f"{inst.element_key}_"):
                    class_spans.setdefault(inst.element_key, []).append((start, end))
                    break

        keys = list(class_spans.keys())
        for i, a in enumerate(keys):
            for b in keys[i + 1 :]:
                for sa_start, sa_end in class_spans[a]:
                    for sb_start, sb_end in class_spans[b]:
                        a_contains_b = sa_start <= sb_start and sa_end >= sb_end
                        b_contains_a = sb_start <= sa_start and sb_end >= sa_end
                        if a_contains_b or b_contains_a:
                            pair = tuple(sorted([a, b], key=lambda x: priority_map[x]))
                            sa_len = sa_end - sa_start
                            sb_len = sb_end - sb_start
                            if pair[0] == a:
                                higher_len = sa_len
                                lower_len = sb_len
                            else:
                                higher_len = sb_len
                                lower_len = sa_len
                            overlaps.setdefault(pair, []).append(
                                (phrase, higher_len, lower_len)
                            )

    errors = []
    for pair, entries in overlaps.items():
        higher, lower = pair

        higher_wins_by_length = any(h_len >= l_len for _, h_len, l_len in entries)

        if higher_wins_by_length:
            continue

        if pair in PRIORITY_EXCEPTIONS:
            continue

        reversed_pair = (lower, higher)
        if reversed_pair in PRIORITY_EXCEPTIONS:
            errors.append(
                f"Priority violation: PRIORITY_EXCEPTIONS declares {reversed_pair[0]} "
                f"should beat {reversed_pair[1]}, but {higher} currently has higher "
                f"priority. Overlapping on: {[p for p, _, _ in entries[:3]]}"
            )
        else:
            errors.append(
                f"Undeclared exception: {higher} (shorter span) beats {lower} "
                f"(longer span) on: {[p for p, _, _ in entries[:3]]}. "
                f"Add ({higher!r}, {lower!r}) to PRIORITY_EXCEPTIONS in constants."
            )

    assert not errors, "\n\n".join(errors)
