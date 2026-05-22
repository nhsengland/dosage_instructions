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
    return _nlp


@pytest.fixture(scope="session")
def matcher(nlp):
    """Empty Matcher on the session nlp vocab."""
    return Matcher(nlp.vocab)


@pytest.fixture(scope="session")
def all_instances(nlp, matcher):
    """Instantiate all element classes, registering patterns in the matcher."""
    from dosage_instructions.model.matcher_classes import classes

    return [cls(nlp, matcher) for cls in classes]


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
