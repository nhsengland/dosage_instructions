"""
Validates the constants/config lists for correctness.
Catches developer errors when adding terms to the wrong list or creating overlaps.
"""

import re

from dosage_instructions.model.constants import (
    for_config,
    method_config,
    unit_config,
    period_unit_config,
    extras,
    extrasPAUSE,
    extrasALTER,
    replace_isolated_terms,
    replace_partofaword_terms,
    weird_terms,
    weekday_config,
)


def test_no_overlap_method_and_unit():
    """method_config and unit_config must not share options (e.g. 'spray')."""
    overlap = set(method_config["options"]) & set(unit_config["options"])
    assert (
        not overlap
    ), f"Options overlap between method_config and unit_config: {overlap}"


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

    assert not bad, (
        f"These extras contain numbers and must be moved to extras_b: " f"{bad}"
    )


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


def _check_subset_ordering(terms_dict, dict_name, only_if_isolated=True):
    """
    For each pair (A before B) in a dict, check if A would match within B's
    maximal match string. If so, A steals from B — the longer pattern should come first.
    """
    items = list(terms_dict.items())
    issues = []

    for i, (pattern_a, replacement_a) in enumerate(items):
        try:
            if only_if_isolated:
                regex_a = re.compile(rf"\b{pattern_a}\b")
            else:
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
                    if only_if_isolated:
                        regex_b = re.compile(rf"\b{pattern_b}\b")
                    else:
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


def test_replace_partofaword_terms_ordering():
    """Earlier patterns must not be subsets of later patterns in the same dict."""
    issues = _check_subset_ordering(
        replace_partofaword_terms, "replace_partofaword_terms"
    )
    assert not issues, "\n\n".join(issues)


def test_weird_terms_ordering():
    """Earlier patterns must not be subsets of later patterns in the same dict."""
    issues = _check_subset_ordering(weird_terms, "weird_terms")
    assert not issues, "\n\n".join(issues)


def test_for_config_no_prefix_subsets():
    """
    Shorter phrases must not come before longer phrases they are a prefix of.
    E.g. 'to prevent blood' before 'to prevent blood clots' would steal the match.
    """
    options = for_config["options"]
    issues = []
    for i, phrase_a in enumerate(options):
        for j, phrase_b in enumerate(options):
            if j <= i:
                continue
            if phrase_b.startswith(phrase_a + " "):
                issues.append(
                    f"Position {i} '{phrase_a}' is a prefix of position {j} '{phrase_b}'. "
                    f"Move '{phrase_b}' before '{phrase_a}'."
                )
    assert not issues, "\n".join(issues)


def test_for_config_no_duplicates():
    """for_config options must not contain duplicate entries."""
    from collections import Counter

    options = for_config["options"]
    counts = Counter(options)
    dupes = {k: v for k, v in counts.items() if v > 1}
    assert not dupes, (
        f"Duplicate entries in for_config options: "
        f"{sorted(f'{k!r} x{v}' for k, v in dupes.items())}"
    )


def test_for_config_no_trailing_prepositions():
    """
    Entries ending in a preposition or article are likely broken fragments
    from list generation that would cause false matches.
    """
    junk_endings = {"in", "on", "of", "the", "a", "an", "at", "is", "it"}
    options = for_config["options"]
    bad = [opt for opt in options if opt.split()[-1] in junk_endings]
    assert not bad, (
        f"for_config entries ending in preposition/article (likely junk): " f"{bad}"
    )


def test_for_config_no_trailing_fragments():
    """Entries must not end with incomplete/meaningless words."""
    bad_endings = {"irritable", "and", "allergic"}
    options = for_config["options"]
    bad = [opt for opt in options if opt.split()[-1] in bad_endings]
    assert not bad, f"for_config entries ending in fragment words: {bad}"


def test_for_config_to_entries_use_base_verb():
    """
    'to' entries should use the base verb form (e.g. 'to reduce', 'to help control'),
    not gerund/participle (e.g. 'to reducing', 'to reduced' are wrong).
    """
    options = for_config["options"]
    helper_words = {"help", "aid", "help aid", "your"}
    bad = []
    for opt in options:
        if not opt.startswith("to "):
            continue
        words = opt.split()
        # Find the action verb (skip "to" and any helper words)
        for i, word in enumerate(words[1:], start=1):
            if word in helper_words:
                continue
            if word.endswith("ing") or word.endswith("ed"):
                bad.append(opt)
            break
    assert not bad, f"'to' entries should use base verb, not -ing/-ed: {bad}"


def test_for_config_for_entries_use_gerund_or_noun():
    """
    'for' entries should use gerund/participle or a noun (e.g. 'for reducing',
    'for pain'), not a bare infinitive (e.g. 'for reduce' is wrong).
    """
    options = for_config["options"]
    helper_words = {"help", "aid", "your", "the"}

    # Collect all -ing verb forms in the list to identify known verbs
    gerunds = {
        opt_word
        for opt in options
        for opt_word in opt.split()
        if opt_word.endswith("ing")
    }
    # Derive base forms from gerunds (e.g. "reducing" -> "reduc", "controlling" -> "controll")
    # Then check if any "for" entry uses that base form
    base_from_gerund = set()
    for g in gerunds:
        if g.endswith("ting"):
            base_from_gerund.add(g[:-4] + "t")  # controlling -> control+ling... hmm
        if g.endswith("ing"):
            base_from_gerund.add(g[:-3])  # reducing -> reduc (partial)
            base_from_gerund.add(g[:-3] + "e")  # reducing -> reduce

    bad = []
    for opt in options:
        if not opt.startswith("for "):
            continue
        words = opt.split()
        for word in words[1:]:
            if word in helper_words:
                continue
            # If this word is a known base verb form, it's likely wrong
            if (
                word in base_from_gerund
                and not word.endswith("ing")
                and not word.endswith("ed")
            ):
                bad.append(opt)
            break
    assert (
        not bad
    ), f"'for' entries should use -ing/-ed form or noun, not bare verb: {bad}"


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
        "for_config": for_config["options"],
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
