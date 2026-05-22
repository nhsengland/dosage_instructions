import spacy

print(spacy.__version__)
nlp = spacy.load("en_core_web_sm")
print(nlp.meta["version"])
