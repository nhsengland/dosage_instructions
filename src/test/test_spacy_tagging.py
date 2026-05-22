"""
Diagnostic utility — not a pass/fail test.

Run with:  pytest tests/test_spacy_tagging.py -s

Prints token-level POS, tag, and lemma for each phrase so you can verify
spaCy is tagging things the way your patterns expect.
"""

import pytest

PHRASES = [
    "litre per minute",
    "litres per minute",
    "microgram per kilogram per hour",
    "at a rate of 1 to 2 litres per minute",
    "at a rate of 1 to 4 litres per minute",
    "to be taked with food",
]


def test_show_tagging(nlp):
    for phrase in PHRASES:
        doc = nlp(phrase)
        print(f"\n{'─' * 60}")
        print(f"  {phrase}")
        print(f"  {'TOKEN':<15} {'POS':<8} {'TAG':<8} {'LEMMA':<15}")
        print(f"  {'─' * 50}")
        for token in doc:
            print(
                f"  {token.text:<15} {token.pos_:<8} {token.tag_:<8} {token.lemma_:<15}"
            )
