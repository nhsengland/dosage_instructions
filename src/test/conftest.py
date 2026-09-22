import pytest
import spacy
from spacy.matcher import Matcher
from spacy.util import compile_infix_regex


@pytest.fixture(scope="session")
def nlp():
    """Load spaCy model with custom tokenizer (same config as run_model)."""
    _nlp = spacy.load("en_core_web_sm")
    # pinned: en_core_web_sm==3.8.0, spacy==3.8.14 — do not upgrade without re-validating lemmatisation/POS
    infixes = _nlp.Defaults.infixes + [r"\/", r"\-", r"(?<=[0-9])(?=[a-zA-Z])"]
    infix_regex = compile_infix_regex(infixes)
    _nlp.tokenizer.infix_finditer = infix_regex.finditer

    # Register "(s)" forms as single tokens (mirrors matcher_run.py setup)
    from dosage_instructions.model.constants import PARENTHETICAL_S_WORDS

    for word in PARENTHETICAL_S_WORDS:
        _nlp.tokenizer.add_special_case(
            f"{word}(s)", [{"ORTH": f"{word}(s)", "NORM": word}]
        )

    # Copy lemma → norm so matcher patterns can use NORM uniformly.
    # Overwrite for all tokens EXCEPT special-case "(s)" forms (detected by "(" in text)
    # to undo spaCy's American-English normalisation (e.g. "litres" norm="liters" → "litre").
    from spacy.language import Language

    @Language.component("norm_from_lemma")
    def norm_from_lemma(doc):
        for token in doc:
            if "(" not in token.text:
                token.norm_ = token.lemma_
        return doc

    _nlp.add_pipe("norm_from_lemma", after="lemmatizer")

    return _nlp


@pytest.fixture(scope="session")
def matcher(nlp):
    """Empty Matcher on the session nlp vocab."""
    return Matcher(nlp.vocab)


@pytest.fixture(scope="session")
def all_instances(nlp, matcher):
    """Instantiate all element classes, registering patterns in the matcher."""
    from dosage_instructions.model.matcher_classes import element_types

    return [element_type(nlp, matcher) for element_type in element_types]


@pytest.fixture(scope="session")
def instances_by_key(all_instances):
    return {inst.element_key: inst for inst in all_instances}


@pytest.fixture(scope="session")
def priority_map(all_instances):
    return {inst.element_key: i for i, inst in enumerate(all_instances)}


@pytest.fixture(scope="session")
def spark():
    """Local SparkSession for integration tests."""
    from pyspark.sql import SparkSession

    session = (
        SparkSession.builder.master("local[1]")
        .appName("dosage_tests")
        .config("spark.sql.shuffle.partitions", "1")
        .getOrCreate()
    )
    yield session
    session.stop()
