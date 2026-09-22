import re

bucket_order = [
    "methodPassive",
    "methodDirect",
    "doseQuantity",
    "dose_QuantityValueOnly",
    "milligramValue",
    "doseXMilliValueOnly",
    "doseRange",
    "dose_QuantityValueAndMaxOnly",
    "milligramMax",
    "rateRatio",
    "rateQuantity",
    "rateRange",
    "durationValue",
    "durationMax",
    "frequencyBare",
    "frequencyWithMethod",
    "periodElement",
    "count",
    "whenBare",
    "whenWithMethod",
    "dayOfWeek",
    "timeOfDay",
    "route",
    "site",
    "asNeededCodeableConcept",
    "asNeededBoolean",
    "boundsDuration",
    "boundsPeriod",
    "boundsAPeriodStartEnd",
    "event",
    "maxDosePerPeriod",
    "maxDosePerAdministration",
    "maxDosePerLifetime",
    "extras",  # additionalInstruction
    "extrasAsDirected",
    "extrasPAUSE",
    "extrasALTER",
    "extras_b",
    "forElement",
]

# ---------------------------------------------------------------------------
# WORD_TO_DIGIT — single source of truth for number-word ↔ digit mapping.
#
# Used by preprocessing (word→digit) and by exclude_list (nums patterns).
# To add a new number word, add ONE line here.
# ---------------------------------------------------------------------------
WORD_TO_DIGIT = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}

latin_dict = {
    "ac": "before food",
    "acm": "before breakfast",
    "acd": "before lunch",
    "acv": "before dinner",
    "bd": ". 2 times every day",
    "od": "every day",
    "pc": "after food",
    "pcm": "after breakfast",
    "pcd": "after lunch",
    "pcv": "after dinner",
    "prn": ". when required",
    "qds": ". 4 times every day",
    "qqh": "every 4 hours",
    "stat": "immediately",
    "tds": ". 3 times every day",
    "tid": ". 3 times every day",
    "mane": "in the morning",
    "nocte": "at night",
    "hs": "before sleep",
    "wake": "upon waking",
    "c": "at a meal",
    "cm": "at breakfast",
    "cv": "at dinner",
    "phs": "after sleep",
    "mdu": "as directed",
    # Note: GPs uneasy about this conversion: "morn": "morning",
    # Note: GPs uneasy about this conversion: "aft": "afternoon",
    # Note: GPs uneasy about this conversion: "eve": "evening",
    # Note: can't include "on": "every night", because of alternate meaning (e.g. on Friday)
    # Note: can't include "cd": "at lunch", because of possible mix up with control drug
    # Note: can't include "om": "every morning", because of risk (e.g. does 8om refer to time)
}

replace_isolated_terms = {
    "after sleep": "once asleep",
    "hourly": "every hour",
    "daily": "every day",
    "weekly": "every week",
    "monthly": "every month",
    "once or twice": ". 1 or 2 times",
    # Note: can't replace once because alternate meaning, e.g. "once you feel better stop"
    "twice": ". 2 times",
    r"hrs": "hours",
    r"hr": "hour",
    r"(\d+)\s+(and)\sa?\s?(half)\s?(of)?\s?a?": r"$1.5 ",
    r"(\d+)\s+(and)\sa\s(half)": "$1.5 ",
    r"(half)\s+of\s+1": "0.5 ",  # "half of 1 tablet" → "0.5 tablet" (consume the "1")
    r"(half)\s?(of)?\s?a?": "0.5 ",
    r"(\d+)\s+and 3 quarters of a": "$1.75 ",
    r"(\d+)\s+(and)\s(3 quarters)\s?(of)?\s?a?": "$1.75 ",
    r"(3 quarters)\s+of\s+1": "0.75 ",  # "3 quarters of 1 tablet" → "0.75 tablet"
    r"(3 quarters)\s?(of)?\s?a?": "0.75 ",
    r"(\d+)\s+(and)\sa?\s?(quarter)\s?(of)?\s?a?": "$1.25 ",
    r"(quarter)\s+of\s+1": "0.25 ",  # "quarter of 1 tablet" → "0.25 tablet"
    r"a?\s+(quarter)\s?(of)?\s?a?": "0.25 ",
    "upto": "up to",
}

# ---------------------------------------------------------------------------
# Date separator normalisation — see docs/preprocessing_dates.md
#
# spaCy's tokenizer splits on "/" and "-" but keeps "." inside tokens:
#   "01/01/2025" → ["01", "/", "01", "/", "2025"]  (5 tokens — breaks matcher)
#   "01-01-2025" → ["01", "-", "01", "-", "2025"]  (5 tokens — breaks matcher)
#   "01.01.2025" → ["01.01.2025"]                   (1 token  — works)
#
# By converting slash- and dash-separated dates to dot-separated BEFORE
# tokenisation, the date matchers (date_reg_dmy, date_reg_ymd) only need
# to match a single token. The date regexes still accept all three separators
# so they also match any mixed-separator dates that slip through (though in
# practice those won't tokenise as a single token and therefore won't match).
# ---------------------------------------------------------------------------
normalise_date_separators = {
    r"(\d{1,2})[\/](\d{1,2})[\/](\d{2,4})": r"$1.$2.$3",  # dd/mm/yyyy → dd.mm.yyyy
    r"(\d{1,2})[\-](\d{1,2})[\-](\d{2,4})": r"$1.$2.$3",  # dd-mm-yyyy → dd.mm.yyyy
}

# Ensure number-dash-number ranges have spaces around the dash so they are
# not confused with hyphenated compounds (e.g. "2-4" → "2 - 4").
normalise_number_ranges = {
    r"(\d+)\s-(\d+)": r"$1 - $2",
}

# ---------------------------------------------------------------------------
# DOSE_FORMS — single source of truth for dose-form unit metadata.
#
# Each entry maps a singular form to (plural, snomed_code, snomed_display, is_unit_dose).
#   plural:         plural form
#   snomed_code:    SNOMED CT code for FHIR coding (or None for display-only)
#   snomed_display: SNOMED display text (or None)
#   is_unit_dose:   True if >10 of this form is implausible (used by rule VC2)
#
# To add a new dose form, add ONE line here.
# ---------------------------------------------------------------------------
DOSE_FORMS = {
    # singular          plural               snomed_code          snomed_display   is_unit_dose
    "tablet": ("tablets", "428673006", "Tablet", True),
    "capsule": ("capsules", "428641000", "Capsule", True),
    "puff": ("puffs", "415215001", "Puff", True),
    "drop": ("drops", "404218003", "Drop", False),
    "patch": ("patches", "421134003", "Patch", True),
    "sachet": ("sachets", "733010000", "Sachet", True),
    "dose": ("doses", "3317411000001100", "Dose", False),
    "lozenge": ("lozenges", "385087003", "Lozenge", True),
    "pessary": ("pessaries", "421079001", "Pessary", True),
    "suppository": ("suppositories", "385194003", "Suppository", True),
    "injection": ("injections", "129326001", "Injection", True),
    "vial": ("vials", "415818005", "Vial", True),
    "ampoule": ("ampoules", "413516001", "Ampoule", True),
    "pump": ("pumps", "2741000175105", "Pump", False),
    "enema": ("enemas", "385166005", "Enema", True),
    "spoonful": ("spoonfuls", "733015005", "Spoonful", False),
    "spray": ("sprays", "738996007", "Spray", False),
    "suck": ("sucks", "764498003", "Suck", False),
    "application": ("applications", "413568008", "Application", False),
    # No SNOMED code — display only
    "spoon": ("spoons", None, None, False),
    "bottle": ("bottles", None, None, False),
    "strip": ("strips", None, None, False),
    "caplet": ("caplets", None, None, False),
    "dressing": ("dressings", None, None, False),
    "swab": ("swabs", None, None, False),
    "plaster": ("plasters", None, None, False),
    "applicator": ("applicators", None, None, False),
    "cup": ("cups", None, None, False),
    "scoop": ("scoops", None, None, False),
    "pastille": ("pastilles", None, None, False),
    "chewable tablet": ("chewable tablets", None, None, False),
}

# ---------------------------------------------------------------------------
# Derived from DOSE_FORMS
# ---------------------------------------------------------------------------
DOSE_FORM_TO_SNOMED = {}
for _sg, (_pl, _code, _display, _) in DOSE_FORMS.items():
    if _code is None:
        continue  # no SNOMED code — falls through to display-only in fhir_logic
    _entry = {"code": _code, "display": _display}
    DOSE_FORM_TO_SNOMED[_sg] = _entry
    if _pl:
        DOSE_FORM_TO_SNOMED[_pl] = _entry
    DOSE_FORM_TO_SNOMED[f"{_sg}(s)"] = _entry

UNIT_DOSE_FORMS = frozenset(
    sg for sg, (pl, _, _, is_ud) in DOSE_FORMS.items() if is_ud
) | frozenset(pl for _, (pl, _, _, is_ud) in DOSE_FORMS.items() if is_ud and pl)

SINGULAR_TO_PLURAL = {sg: pl for sg, (pl, _, _, _) in DOSE_FORMS.items() if pl}
PLURAL_TO_SINGULAR = {v: k for k, v in SINGULAR_TO_PLURAL.items()}
ALL_SINGULAR = frozenset(SINGULAR_TO_PLURAL.keys())
ALL_PLURAL = frozenset(SINGULAR_TO_PLURAL.values())

# ---------------------------------------------------------------------------
# unit_config — derived from DOSE_FORMS for matcher pattern generation.
# ---------------------------------------------------------------------------
unit_config = {
    "options": list(DOSE_FORMS.keys()),
    "prefixes": [""],
    "suffixes": ["", "s", "(s)", "es"],
}

# Build alternation of dose-form words for use in exclude_list pattern.
# Sorted longest-first so regex matches greedily (e.g. "chewable tablets" before "tablets").
_DOSE_FORM_ALTERNATION = "|".join(
    sorted(
        {opt + s for opt in unit_config["options"] for s in ("", "s")},
        key=len,
        reverse=True,
    )
)

# ---------------------------------------------------------------------------
# PERIOD_UNITS — single source of truth for all period/time unit metadata.
#
# Each entry maps a base unit name to (ucum_code, days, adverb).
# Everything else (period_unit_config, _PERIOD_UNIT_ADVERBS, FHIR UCUM
# lookups, cross-column day conversions) is derived from this dict.
# To add a new period unit, add ONE line here.
# ---------------------------------------------------------------------------
PERIOD_UNITS = {
    #  base_form    ucum   days        adverb           plural
    "minute": ("min", 1 / 1440, "minutely", "minutes"),
    "hour": ("h", 1 / 24, "hourly", "hours"),
    "day": ("d", 1, "daily", "days"),
    "week": ("wk", 7, "weekly", "weeks"),
    "fortnight": (
        "wk",
        14,
        "fortnightly",
        "fortnights",
    ),  # UCUM has no fortnight; use 2×wk
    "month": ("mo", 30, "monthly", "months"),
    "year": ("a", 365, "yearly", "years"),
    "annual": ("a", 365, None, None),  # alias for year, no adverb/plural
}

# ---------------------------------------------------------------------------
# Ambiguous "<number> <unit>ly" patterns (e.g. "4 hourly", "4-6 hourly")
# These are ambiguous because "4 hourly" could mean either:
#   - 4 (quantity) every hour, OR
#   - every 4 hours
# We exclude any instruction containing <digit><space or hyphen><period-adverb>.
# ---------------------------------------------------------------------------
_PERIOD_UNIT_ADVERBS = {k: v[2] for k, v in PERIOD_UNITS.items() if v[2]}
_PERIOD_UNIT_PLURALS = {k: v[3] for k, v in PERIOD_UNITS.items() if v[3]}
_PERIOD_ADVERBS_PATTERN = "|".join(_PERIOD_UNIT_ADVERBS.values())

# ── Derived lookups (used by fhir_logic and cross_column_validity_rules) ──
PERIOD_UNIT_TO_UCUM = {}
for _pu, (_ucum, _, _, _plural) in PERIOD_UNITS.items():
    PERIOD_UNIT_TO_UCUM[_pu] = _ucum
    if _plural:
        PERIOD_UNIT_TO_UCUM[_plural] = _ucum

PERIOD_UNIT_TO_DAYS = {}
for _pu, (_, _days, _, _plural) in PERIOD_UNITS.items():
    if _pu == "annual":
        continue  # cross-column rules use base period words only
    PERIOD_UNIT_TO_DAYS[_pu] = _days
    if _plural:
        PERIOD_UNIT_TO_DAYS[_plural] = _days

# Derived from WORD_TO_DIGIT — used by exclude_list patterns
nums = list(WORD_TO_DIGIT.keys())
_NUMS_PATTERN = "|".join(nums)
_NUMS_PATTERN_GT1 = "|".join(nums[1:])  # two|three|...|ten (excludes "one")
exclude_list = [a + b for a in nums for b in nums] + [
    "one half",
    "1 half",
    "2time",
    "0ne",
    "oneto",
    "&amp;",
    "&gt;",
    "&lt;",
    "1 time",
    "one time",
    r"\d\s?\.\s\d",
    r"\d\s\.\d",
    # ── Ambiguous fraction-number patterns ────────────────────────────────────
    # "half - one tablet" / "half one tablet" — unclear if range or fixed dose
    rf"\bhalf\s*-\s*({_NUMS_PATTERN}|\d+)\b",
    rf"\bhalf\s+({_NUMS_PATTERN}|\d+)\b",
    rf"\bquarter\s*-\s*({_NUMS_PATTERN}|\d+)\b",
    rf"\bquarter\s+({_NUMS_PATTERN}|\d+)\b",
    rf"\b3 quarters\s*-\s*({_NUMS_PATTERN}|\d+)\b",
    rf"\b3 quarters\s+({_NUMS_PATTERN}|\d+)\b",
    # "half of 2 tablets" — ambiguous arithmetic (half of N>1)
    # Excludes "one"/1 because "half of one tablet" is unambiguous (= 0.5 tablet)
    # and preprocessing already converts it via "half of 1" → "0.5 ".
    rf"\bhalf of ({_NUMS_PATTERN_GT1}|\d{{2,}}|[2-9])\b",
    rf"\bquarter of ({_NUMS_PATTERN_GT1}|\d{{2,}}|[2-9])\b",
    rf"\b3 quarters of ({_NUMS_PATTERN_GT1}|\d{{2,}}|[2-9])\b",
    # ── Ambiguous "<number> <period-adverb>" patterns ─────────────────────────
    # "4 hourly" / "4-6 hourly" / "4-hourly" — could mean "every 4 hours" or
    # "4 (quantity) every hour". Exclude rather than guess.
    # "1 hourly" / "one hourly" is unambiguous (= once every hour) so only >1 excluded.
    # Digits: 2-9 or 2+ digit numbers (10, 12, etc.) — not "1" alone
    rf"(?:[2-9]|\d{{2,}})[\s-](?:{_PERIOD_ADVERBS_PATTERN})",
    # Written numbers (two–ten) — word-to-digit hasn't run yet at exclude time
    rf"\b(?:{_NUMS_PATTERN_GT1})[\s-](?:{_PERIOD_ADVERBS_PATTERN})",
    # ── Number glued to dose-form word (no space) ─────────────────────────────
    # "2tablets" is a typo/OCR error — ambiguous whether "2 tablets" or garbage.
    # NOT excluded when followed by "/" (e.g. "2tablets/day" is a valid rate).
    rf"\d+(?:{_DOSE_FORM_ALTERNATION})\b(?!/)",
    # ── Two bare numbers separated only by whitespace ─────────────────────────
    # e.g. "1 3 times a day", "2  4 times daily", "1\t2 tablets"
    # A number immediately followed by another number (spaces/tabs only between)
    # is always a data error — valid instructions always have a word or operator
    # (to, or, x, -, /, in, every …) between two numbers.
    r"\b\d+[ \t]+\d+\b",
]

# ---------------------------------------------------------------------------
# Date token regexes — match a SINGLE token containing a complete date.
#
# These work because preprocessing normalises "/" and "-" separators to "."
# (see normalise_date_separators above and docs/preprocessing_dates.md).
# spaCy keeps "." inside tokens, so "01.01.2025" arrives as one token.
# The [\/.\-] character class is retained as a safety fallback.
# ---------------------------------------------------------------------------
date_reg_dmy = (
    r"^([0-2]?[1-9]|10|20|30|31)"  # day: 01-31
    r"([\/.\-](0?[0-9]|10|11|12)[\/.\-]"  # numeric month: 01-12
    r"|[\/.\-\s]"  # or separator before named month
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
    r"January|February|March|April|May|June|July|August|September|October|November|December)"
    r"[\/.\-\s])"
    r"(19|20)[0-9]{2}$"  # year: 1900-2099
)

date_reg_ymd = (
    r"^(19|20)[0-9]{2}"  # year: 1900-2099
    r"([\/.\-](0?[0-9]|10|11|12)[\/.\-]"  # numeric month: 01-12
    r"|[\/.\-\s]"  # or separator before named month
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
    r"January|February|March|April|May|June|July|August|September|October|November|December)"
    r"[\/.\-\s])"
    r"([0-2]?[1-9]|10|20|30|31)$"  # day: 01-31
)

#  Add the plural of the list via processing rather than require both in the list. Display as 5 milligram
preprocess_units_of_measure = {
    #    "milligram": ["milligram", "mg"],
    #    "millilitre": ["millilitre", "ml"],
    #    "microgram": ["microgram"],
    #    "nanogram": ["nanogram"],
    #    "millimol": ["millimol", "mmol"],
    r"$1 x 5ml spoon": [
        r"(\d+)\s?x5ml spoon",
        r"(\d+)\s?x5mls spoon",
        r"(\d+)\s?x 5mls spoon",
        r"(\d+) 5mls? spoon",
    ],
    r"$1 x 2.5ml spoon": [
        r"(\d+)\s?x2.5ml spoon",
        r"(\d+)\s?x2.5mls spoon",
        r"(\d+)\s?x 2.5mls spoon",
        r"(\d+) 2.5mls? spoon",
    ],  #
}


# ---------------------------------------------------------------------------
# ROUTES — single source of truth for administration route metadata.
#
# Each entry maps a route name to (snomed_code, snomed_display, adverbial).
#   snomed_code:    SNOMED CT code for FHIR coding (or None)
#   snomed_display: SNOMED display text (or None)
#   adverbial:      adverb form matched in text (e.g. "orally") or None
#
# To add a new route, add ONE line here.
# ---------------------------------------------------------------------------
ROUTES = {
    # route_name                              snomed_code           snomed_display                adverbial
    # ── With SNOMED code ──────────────────────────────────────────────────────
    "oral": ("26643006", "Oral", "orally"),
    "inhalation": ("18679011000001101", "Inhalation", None),
    "subcutaneous": ("34206005", "Subcutaneous", "subcutaneously"),
    "intravenous": ("47625008", "Intravenous", "intravenously"),
    "intramuscular": ("78421000", "Intramuscular", "intramuscularly"),
    "rectal": ("37161004", "Rectal", None),
    "vaginal": ("16857009", "Vaginal", "vaginally"),
    "nasal": ("46713006", "Nasal", "nasally"),
    "sublingual": ("37839007", "Sublingual", None),
    "transdermal": ("45890007", "Transdermal", None),
    "topical": ("6064005", "Topical", "topically"),
    "buccal": ("54471007", "Buccal", None),
    "epidural": ("404820008", "Epidural", None),
    "intrathecal": ("72607000", "Intrathecal", None),
    "intra-articular": ("12130007", "Intra-articular", None),
    "intra-arterial": ("58100008", "Intra-arterial", None),
    "intradermal": ("372464004", "Intradermal", None),
    "intravitreal": ("58831000052108", "Intravitreal", None),
    "periarticular": ("372464004", "Periarticular", None),
    "ocular": ("54485002", "Ophthalmic", None),
    "otic": ("10547007", "Otic", None),
    "cutaneous": ("6064005", "Cutaneous", None),
    "percutaneous": ("6064005", "Percutaneous", None),
    "enteral": ("447694001", "Enteral", None),
    "gastroenteral": ("447694001", "Gastroenteral", None),
    "gastrostomy": ("127490009", "Gastrostomy", None),
    "jejunostomy": ("127491008", "Jejunostomy", None),
    "nasogastric": ("127492001", "Nasogastric", None),
    "nasojejunal": ("446540005", "Nasojejunal", None),
    "oromucosal": ("447052000", "Oromucosal", None),
    "translingual": ("37839007", "Translingual", None),
    "implantation": ("90028008", "Implantation", None),
    "intraperitoneal": ("38239002", "Intraperitoneal", None),
    "intravesical": ("372468001", "Intravesical", None),
    "intralesional": ("372469009", "Intralesional", None),
    "intraosseous": ("417255000", "Intraosseous", None),
    "intracardiac": ("372460005", "Intracardiac", None),
    "intrapleural": ("418821007", "Intrapleural", None),
    "intracameral": ("418401004", "Intracameral", None),
    "dental": ("372449004", "Dental", None),
    "endocervical": ("37737002", "Endocervical", None),
    "gingival": ("372457001", "Gingival", None),
    "infiltration": ("446540005", "Infiltration", None),
    "urethral": ("90028008", "Urethral", None),
    "subconjunctival": ("37161004", "Subconjunctival", None),
    "pericardial": ("445771006", "Pericardial", None),
    "haemodialysis": ("431784008", "Haemodialysis", None),
    "haemofiltration": ("431784008", "Haemofiltration", None),
    "haemodiafiltration": ("431784008", "Haemodiafiltration", None),
    # ── No SNOMED code (display only) ─────────────────────────────────────────
    "submucosal rectal": (None, None, None),
    "subretinal": (None, None, None),
    "intrauterine": (None, None, None),
    "perilesional": (None, None, None),
    "intracavernous": (None, None, None),
    "intracervical": (None, None, None),
    "intracoronary": (None, None, None),
    "intradiscal": (None, None, None),
    "intralymphatic": (None, None, None),
    "intraocular": (None, None, None),
    "intrasternal": (None, None, None),
    "perineural": (None, None, None),
    "extra-amniotic": (None, None, None),
    "endosinusial": (None, None, None),
    "endotracheopulmonary": (None, None, None),
    "intraamniotic": (None, None, None),
    "intrabursal": (None, None, None),
    "transmucosal": (None, None, None),
    "intraglandular": (None, None, None),
    "intracerebroventricular": (None, None, None),
    "intraventricular route - cardiac": (None, None, None),
    "body cavity": (None, None, None),
    "regional perfusion": (None, None, None),
    "peribulbar ocular": (None, None, None),
    "extracorporeal": (None, None, None),
    "intraputaminal": (None, None, None),
    "sublabial": (None, None, None),
    "retrobulbar": (None, None, None),
    "intratendinous": (None, None, None),
    "intratumor": (None, None, None),
    "epilesional": (None, None, None),
    "percutaneous endoscopic gastrostomy tube": (None, None, None),
    "intraepidermal": (None, None, None),
    "iontophoresis": (None, None, None),
    "peritendinous": (None, None, None),
    "submucosal": (None, None, None),
    "intracatheter instillation": (None, None, None),
    "intradialytic": (None, None, None),
    "intracholangiopancreatic": (None, None, None),
    "line lock": (None, None, None),
    "periosseous": (None, None, None),
    "peritumoral": (None, None, None),
}

# ---------------------------------------------------------------------------
# Derived from ROUTES
# ---------------------------------------------------------------------------
route = list(ROUTES.keys())

ROUTE_TO_SNOMED = {}
for _r, (_code, _display, _) in ROUTES.items():
    if _code is not None:
        ROUTE_TO_SNOMED[_r] = {"code": _code, "display": _display}

route_adverbial_mapping = {k: adv for k, (_, _, adv) in ROUTES.items() if adv}

MEDICAL_PROFESSIONAL = (
    r"(?:specialist|hospital|consultant|dietician|dermatology|cardiology)"
)
COMMON_MEDICINE = r"(paracetamol|ibuprofen|asprin|naproxen|prednisolone)"
extras_asDirected = [
    # Longer "by professional" patterns FIRST so they win over the shorter ones.
    # These stay as text-only additionalInstruction (no SNOMED code).
    r"\bas directed by " + MEDICAL_PROFESSIONAL,
    # Generic forms — normalised to "as directed" → gets SNOMED 1116431000001106
    r"\bas directed\b",
]
extras_symptoms_PAUSE = [
    "these tablets are addictive so do not take regularly",
    "potentially addictive",
    "not for long term use",
]
extras_symptoms_ALTER = [
    "may cause drowsiness",
]
extras_purpose = [
    # purpose #Use with asNeededCodeableConcept otherwise additionalinformation
]  # Qcall2 - What does Friday Collect mean?
extras_how = [
    "sparingly",
    "gently",
    "liberally",
    "vigorously",
    "slowly",
    "repeatedly",
    "completely",
    "deeply",
    "thoroughly",
    "once only, at night",
    "once only",
    "only",
    "until finished",
    "until gone",
    "then discontinue",
    "now",
    "preferably",
    "thinly",
    "as moisturiser and as soap substitute",
    "to be supplied in a dosette",
    "in dosette",
    "via spacer",
    "via peg",
    "as soap substitute",
    "at the same time every day",
    "without a break",
    "do not stop",
    "then stop",
    "for life",
    "life long",
    "lifelong",
    "lifelong treatment",
    "to continue lifelong",
    "avoid grapefruit",
    r"with your inhaler(\(s\)|s)?",
    r"with (plenty of )?(water|orange juice)",
    "with a full glass of water",
    "with spacer",
    "with insulin pen",
    "regularly",
    (
        r"(with|while|whilst|when)? ?"
        r"(taking|on|using)? ?"
        r"(regular)? ?" + COMMON_MEDICINE
    ),  # Qcall2
    "while sitting",
    "while standing",
    "while sitting or standing",
    "when washing hair",
    r"as advised by " + MEDICAL_PROFESSIONAL,
    r"as per " + MEDICAL_PROFESSIONAL,
]
extras_how_PAUSE = [
    "rinse mouth with water and spit out after use",
    "a thick layer and cover with dressing",
    "dosette",
    "remove old patch before new patch",
]
extras_qualifiers = ["after dialysis", "until review"]
extras_qualifiers_PAUSE = [
    "reduce dose if dizzy",
]

extra_random = [
    "to continue indefinitely",
    "in blister pack",
]

extra_random_PAUSE = [
    "please return your empty or unwanted inhalers to a pharmacy for disposal",
    "blister pack",
    "collect Friday",  # Qcall2: is this an additional instruction anyday of the week?
    "eps",  # Qcall2: what does this mean?
    "contains paracetamol and codeine",  # Qcall2: anywhere specific?
    "clean by soaking in warm soapy water",
    "rinse and allow to air-dry",
    "home delivery service",
    "indication: cvd prevention",
]

extras = extras_purpose + extras_how + extra_random + extras_qualifiers

# These don't sound right unless a comma is added prior
extrasPAUSE = (
    extras_symptoms_PAUSE
    + extras_how_PAUSE
    + extra_random_PAUSE
    + extras_qualifiers_PAUSE
)

# These make the before invalid - e.g. 2 per day may cause drowsiness
extrasALTER = extras_symptoms_ALTER

# Extras which contain numbers need to go before matcher runs
extras_b = [
    r"replace every [0-9]*\s?(day|week|month|year)s?",
    "amber 2",
    "amber 3",
]

# ---------------------------------------------------------------------------
# Parenthetical (s) — words that may appear as "word(s)" in prescriptions.
# Registered as single tokens with NORM = singular so spaCy doesn't split them.
# Sites (eye, nostril, area, nail) are intentionally EXCLUDED — "eye(s)" carries
# clinical meaning (one or both eyes).
#
# Derived from DOSE_FORMS (dose units) + PERIOD_UNITS (time units) + "time".
# Multi-word options (e.g. "chewable tablet") are excluded — spaCy can't
# register multi-word special cases for "(s)" tokenisation.
# ---------------------------------------------------------------------------
PARENTHETICAL_S_WORDS = sorted(
    {sg for sg in DOSE_FORMS if " " not in sg}
    | {k for k in PERIOD_UNITS if k != "annual"}
    | {"time"}
)

# ── Derived (s) resolution lookups (used by matcher_classes) ─────────────────
PARENTHETICAL_S_SINGULAR = {f"{w}(s)": w for w in PARENTHETICAL_S_WORDS}
PARENTHETICAL_S_PLURAL = {}
for _sg, (_pl, _, _, _) in DOSE_FORMS.items():
    if _pl and " " not in _sg:
        PARENTHETICAL_S_PLURAL[f"{_sg}(s)"] = _pl
for _pu, (_, _, _, _plural) in PERIOD_UNITS.items():
    if _plural:
        PARENTHETICAL_S_PLURAL[f"{_pu}(s)"] = _plural
PARENTHETICAL_S_PLURAL["time(s)"] = "times"

period_unit_config = {
    "options": list(PERIOD_UNITS.keys()),
    "prefixes": [
        "per",
        "a",
        "/",
        "each",
        "every",
    ],
    "suffixes": ["", "ly"],
}
special_unit_config = {
    "options": [
        "litres per minute",
        "micrograms per kilogram per hour",
        "milligrams per minute",
    ],
    "prefixes": [""],
    "suffixes": [""],
}

# ---------------------------------------------------------------------------
# METHODS — single source of truth for method/verb metadata.
#
# Each entry maps a verb to (past_participle, snomed_code, snomed_display).
#   past_participle: the passive form matched by MethodPassiveElement
#   snomed_code:     SNOMED CT code for FHIR coding (or None)
#   snomed_display:  SNOMED display text (or None)
#
# spaCy lemmatises past participles to base form, so "instilled" → "instill"
# (American/SNOMED spelling). The British "instil" is the dict key; the lemma
# "instill" is added to METHOD_TO_SNOMED automatically for lookup.
#
# To add a new method verb, add ONE line here.
# ---------------------------------------------------------------------------
METHODS = {
    # verb           past_participle  snomed_code        snomed_display
    "take": ("taken", "419652001", "Take"),
    "inhale": ("inhaled", "740666001", "Inhale"),
    "apply": ("applied", "738991002", "Apply"),
    "use": ("used", "18629005", "Use"),
    "insert": ("inserted", "738993004", "Insert"),
    "spray": ("sprayed", "738996007", "Spray"),
    "suck": ("sucked", "764498003", "Suck"),
    "place": ("placed", "421066005", "Place"),
    "chew": ("chewed", "738992009", "Chew"),
    "instil": (
        "instilled",
        "738994005",
        "Instill",
    ),  # British verb; SNOMED uses American "Instill"
    "infuse": ("infused", "764794000", "Infuse"),
    "dissolve": ("dissolved", "421521009", "Dissolve"),
    "inject": ("injected", "740685003", "Inject"),
    "massage": ("massaged", "448598008", "Massage"),
    "swallow": ("swallowed", "738995006", "Swallow"),
    "administer": ("administered", "738990001", "Administer"),
    "rinse": ("rinsed", "782155003", "Rinse"),
    "gargle": ("gargled", "782168006", "Gargle"),
    "give": (
        "given",
        None,
        None,
    ),  # SNOMED display is "Administer" — doesn't match input text
    "dilute": ("diluted", "421399004", "Dilute"),
    "sprinkle": ("sprinkled", "422219000", "Sprinkle"),
    "shampoo": ("shampooed", "420606003", "Shampoo"),
    "sniff": ("sniffed", "420360002", "Sniff"),
    "wash": ("washed", "422152000", "Wash"),
    "swish": ("swished", "421805007", "Swish"),
}

# Compound methods — multi-token phrases matched as a single method unit.
# Each maps a phrase to (snomed_code, snomed_display).
COMPOUND_METHODS = {
    "swish and swallow": ("421298005", "Swish and swallow"),
    "apply sparingly": ("93431000001109", "Apply sparingly"),
    "use as a mouthwash": ("93481000001108", "Use as a mouthwash"),
}

# ---------------------------------------------------------------------------
# Derived from METHODS / COMPOUND_METHODS
# ---------------------------------------------------------------------------
METHOD_TO_SNOMED = {}
for _verb, (_pp, _code, _display) in METHODS.items():
    if _code is not None:
        _entry = {"code": _code, "display": _display}
        METHOD_TO_SNOMED[_verb] = _entry
        # Also map the lemma form if it differs (e.g. "instill" from spaCy lemma of "instilled")
        if _pp and _pp.endswith("ed"):
            # crude lemma: strip -ed, -d; spaCy is more sophisticated but this catches instill→instilled
            pass  # spaCy handles lemmatisation; we just need the base verb key above
        # Map the American spelling "instill" explicitly (spaCy lemma of "instilled")
        if _verb == "instil":
            METHOD_TO_SNOMED["instill"] = _entry
for _phrase, (_code, _display) in COMPOUND_METHODS.items():
    METHOD_TO_SNOMED[_phrase] = {"code": _code, "display": _display}

method_config = {
    "options": list(METHODS.keys()),
    "past_participles": [pp for _, (pp, _, _) in METHODS.items()],
    "compound_options": list(COMPOUND_METHODS.keys()),
    "prefixes": ["", "to be "],
    "suffixes": ["", "n", "d", "ed"],
}

weekday_config = {
    "options": [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "mondays",
        "tuesdays",
        "wednesdays",
        "thursdays",
        "fridays",
        "saturdays",
        "sundays",
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",
        "sun",
    ],
    "prefixes": [""],
    "suffixes": [""],
}

# ---------------------------------------------------------------------------
# Derived from weekday_config
# ---------------------------------------------------------------------------
DAY_TO_FHIR = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
    "mon": "mon",
    "tue": "tue",
    "wed": "wed",
    "thu": "thu",
    "fri": "fri",
    "sat": "sat",
    "sun": "sun",
}

# ---------------------------------------------------------------------------
# WHEN_NOUNS — single source of truth for when/timing noun metadata.
#
# Each entry maps a when keyword to (timing_category, fhir_event_code).
#   timing_category: how cross-column rules treat this noun:
#       "specific"      — implies a daily cycle (one point per day)
#       "generic"       — no timing cycle implied
#       "multi_per_day" — implies multiple occurrences per day
#   fhir_event_code: FHIR EventTiming code (e.g. "MORN") or None.
#       When None, the noun may still get a FHIR code via WHEN_PREFIX_MAP
#       (e.g. "before" + "breakfast" → "ACM") or route to additionalInstruction.
#
# To add a new when noun, add ONE line here.
# ---------------------------------------------------------------------------
WHEN_NOUNS = {
    # keyword                 timing_category    fhir_event_code
    # ── Specific (daily timing point, one per day) ────────────────────────
    "morning": ("specific", "MORN"),
    "afternoon": ("specific", "AFT"),
    "evening": ("specific", "EVE"),
    "night": ("specific", "NIGHT"),
    "noon": ("specific", "NOON"),
    "bedtime": ("specific", "HS"),
    "waking": ("specific", "WAKE"),
    "breakfast": ("specific", None),  # FHIR via prefix map only
    "lunch": ("specific", None),  # FHIR via prefix map only
    "lunchtime": ("specific", None),
    "dinner": ("specific", None),  # FHIR via prefix map only
    "evening meal": ("specific", None),
    "morning meal": ("specific", None),
    "teatime": ("specific", None),
    "tea time": ("specific", None),  # space variant used by when_config
    "sleep": ("specific", None),  # FHIR via prefix map (before sleep → HS)
    "asleep": ("specific", None),  # from preprocessing: "after sleep" → "once asleep"
    "procedure": ("specific", None),
    # ── Generic (no timing cycle implied) ─────────────────────────────────
    "food": ("generic", None),  # FHIR via SNOMED additional + prefix map
    "meal": ("generic", None),  # FHIR via prefix map
    "eat": ("generic", None),
    "eating": ("generic", None),
    "empty stomach": ("generic", None),  # FHIR via text-only additional
    # ── Multi per day (implies multiple daily occurrences) ────────────────
    "meals": ("multi_per_day", None),
    "main meals": ("multi_per_day", None),
    "each meal": ("multi_per_day", None),
    "every meal": ("multi_per_day", None),
    "each main meal": ("multi_per_day", None),
    "every main meal": ("multi_per_day", None),
    "foods": ("multi_per_day", None),
    "bowel movements": ("multi_per_day", None),
    "each bowel movement": ("multi_per_day", None),
    "every bowel movement": ("multi_per_day", None),
}

# ---------------------------------------------------------------------------
# Derived from WHEN_NOUNS
# ---------------------------------------------------------------------------
SPECIFIC_WHEN_KEYWORDS = frozenset(
    k for k, (cat, _) in WHEN_NOUNS.items() if cat == "specific"
)
GENERIC_WHEN_KEYWORDS = frozenset(
    k for k, (cat, _) in WHEN_NOUNS.items() if cat == "generic"
)
MULTI_PER_DAY_WHEN_KEYWORDS = frozenset(
    k for k, (cat, _) in WHEN_NOUNS.items() if cat == "multi_per_day"
)
WHEN_OPTION_TO_FHIR = {k: code for k, (_, code) in WHEN_NOUNS.items() if code}

# ---------------------------------------------------------------------------
# FHIR when routing — prefix-based and additional instruction mappings.
#
# These describe *combinations* (preposition + noun → code) rather than
# individual nouns, so they stay as separate dicts next to WHEN_NOUNS.
# ---------------------------------------------------------------------------

# Prefix-based: (preposition, noun) → FHIR EventTiming code.
# Used when a noun alone has no fhir_event_code but gains one with a preposition.
WHEN_PREFIX_MAP = {
    ("before", "meal"): "AC",
    ("before", "breakfast"): "ACM",
    ("before", "lunch"): "ACD",
    ("before", "dinner"): "ACV",
    ("after", "food"): "PC",
    ("after", "meal"): "PC",
    ("after", "breakfast"): "PCM",
    ("after", "lunch"): "PCD",
    ("after", "dinner"): "PCV",
    ("with", "meal"): "C",
    ("with", "breakfast"): "CM",
    ("with", "lunch"): "CD",
    ("with", "dinner"): "CV",
    ("before", "sleep"): "HS",
}

# Move to additionalInstruction WITH SNOMED code.
# Key = substring to match in when_text; value = {code, display}.
WHEN_TO_ADDITIONAL_INSTRUCTION_SNOMED = {
    "before food": {"code": "311500009", "display": "Before food"},
    "with food": {"code": "1116481000001105", "display": "With food"},
    "after food": {"code": "225758001", "display": "After food"},
}

# Move to additionalInstruction as TEXT ONLY (no SNOMED code available).
# NB: meal compound phrases (e.g. "evening meal") must be listed BEFORE bare
# timing words (e.g. "evening") so they are caught here before WHEN_OPTION_TO_FHIR
# would incorrectly map them to EVE/MORN etc.
WHEN_TO_ADDITIONAL_INSTRUCTION_TEXT = [
    "evening meal",
    "morning meal",
    "main meal",
    "empty stomach",
    "before noon",
    "after noon",
]

# ---------------------------------------------------------------------------
# METRIC_UNITS — single source of truth for metric/measurement unit metadata.
#
# Each entry maps a canonical name to (ucum_code, factor, category, aliases).
#   ucum_code: FHIR UCUM code for this unit
#   factor:    conversion factor to base unit within category
#              (micrograms for mass, mL for volume, mmol for molar)
#   category:  "mass", "volume", or "molar" — controls which units are
#              comparable for range validation (e.g. 500mg to 1g is valid)
#   aliases:   abbreviations and plural forms that appear in prescription text
#
# To add a new metric unit, add ONE line here.
# ---------------------------------------------------------------------------
METRIC_UNITS = {
    "milligram": ("mg", 1000, "mass", ["mg", "mgs", "milligrams"]),
    "microgram": ("ug", 1, "mass", ["mcg", "mcgs", "micrograms"]),
    "gram": ("g", 1_000_000, "mass", ["g", "gs", "grams"]),
    "nanogram": ("ng", 0.001, "mass", ["nanograms"]),
    "millilitre": ("mL", 1, "volume", ["ml", "mls", "millilitres"]),
    "litre": ("L", 1000, "volume", ["litres"]),
    "millimol": ("mmol", 1, "molar", ["mmol", "mmols", "millimols"]),
}

# Derive milli_config from METRIC_UNITS
milli_config = {
    "options": sorted(
        {canonical for canonical in METRIC_UNITS}
        | {alias for _, (_, _, _, aliases) in METRIC_UNITS.items() for alias in aliases}
    ),
    "prefixes": [""],
    "suffixes": [""],
}

# ---------------------------------------------------------------------------
# Derived from METRIC_UNITS
# ---------------------------------------------------------------------------
METRIC_UNIT_TO_UCUM = {}
UNIT_TO_MICROGRAMS = {}
MASS_UNITS: set[str] = set()
VOLUME_UNITS: set[str] = set()
for _canonical, (_ucum, _factor, _category, _aliases) in METRIC_UNITS.items():
    METRIC_UNIT_TO_UCUM[_canonical] = _ucum
    for _alias in _aliases:
        METRIC_UNIT_TO_UCUM[_alias] = _ucum
    _all_forms = [_canonical] + _aliases
    for _form in _all_forms:
        UNIT_TO_MICROGRAMS[_form] = _factor
        if _category == "mass":
            MASS_UNITS.add(_form)
        elif _category == "volume":
            VOLUME_UNITS.add(_form)


# ---------------------------------------------------------------------------
# for_config — regex-based extraction of purpose/indication phrases
#
# Item groups control which qualifiers and verbs are semantically valid:
#   _HIGH_ITEMS      → things that can be high/raised → reduce/lower/control verbs
#   _LOW_ITEMS       → things that can be low → raise/improve/treat verbs
#   _DUAL_ITEMS      → can be high OR low (blood pressure, sugar, bp) → both verb sets
#   _CONDITION_ITEMS → abstract conditions → neutral verbs only, "your" qualifier only
#   _BODY_SITE_NOUNS → physical organs → help/protect/treat + "your" only
#   _PAIN_TYPES      → site+pain compounds → relieve/reduce/treat/help/prevent
# ---------------------------------------------------------------------------

# Things that can be high/raised — only valid with reduce/lower/control verbs
_HIGH_ITEMS = (
    r"cholesterol"
    r"|cardiovascular risk"
    r"|cvd risk"
    r"|palpitations?"  # ? allows singular "palpitation"
    r"|angina"
    r"|heart rate"
    r"|blood clots?"
    r"|stomach acid"
)

# Things that can be low — only valid with raise/improve verbs
_LOW_ITEMS = (
    r"iron(?: levels?)?"
    r"|mood"
    r"|folate"
    r"|folic acid(?: levels?)?"
    r"|vitamin (?:d|b12)(?: levels?)?"
    r"|thyroid(?: levels?)?"
)

# Can be high OR low — added to both high and low blocks with their respective verbs
_DUAL_ITEMS = r"blood pressure" r"|blood sugar" r"|sugar(?: levels?)?" r"|bp"

_CONDITION_ITEMS = (
    r"diabetes"
    r"|breathlessness"
    r"|constipation"
    r"|osteoporosis"
    r"|incontinence"
    r"|copd"
    r"|gout"
    r"|anaemia"
    r"|indigestion"
    r"|insomnia"
    r"|anxiety"
    r"|allergies"
    r"|allergy"
    r"|nausea"
    r"|dizziness"
    r"|bowel(?:s| (?:symptoms?|syndrome|spasm))?"
    r"|irritable (?:bowel(?: syndrome)?|bladder|skin)"
    r"|bladder"
    r"|sputum"
    r"|wheeze"
    r"|mucus"
    r"|spasm"
    r"|sleep"
    r"|prostate"
    r"|deficiency"
    r"|prophylaxis"
    r"|thyroid"
    r"|chronic (?:migraine|urticaria|rhinitis|fatigue)"
    r"|ulcer"
    r"|fractures?"
    r"|clots?"
    r"|disease"
    r"|infections?"
    r"|heart (?:failure|attack|disease)"
    r"|strokes?"
    r"|cardiovascular(?: disease)?"
    r"|cvd"
    r"|dry eyes"
)

_BODY_SITE_NOUNS = (
    r"heart"
    r"|kidneys?"
    r"|stomach"
    r"|bones?"
    r"|lungs?"
    r"|skin"
    r"|bowels?"
    r"|bladder"
    r"|liver"
    r"|nerves?"
    r"|back"
    r"|neck"
    r"|legs?"
    r"|joints?"
    r"|chest"
)

_CONTROL_NOUNS = (
    r"blood pressure" r"|bladder" r"|cholesterol" r"|pain" r"|bowel" r"|sugar" r"|bp"
)

_PAIN_TYPES = (
    r"muscle (?:pain|spasm|tightness|rigidity)"  # compound — can't split to site+pain
    r"|nerve[ -]?related pain"
    r"|neuropathic pain"
    r"|pain relief"
    r"|(?:severe|chronic|breakthrough) (?:(?:{_BODY_SITE_NOUNS}) )?pain"
    r"|(?:{_BODY_SITE_NOUNS}) pain"
    r"|pain"
)
# Expand _BODY_SITE_NOUNS reference in _PAIN_TYPES at definition time
_PAIN_TYPES = _PAIN_TYPES.format(_BODY_SITE_NOUNS=_BODY_SITE_NOUNS)

_RISK_EVENTS = (
    r"heart attacks?"
    r"|strokes?"
    r"|blood clots?"
    r"|heart disease"
    r"|cardiovascular disease"
    r"|clots?"
    r"|further stroke"
    r"|side effects"
    r"|cvd"
    r"|dizziness(?:/unsteadiness)?"
)

# Verb forms
_REDUCE_INF = (
    r"reduce|lower|control|manage|prevent|treat|improve|relieve|protect|aid|loosen"
)
_REDUCE_GER = r"reducing|lowering|controlling|managing|preventing|treating|improving|relieving|protecting|aiding|loosening"
_RAISE_INF = r"raise|increase|improve|treat|boost"
_RAISE_GER = r"raising|increasing|improving|treating|boosting"
_NEUTRAL_INF = (
    r"control|manage|treat|help|improve|relieve|protect|aid|prevent|reduce|lower"
)
_NEUTRAL_GER = r"controlling|managing|treating|helping|improving|relieving|protecting|aiding|preventing|reducing|lowering"
_SITE_INF = r"help|protect|treat|support|aid|improve"
_SITE_GER = r"helping|protecting|treating|supporting|aiding|improving"
_PAIN_INF = r"relieve|reduce|treat|prevent|help|control|manage"
_PAIN_GER = r"relieving|reducing|treating|preventing|helping|controlling|managing"

_HIGH_Q = r"(?:your |high |raised |excess )?"
_LOW_Q = r"(?:your (?:low )?|low )?"
_YOUR = r"(?:your )?"

for_config = [
    # ── IMPORTANT: specific/compound patterns FIRST ───────────────────────────
    # These must come before the broad general patterns below. Regex alternation
    # is first-match, so "for blood pressure" would beat "for blood pressure control"
    # if the general pattern appeared earlier. All patterns below that could be
    # a prefix of something longer are listed here first.
    # ── X control: bp control, bladder control, pain control etc ─────────────
    rf"(?:to (?:help )?|for (?:help(?:ing)? )?)(?:improve|maintain|aid) {_YOUR}(?:{_CONTROL_NOUNS}) control",
    rf"for {_YOUR}(?:{_CONTROL_NOUNS}) control",
    # ── Risk of X ─────────────────────────────────────────────────────────────
    rf"(?:to (?:help )?|for (?:help(?:ing)? )?)(?:reduce|lower|prevent) (?:the |your )?risk of (?:{_RISK_EVENTS})(?:(?: (?:and|or|/) (?:{_RISK_EVENTS}))?)?",
    r"(?:to (?:help )?|for (?:help(?:ing)? )?)(?:reduce|lower|prevent) (?:the |your )?risk",
    # ── Remaining special cases ───────────────────────────────────────────────
    r"to reduce heart (?:strain(?:/failure)?|attacks? and strokes?|and stroke risk|effort)",
    r"to reduce heartburn and stomach pain",
    r"to (?:keep|regulate) (?:the )?bowels? regular",
    r"to aid (?:improved )?sleep",
    r"for (?:irritable )?bowel (?:spasm )?pain",
    r"for high blood pressure control",
    r"for high blood pressure/angina/palpitations",
    r"to help stomach while on (?:aspirin|rivaroxaban)",
    r"to help stomach(?: (?:acid|ache))?",
    r"to help thyroid(?: gland)?",
    r"for your (?:mood and sleep|neuropathic pain)",
    r"to (?:improve|help improve) (?:blood pressure control|thyroid levels?|stomach pain|chronic fatigue)",
    # ── High items + dual (reduce only) ──────────────────────────────────────
    rf"(?:to (?:help )?|for (?:help(?:ing)? )?)(?:{_REDUCE_INF}) {_HIGH_Q}(?:{_HIGH_ITEMS}|{_DUAL_ITEMS})",
    rf"to help (?:{_REDUCE_GER}) {_HIGH_Q}(?:{_HIGH_ITEMS}|{_DUAL_ITEMS})",
    rf"for (?:{_REDUCE_GER}) {_HIGH_Q}(?:{_HIGH_ITEMS}|{_DUAL_ITEMS})",
    rf"for {_HIGH_Q}(?:{_HIGH_ITEMS}|{_DUAL_ITEMS})",
    # ── Low items + dual (raise only) ────────────────────────────────────────
    rf"(?:to (?:help )?|for (?:help(?:ing)? )?)(?:{_RAISE_INF}) {_LOW_Q}(?:{_LOW_ITEMS}|{_DUAL_ITEMS})",
    rf"to help (?:{_RAISE_GER}) {_LOW_Q}(?:{_LOW_ITEMS}|{_DUAL_ITEMS})",
    rf"for (?:{_RAISE_GER}) {_LOW_Q}(?:{_LOW_ITEMS}|{_DUAL_ITEMS})",
    rf"for low (?:{_LOW_ITEMS}|{_DUAL_ITEMS})",
    rf"for {_LOW_Q}(?:{_LOW_ITEMS})",
    # ── Condition items: neutral verbs, "your" qualifier only ─────────────────
    rf"(?:to (?:help )?|for (?:help(?:ing)? )?)(?:{_NEUTRAL_INF}) {_YOUR}(?:{_CONDITION_ITEMS})",
    rf"to help (?:{_NEUTRAL_GER}) {_YOUR}(?:{_CONDITION_ITEMS})",
    rf"for (?:{_NEUTRAL_GER}) {_YOUR}(?:{_CONDITION_ITEMS})",
    rf"for {_YOUR}(?:{_CONDITION_ITEMS})",
    rf"to help {_YOUR}(?:{_CONDITION_ITEMS})",
    # ── Body site nouns: "your" + restricted verbs only ───────────────────────
    rf"(?:to (?:{_SITE_INF})|for (?:{_SITE_GER})) your (?:{_BODY_SITE_NOUNS})",
    rf"for your (?:{_BODY_SITE_NOUNS})",
    # ── Pain types: reduce/relieve/treat ─────────────────────────────────────
    rf"(?:to (?:help )?|for (?:help(?:ing)? )?)(?:{_PAIN_INF}) (?:your )?(?:{_PAIN_TYPES})",
    rf"to help (?:{_PAIN_GER}) (?:your )?(?:{_PAIN_TYPES})",
    rf"for (?:{_PAIN_GER}) (?:your )?(?:{_PAIN_TYPES})",
    rf"for (?:your )?(?:{_PAIN_TYPES})",
]


# ---------------------------------------------------------------------------
# when_config — structured generation of timing phrases
#
# Timing nouns are grouped by semantic category. Each group defines which
# prepositions and determiners are valid, based on real prescription data.
# The flat list is generated programmatically — identical to the original
# hand-maintained list but far easier to reason about and extend.
#
# Noun categories:
#   _W_MEAL_SG         → singular generic meals (meal, main meal, evening meal)
#   _W_MEAL_PL         → plural generic meals (meals, main meals, evening meals)
#   _W_SPECIFIC_MEALS  → named meals (breakfast, lunch, dinner, etc.)
#   _W_FOOD            → generic food/eating terms
#   _W_TOD_SG          → singular time of day (morning, afternoon, evening)
#   _W_TOD_PL          → plural time of day (mornings, afternoons, evenings)
#   _W_NIGHT_SLEEP     → night/sleep/bedtime
#   _W_WAKING          → waking/wakes
#   _W_BOWEL           → bowel movement(s)
#   _W_STOMACH         → empty stomach
#   _W_PROCEDURE       → procedure
# ---------------------------------------------------------------------------

# ── Noun categories ──────────────────────────────────────────────────────────

# Meals: singular nouns use "a" or "an" depending on vowel start
_W_MEALS = [
    # (singular, plural, article)
    ("meal", "meals", "a"),
    ("main meal", "main meals", "a"),
    ("evening meal", "evening meals", "an"),
    ("morning meal", None, "a"),  # no plural form in data
    ("breakfast", "breakfasts", "a"),
    ("lunch", None, "a"),
    ("lunchtime", None, None),  # no article ("a lunchtime" is unusual)
    ("dinner", None, "a"),
    ("tea time", None, None),  # no article
]

_W_FOOD = ["food"]
_W_TOD_SG = ["morning", "afternoon", "evening"]
_W_TOD_PL = ["mornings", "afternoons", "evenings"]
_W_NIGHT_SLEEP_NOUNS = ["night", "bedtime"]
_W_WAKING = ["waking", "wakes"]
_W_BOWEL_SG = ["bowel movement"]
_W_BOWEL_PL = ["bowel movements"]

# ── Generation rules ─────────────────────────────────────────────────────────


def _generate_when_options():
    """Generate all valid when timing phrases from structured rules."""
    opts = []

    # ── MEALS: before/after/with/at + [the/a|an/each/every] ──────────────
    # All meal nouns (singular and plural) in one unified loop.
    # For each singular noun: prep + bare, prep + the, prep + a/an, prep + each/every
    # For each plural noun: prep + bare, with the
    for sg, pl, article in _W_MEALS:
        for prep in ("before", "after", "with", "at"):
            # singular: bare + the + each/every
            opts.append(f"{prep} {sg}")  # before meal
            opts.append(f"{prep} the {sg}")  # before the meal
            for det in ("each", "every"):
                opts.append(f"{prep} {det} {sg}")  # before each meal
            # singular: article (a/an) where valid
            if article:
                opts.append(
                    f"{prep} {article} {sg}"
                )  # before a meal / with an evening meal

            # plural: bare
            if pl:
                opts.append(f"{prep} {pl}")  # before meals

        # each/every as standalone prefix (singular only)
        opts.append(f"each {sg}")  # each meal
        opts.append(f"every {sg}")  # every meal

        # with the + plural
        if pl:
            opts.append(f"with the {pl}")  # with the meals

    # Extra meal variant
    opts.append("in evening meal")  # unusual but appears in data

    # ── FOOD: before/after/with + [bare/the/a] ───────────────────────────
    for prep in ("before", "after", "with"):
        opts.append(f"{prep} food")  # before food
        opts.append(f"{prep} the food")  # before the food
        opts.append(f"{prep} a food")  # after a food
    opts.append("with foods")

    # eating: before/after/with/when
    for prep in ("before", "after", "with", "when"):
        opts.append(f"{prep} eating")  # before eating

    # ── TIME OF DAY (singular): in/at/on + [the/an/each/every/a] ──────────
    # Rules differ slightly per noun due to article agreement and idiom:
    #   "in an evening" ✓ but "in an morning" ✗ (consonant)
    #   "in evening" ✓ but "in morning" ✗ (not idiomatic)
    #   "at morning" ✓ (exists in data) but "at afternoon" ✗ (unusual)
    for noun in _W_TOD_SG:
        # in the — all three
        opts.append(f"in the {noun}")
        # on the / on each / on every — all three
        opts.append(f"on the {noun}")
        opts.append(f"on each {noun}")
        opts.append(f"on every {noun}")
        # at each / at every — all three
        opts.append(f"at each {noun}")
        opts.append(f"at every {noun}")
        # each/every as prefix — all three
        opts.append(f"each {noun}")
        opts.append(f"every {noun}")
        # with (unusual but in data) — all three
        opts.append(f"with {noun}")

    # "in/on + bare" and "in/on + an" only for evening (vowel, idiomatic)
    opts.extend(["in evening", "in an evening", "on evening", "on an evening"])
    # "in + bare" and "in an" for afternoon
    opts.extend(["in afternoon", "in an afternoon", "on an afternoon"])
    # "at + bare" for morning and evening (not afternoon)
    opts.extend(["at morning", "at evening"])
    # "on a morning" special case
    opts.append("on a morning")
    # before morning/evening (not afternoon)
    opts.extend(["before morning", "before evening"])

    # ── TIME OF DAY (plural): in/on + [the/bare] ────────────────────────
    for noun in _W_TOD_PL:
        opts.append(f"in the {noun}")
        opts.append(f"in {noun}")
        opts.append(f"on the {noun}")
        opts.append(f"on {noun}")

    # ── NOON ──────────────────────────────────────────────────────────────
    opts.extend(["at noon", "before noon", "after noon", "each noon"])

    # ── NIGHT / SLEEP / BEDTIME ───────────────────────────────────────────
    # night and bedtime share: at, before, before each/every, each, every
    for noun in ("night", "bedtime"):
        opts.append(f"at {noun}")  # at night
        opts.append(f"before {noun}")  # before night
        opts.append(f"before each {noun}")  # before each bedtime
        opts.append(f"before every {noun}")  # before every night
        opts.append(f"each {noun}")  # each night
        opts.append(f"every {noun}")  # every night
        opts.append(f"with {noun}")  # with bedtime (unusual)
        # night-specific: has "the", "on", "in the", plural
    opts.extend(
        [
            "before the night",
            "at every night",
            "in the night",
            "in the nights",
            "in the bedtime",
            "on a night",
            "on the night",
            "on the nights",
            "on every night",
            "on nights",
        ]
    )
    # sleep/sleeping
    opts.extend(["before sleep", "before sleeping", "with sleeping"])

    # ── WAKING ────────────────────────────────────────────────────────────
    opts.extend(
        ["after waking", "on waking", "upon waking", "when waking", "when wakes"]
    )

    # ── BOWEL MOVEMENT ────────────────────────────────────────────────────
    for prep in ("before", "after", "with"):
        opts.append(f"{prep} bowel movement")
        opts.append(f"{prep} each bowel movement")
        opts.append(f"{prep} every bowel movement")
        opts.append(f"{prep} a bowel movement")
        opts.append(f"{prep} bowel movements")

    # ── EMPTY STOMACH ─────────────────────────────────────────────────────
    opts.extend(
        [
            "on an empty stomach",
            "on empty stomach",
            "with an empty stomach",
            "with empty stomach",
        ]
    )

    # ── PROCEDURE ─────────────────────────────────────────────────────────
    opts.extend(["at procedure", "before procedure", "before the procedure"])

    # ── AT ONCE prefix (immediately) ─────────────────────────────────────
    opts.extend(
        [
            "at once after breakfast",
            "at once after food",
            "at once at lunch",
            "at once at night",
            "at once each morning",
            "at once every evening",
            "at once every morning",
            "at once in the morning",
            "at once with breakfast",
            "at once with food",
            "at once with main meal",
            "at once with meal",
        ]
    )

    return sorted(set(opts))


when_config = {"options": _generate_when_options()}

# ---------------------------------------------------------------------------
# SITES — single source of truth for application site SNOMED metadata.
#
# Each entry maps a site keyword to (snomed_code, snomed_display, description_display).
#   snomed_code:         SNOMED CT code
#   snomed_display:      SNOMED display text
#   description_display: UK SNOMED description display (for extension)
#
# site_config (below) handles regex pattern matching for extraction.
# SITE_TO_SNOMED (derived) handles FHIR coding for matched sites.
# ---------------------------------------------------------------------------
SITES = {
    # keyword            snomed_code        snomed_display                  description_display
    "both eyes": ("40638003", "Structure of both eyes", "Both eyes"),
    "left eye": ("8966001", "Left eye structure", "Left eye"),
    "right eye": ("18944008", "Right eye structure", "Right eye"),
    "each eye": ("81745001", "Structure of eye", "Each eye"),
    "left nostril": ("91775001", "Structure of left nasal cavity", "Left nostril"),
    "right nostril": ("91776000", "Structure of right nasal cavity", "Right nostril"),
    "each nostril": ("45206002", "Nasal cavity structure", "Each nostril"),
    "nostrils": ("45206002", "Nasal cavity structure", "Nostrils"),
    "tongue": ("21974007", "Tongue structure", "Tongue"),
    "rectum": ("34402009", "Rectum structure", "Rectum"),
    "affected area": ("22201000087104", "Affected area", "Affected area"),
}

# ---------------------------------------------------------------------------
# Derived from SITES
# ---------------------------------------------------------------------------
SITE_TO_SNOMED = {
    k: {"code": code, "display": display, "descriptionDisplay": desc}
    for k, (code, display, desc) in SITES.items()
}

# ---------------------------------------------------------------------------
# EXTRAS_TO_SNOMED — SNOMED codes for additional instruction phrases.
#
# If an extras_clean text matches a key here, the FHIR additionalInstruction
# gets a coded entry instead of free text.
# ---------------------------------------------------------------------------
EXTRAS_TO_SNOMED = {
    "gently": {"code": "418449005", "display": "Gently"},
    "liberally": {"code": "419125005", "display": "Liberally"},
    "vigorously": {"code": "419913006", "display": "Vigorously"},
    "until finished": {"code": "421984009", "display": "Until finished"},
    "until gone": {"code": "420652005", "display": "Until gone"},
    "then discontinue": {"code": "421484000", "display": "Then discontinue"},
    "then stop": {"code": "422327006", "display": "Then stop"},
    "sparingly": {"code": "420883007", "display": "Sparingly"},
    "slowly": {"code": "419443000", "display": "Slowly"},
    "repeatedly": {"code": "769410007", "display": "Repeatedly"},
    "completely": {"code": "769408005", "display": "Completely"},
    "deeply": {"code": "769409002", "display": "Deeply"},
    "now": {"code": "421723005", "display": "Now"},
    "once only, at night": {
        "code": "13287601000001100",
        "display": "Once only, at night",
    },
    "once only": {"code": "422114001", "display": "Once only"},
    "only": {"code": "420295001", "display": "Only"},
    "thoroughly": {"code": "769407000", "display": "Thoroughly"},
    "as directed": {"code": "1116431000001106", "display": "As directed"},
}

# ---------------------------------------------------------------------------
# SPOON_SIZE_TO_SNOMED — SNOMED codes for spoonful sizes.
# 5ml has a UK SNOMED code; 2.5ml does not (display only).
# ---------------------------------------------------------------------------
SPOON_SIZE_TO_SNOMED = {
    "5": {"code": "514941000000109", "display": "5ml spoonful"},
    "2.5": {"code": None, "display": "2.5ml spoonful"},
}

# ---------------------------------------------------------------------------
# site_config — regex patterns for application site extraction
#
# Preposition constraints per body part:
#   eye      → in/into/to/on  (all four)
#   nostril  → in/into/to/on  (all four)
#   area     → in/into/to/on  (all four; "inject into the area" is valid)
#   nail     → in/to/on       (no into)
#   tongue   → under/on/to/into (not "in the tongue")
#   rectum   → in/into/to     (no on/under)
# ---------------------------------------------------------------------------

_S_PREP_EYE = r"(?:in|into|to|on)"
_S_PREP_NOS = r"(?:in|into|to|on)"
_S_PREP_AREA = r"(?:in|into|to|on)"
_S_PREP_NAIL = r"(?:in|to|on|under)"
_S_PREP_RECT = r"(?:in|into|to)"
_S_PREP_TONG = r"(?:under|on|to|into)"
_S_ADJ = r"(?:affected |infected |painful )?"
_S_SIDE = r"(?:left |right |both |each )?"

site_config = [
    # eye — in/into/to/on, optional side or determiner
    rf"{_S_PREP_EYE}(?: the)? {_S_ADJ}{_S_SIDE}eyes?",
    # nostril — in/into/to/on, optional side or determiner
    rf"{_S_PREP_NOS}(?: the)? {_S_ADJ}{_S_SIDE}nostrils?",
    # area — in/into/to/on, optional determiner
    rf"{_S_PREP_AREA}(?: (?:the|each|an))? {_S_ADJ}areas?",
    # nail — in/to/on/under (no into)
    rf"{_S_PREP_NAIL}(?: the)? {_S_ADJ}nails?",
    # tongue — under/on/to/into (not "in")
    rf"{_S_PREP_TONG}(?: the)? tongue",
    # rectum — in/into/to (no on/under)
    rf"{_S_PREP_RECT}(?: the)? rectum",
    # bare entries — adjective/side without preposition
    rf"{_S_ADJ}{_S_SIDE}eyes?",
    rf"{_S_ADJ}{_S_SIDE}nostrils?",
    rf"{_S_ADJ}areas?",
    rf"{_S_ADJ}nails?",
    r"tongue",
    r"rectum",
]

# ---------------------------------------------------------------------------
# Priority Exceptions
# ---------------------------------------------------------------------------
# Cases where a sub-part element intentionally has higher priority than
# a compound element that contains it. In all other overlaps, the longer
# (more detailed) match wins automatically.

PRIORITY_EXCEPTIONS = {
    (
        "methodDirect",
        "frequencyWithMethod",
    ): "method extracted first, rescue gives compound the span",
    (
        "methodPassive",
        "frequencyWithMethod",
    ): "method extracted first, rescue gives compound the span",
    (
        "methodDirect",
        "whenWithMethod",
    ): "method extracted first, rescue gives compound the span",
    (
        "methodPassive",
        "whenWithMethod",
    ): "method extracted first, rescue gives compound the span",
    (
        "methodDirect",
        "doseQuantity",
    ): "dual-purpose words (spray/suck): method wins initially, rescue prefers doseQuantity when preceded by number",
}

ISOLATED_ELEMENTS = {loser for _, loser in PRIORITY_EXCEPTIONS}


# ---------------------------------------------------------------------------
# Numeric Validation Rules
# functions include: [
# - ("no_negatives",)
# - ("avoid_zero",)
# - ("below", N)
# - ("must_be_whole_num",)
# - ("must_be_greater_than", N)
# - ("avoid_emergency_numbers",)
# - ("avoid_years",)
# - ("avoid_times",)
# - ("only_halves_and_quarters",)
# - ]
# ---------------------------------------------------------------------------

EMERGENCY_NUMBERS = {"999", "111", "112", "911", "101"}
YEAR_RANGE = (1900, 2030)

# ── Thresholds ────────────────────────────────────────────────────────────────
HIGH_DOSE = 100
LOW_DOSE = 10
HIGH_FREQUENCY = 20
LOW_FREQUENCY = 10
HIGH_PERIOD = 100
LOW_PERIOD = 10
HIGH_MILLIGRAM = 5000
LOW_MILLIGRAM = 200
HIGH_DURATION = 365
LOW_DURATION = 52
HIGH_OFFSET = 120
LOW_OFFSET = 60
HIGH_MAX_DOSE = 100
LOW_MAX_DOSE = 20
HIGH_RATE = 100
LOW_RATE = 20
HIGH_COUNT = 20
LOW_COUNT = 10

# ── Validation groups ─────────────────────────────────────────────────────────

VALIDATION_GROUPS = {
    # ── Dose (e.g. "4 tablets", "1-2 puffs") ─────────────────────────────────
    "dose": {
        "confident": {
            "fields": [
                "doseQuantity_quantity",
                "doseRange_low",
                "doseRange_high",
            ],
            "rules": [
                ("no_negatives",),
                ("below", HIGH_DOSE),
                ("only_halfs_and_quarters",),
            ],
        },
        "risk_averse": {
            "fields": [
                "dose_QuantityValueOnly_value",
                "dose_QuantityValueAndMaxOnly_value",
                "dose_QuantityValueAndMaxOnly_valueMax",
            ],
            "rules": [
                ("no_negatives",),
                ("avoid_zero",),
                ("below", LOW_DOSE),
                ("avoid_emergency_numbers",),
                ("avoid_years",),
                ("avoid_times",),
                ("only_halfs_and_quarters",),
            ],
        },
        "max_rules": {
            "doseRange_high": ("must_be_greater_than", "doseRange_low"),
            "dose_QuantityValueAndMaxOnly_valueMax": (
                "must_be_greater_than",
                "dose_QuantityValueAndMaxOnly_value",
            ),
            "dose_QuantityValueAndMaxOnly_value": ("avoid_zero", False),
        },
    },
    # ── Dose x Milli (e.g. "120 x 42ml") ─────────────────────────────────────
    "dose_x_milli": {
        "confident": {
            "fields": [
                "doseXMilliValueOnly_value",
                "doseXMilliValueOnly_val_milli",
            ],
            "rules": [
                ("no_negatives",),
                ("avoid_zero",),
                ("below", 1),
                ("must_be_whole_num",),
            ],
        },
    },
    # ── Rate (e.g. "at a rate of 2 per 3 days") ──────────────────
    "rate_ratio": {
        "confident": {
            "fields": [
                "rateRatio_numerator",
                "rateRatio_denominator",
            ],
            "rules": [
                ("no_negatives",),
                ("avoid_zero",),
                ("below", HIGH_RATE),
                ("must_be_whole_num",),
            ],
        },
    },
    # ── Rate (e.g. "at a rate of 2 to 5 litres per minute") ──────────────────
    "rate_other": {
        "confident": {
            "fields": [
                "rateRange_low",
                "rateRange_high",
                "rateQuantity_value",
            ],
            "rules": [
                ("no_negatives",),
                ("avoid_zero",),
                ("below", HIGH_RATE),
            ],
        },
        "max_rules": {
            "rateRange_high": ("must_be_greater_than", "rateRange_low"),
        },
    },
    # ── Frequency (e.g. "4 times per day") ────────────────────────────────────
    "frequency": {
        "confident": {
            "fields": [
                "frequencyBare_frequency",
                "frequencyBare_frequencyMax",
                "frequencyWithMethod_frequency",
                "frequencyWithMethod_frequencyMax",
            ],
            "rules": [
                ("no_negatives",),
                ("avoid_zero",),
                ("below", HIGH_FREQUENCY),
                ("must_be_whole_num",),
            ],
        },
        "max_rules": {
            "frequencyBare_frequencyMax": (
                "must_be_greater_than",
                "frequencyBare_frequency",
            ),
            "frequencyWithMethod_frequencyMax": (
                "must_be_greater_than",
                "frequencyWithMethod_frequency",
            ),
            "frequencyWithMethod_frequency": ("avoid_zero", False),
            "frequencyBare_frequency": ("avoid_zero", False),
        },
    },
    # ── Count (e.g. "2 times", "once") ────────────────────────────────────────
    "count": {
        "confident": {
            "fields": [
                "count_count",
                "count_countMax",
            ],
            "rules": [
                ("no_negatives",),
                ("avoid_zero",),
                ("below", HIGH_COUNT),
                ("must_be_whole_num",),
            ],
        },
        "max_rules": {
            "count_countMax": ("must_be_greater_than", "count_count"),
        },
    },
    # ── Period (e.g. "every 4 days") ──────────────────────────────────────────
    "period": {
        "confident": {
            "fields": [
                "periodElement_period",
                "periodElement_periodMax",
            ],
            "rules": [
                ("no_negatives",),
                ("avoid_zero",),
                ("below", HIGH_PERIOD),
                ("must_be_whole_num",),
            ],
        },
        "max_rules": {
            "periodElement_periodMax": ("must_be_greater_than", "periodElement_period"),
        },
    },
    # ── When / Offset (e.g. "30 minutes after food") ─────────────────────────
    "when_offset": {
        "confident": {
            "fields": [
                "whenBare_offset",
                "whenBare_offsetMax",
                "whenWithMethod_offset",
                "whenWithMethod_offsetMax",
            ],
            "rules": [
                ("no_negatives",),
                ("avoid_zero",),
                ("below", HIGH_OFFSET),
                ("must_be_whole_num",),
            ],
        },
        "max_rules": {
            "whenBare_offsetMax": ("must_be_greater_than", "whenBare_offset"),
            "whenWithMethod_offsetMax": (
                "must_be_greater_than",
                "whenWithMethod_offset",
            ),
        },
    },
    # ── Milligram (e.g. "500mg", "4 to 5 ml") ────────────────────────────────
    "milligram": {
        "confident": {
            "fields": [
                "milligramValue_value",
                "milligramMax_value",
                "milligramMax_valueMax",
            ],
            "rules": [
                ("no_negatives",),
                ("below", HIGH_MILLIGRAM),
                ("avoid_emergency_numbers",),
                ("avoid_years",),
                ("avoid_times",),
            ],
        },
        "max_rules": {
            # Note: must_be_greater_than for milligramMax_valueMax is handled by
            # rule_milligram_range_consistency in cross_column_validity_rules.py, which accounts
            # for cross-unit ranges (e.g. 500mg to 1g where raw 1 < 500 but 1g > 500mg).
            "milligramMax_value": ("avoid_zero", False),
        },
    },
    # ── Duration (e.g. "for 5 days", "over 2 weeks") ─────────────────────────
    "duration": {
        "confident": {
            "fields": [
                "durationValue_value",
                "durationMax_value",
                "boundsDuration_value",
                "boundsDuration_valueMax",
            ],
            "rules": [
                ("no_negatives",),
                ("avoid_zero",),
                ("below", HIGH_DURATION),
                ("must_be_whole_num",),
            ],
        },
        "max_rules": {
            "boundsDuration_valueMax": ("must_be_greater_than", "boundsDuration_value"),
        },
    },
    # ── Max dose (e.g. "maximum of 8 tablets in a day") ───────────────────────
    "max_dose": {
        "confident": {
            "fields": [
                "maxDosePerPeriod_num_value",
                "maxDosePerPeriod_denom_value",
                "maxDosePerAdministration_value",
                "maxDosePerLifetime_value",
            ],
            "rules": [
                ("no_negatives",),
                ("avoid_zero",),
                ("below", HIGH_MAX_DOSE),
                ("must_be_whole_num",),
            ],
        },
    },
}


# ── Build flat NUMERIC_VALIDATION_RULES from groups ───────────────────────────


def _build_rules_from_groups(groups):
    rules = {}
    for group_config in groups.values():
        max_rules = group_config.get("max_rules", {})
        for tier_name, tier in group_config.items():
            if tier_name == "max_rules":
                continue
            for field in tier["fields"]:
                field_rules = list(tier["rules"])
                if field in max_rules:
                    field_rules.append(max_rules[field])
                rules[field] = field_rules
    return rules


NUMERIC_VALIDATION_RULES = _build_rules_from_groups(VALIDATION_GROUPS)


# ---------------------------------------------------------------------------
# Implied frequency rule — single source of truth
#
# When no explicit frequency count is stated (no frequencyBare / frequencyWithMethod),
# the model assumes frequency=1. This assumption is applied in two places:
#
#   1. PeriodElement.phrase_parts() — for period words ("each day", "per week", etc.)
#      The spaCy matcher captures the period and hardcodes frequency=IMPLIED_FREQUENCY.
#
#   2. _infer_period_for_daily_when() in matcher_run.py — for daily timing words
#      ("each morning", "every night", etc.) captured by WhenBare/WhenWithMethod.
#      Post-spaCy Spark SQL creates a synthetic periodElement with frequency,
#      period, and periodUnit all set from these constants.
#      This can't be done inside the spaCy UDF because WhenBare would need to
#      check whether PeriodElement/Frequency elements were already resolved —
#      cross-element logic belongs in the post-processing layer, not inside
#      individual element classes.
#
# The assumption is only safe when dose == IMPLIED_ONLY_IF_DOSE. This is
# validated by CC12 (rule_cc12_period_without_single_dose) in
# cross_column_validity_rules.py.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Row selection threshold — minimum dosage_count to include a dosage_lower
# group in the extraction pipeline. Set to None to disable filtering.
# ---------------------------------------------------------------------------
MIN_COUNT = 10000

# ---------------------------------------------------------------------------
# Assumptions:
# If each day is said, and dose = 1 then frequency of once is implied
# If each morning (or other specific time of day) is said, and dose = 1
# then period and frequency of once every day is implied
# ---------------------------------------------------------------------------
IMPLIED_FREQUENCY = "1"
IMPLIED_DAILY_PERIOD = "1"
IMPLIED_DAILY_UNIT = "day"
IMPLIED_ONLY_IF_DOSE = 1

# ---------------------------------------------------------------------------
# Pipeline constants — used by matcher_run.py
# ---------------------------------------------------------------------------

# Regex matching "each/every" + a daily timing word. Used by
# _infer_period_for_daily_when() to detect when elements that imply
# a daily period. See "Implied frequency rule" above.
DAILY_WHEN_RE = (
    r"^(each|every)\s+(morning|afternoon|evening|night|bedtime|noon|waking)$"
)

# Normalisation rules for when text → canonical FHIR timing form.
# Multiple phrasings map to the same FHIR EventTiming code (e.g. "in the morning",
# "at morning", "on a morning" all → MORN). Order matters: longer/more-specific
# keywords first to avoid partial matches (e.g. "bedtime" before "night").
# Phrases containing "meal" are excluded — they retain original specificity.
WHEN_NORMALISE_RULES = [
    (r".*\bbedtime\b.*", "at bedtime"),
    (r".*\bwaking\b.*", "on waking"),
    (r"^at noon$", "at noon"),
    (r".*\bmorning\b(?!.*meal).*", "in the morning"),
    (r".*\bafternoon\b.*", "in the afternoon"),
    (r".*\bevening\b(?!.*meal).*", "in the evening"),
    (r".*\bnight\b.*", "at night"),
]

# ---------------------------------------------------------------------------
# asNeededBoolean — all phrase forms that express "as needed" in prescriptions.
# "as needed" is the canonical form; all others are synonyms normalised to it.
# Used as:
#   - matcher patterns for asNeededBoolean_clean and asNeededCodeableConcept_clean
#   - ASNEEDED_NORMALISE_PATTERN  — normalises synonyms → "as needed" in _clean
#   - ASNEEDED_STRIP_PATTERN      — strips the prefix from ANCC_clean leaving
#                                   just the indication (e.g. "for pain")
# ---------------------------------------------------------------------------
asNeededBoolean = [
    "as needed",  # canonical form — normalise target, not stripped
    "as required",
    "when required",
    "if required",
    "if needed",
    "when needed",
    "as necessary",
    "if necessary",
    "when necessary",
    # "as req",  # removed — could mean "requested"
    # "when req",  # removed — could mean "requested"
    # "if req",  # removed — could mean "requested"
]

# Synonyms only (excludes "as needed" itself) — used to normalise _clean to canonical.
_AS_NEEDED_SYNONYMS = [s for s in asNeededBoolean if s != "as needed"]
ASNEEDED_NORMALISE_PATTERN = r"(?i)\b(?:{})\b".format(
    "|".join(re.escape(s) for s in _AS_NEEDED_SYNONYMS)
)

# Strip pattern — removes the entire asNeeded prefix (including canonical "as needed")
# from asNeededCodeableConcept_clean, leaving just the indication phrase.
ASNEEDED_STRIP_PATTERN = r"(?i)^(?:{}) ".format(
    "|".join(re.escape(s) for s in asNeededBoolean)
)

# ---------------------------------------------------------------------------
# INDICATIONS — single source of truth for indication/purpose SNOMED metadata.
#
# Maps the normalised indication phrase (as it appears in asNeededCodeableConcept_clean
# or forElement_clean after stripping the asNeeded prefix) to (snomed_code, snomed_display).
# Keys use the simplest form that will be substring-matched — longer/more-specific
# keys are checked first (sort by length descending in INDICATION_TO_SNOMED derivation).
#
# Lookup strategy (same pattern as _build_route / _build_site):
#   - Iterate INDICATION_TO_SNOMED longest-key-first
#   - Return first key that is a substring of the lowercased indication text
#   - Fall back to {"text": indication_text} if no match
#
# Codes use SNOMED CT International Edition unless marked †UK (UK extension).
# ---------------------------------------------------------------------------
INDICATIONS = {
    # ── Pain ──────────────────────────────────────────────────────────────────
    # More-specific pain types first so they win over bare "pain"
    "neuropathic pain": ("57676002", "Neuropathic pain"),
    "nerve-related pain": ("57676002", "Neuropathic pain"),
    "nerve related pain": ("57676002", "Neuropathic pain"),
    "muscle spasm": ("45352006", "Spasm"),
    "muscle pain": ("68962001", "Myalgia"),
    "breakthrough pain": ("22253000", "Pain"),  # no finer SNOMED code in common use
    "chronic pain": ("82423001", "Chronic pain"),
    "severe pain": ("22253000", "Pain"),
    "chest pain": ("29857009", "Chest pain"),
    "back pain": ("161891005", "Back pain"),
    "joint pain": ("57676002", "Joint pain"),
    "stomach pain": ("21522001", "Stomach pain"),
    "bowel spasm pain": ("21522001", "Stomach pain"),
    "pain relief": ("22253000", "Pain"),
    "pain": ("22253000", "Pain"),
    # ── Cardiovascular ────────────────────────────────────────────────────────
    "high blood pressure/angina/palpitations": (
        "38341003",
        "Hypertension",
    ),  # combined phrase → lead concept
    "high blood pressure control": ("38341003", "Hypertension"),
    "high blood pressure": ("38341003", "Hypertension"),
    "blood pressure control": ("24184005", "Blood pressure finding"),
    "blood pressure": ("24184005", "Blood pressure finding"),
    "cardiovascular risk": ("395112001", "Cardiovascular disease risk"),
    "cardiovascular disease": ("49601007", "Cardiovascular disease"),
    "cvd risk": ("395112001", "Cardiovascular disease risk"),
    "cardiovascular": ("49601007", "Cardiovascular disease"),
    "cvd": ("49601007", "Cardiovascular disease"),
    "heart failure": ("84114007", "Heart failure"),
    "heart attack": ("22298006", "Myocardial infarction"),
    "heart disease": ("56265001", "Heart disease"),
    "heart strain": ("84114007", "Heart failure"),
    "heart": ("56265001", "Heart disease"),
    "angina": ("194828000", "Angina"),
    "palpitation": ("80313002", "Palpitation"),
    "palpitations": ("80313002", "Palpitation"),
    "high heart rate": ("3424008", "Tachycardia"),
    "heart rate": ("364075005", "Heart rate"),
    "blood clot": ("396275006", "Blood clot"),
    "blood clots": ("396275006", "Blood clot"),
    "stroke": ("230690007", "Stroke"),
    "further stroke": ("230690007", "Stroke"),
    # ── Metabolic / endocrine ─────────────────────────────────────────────────
    "high cholesterol": ("13644009", "Hypercholesterolaemia"),
    "raised cholesterol": ("13644009", "Hypercholesterolaemia"),
    "cholesterol control": ("13644009", "Hypercholesterolaemia"),
    "cholesterol": ("13644009", "Hypercholesterolaemia"),
    "high blood sugar": ("80394007", "Hyperglycaemia"),
    "blood sugar": ("33747003", "Blood glucose"),
    "sugar levels": ("33747003", "Blood glucose"),
    "sugar": ("33747003", "Blood glucose"),
    "bp control": ("24184005", "Blood pressure finding"),
    "bp": ("24184005", "Blood pressure finding"),
    "diabetes": ("73211009", "Diabetes mellitus"),
    "thyroid levels": ("14304000", "Thyroid disorder"),
    "thyroid": ("14304000", "Thyroid disorder"),
    "vitamin d": ("34713006", "Vitamin D deficiency"),
    "vitamin b12": ("444683003", "Vitamin B12 deficiency"),
    "folic acid": ("190634004", "Folic acid deficiency"),
    "folate": ("190634004", "Folic acid deficiency"),
    "iron levels": ("35240004", "Iron deficiency"),
    "iron": ("35240004", "Iron deficiency"),
    "anaemia": ("271737000", "Anaemia"),
    "gout": ("90560007", "Gout"),
    "osteoporosis": ("64859006", "Osteoporosis"),
    "deficiency": ("260372006", "Deficiency"),
    # ── Respiratory ───────────────────────────────────────────────────────────
    "breathlessness": ("230145002", "Difficulty breathing"),
    "copd": ("13645005", "COPD"),
    "wheeze": ("56018004", "Wheezing"),
    "sputum": ("45710003", "Sputum"),
    "mucus": ("405777007", "Mucus"),
    # ── GI / abdominal ────────────────────────────────────────────────────────
    "stomach acid": ("73550003", "Gastric acid"),
    "stomach": ("21522001", "Stomach pain"),
    "heartburn": ("16331000", "Heartburn"),
    "indigestion": ("27822002", "Indigestion"),
    "constipation": ("14760008", "Constipation"),
    "nausea": ("422587007", "Nausea"),
    "irritable bowel syndrome": ("10743008", "Irritable bowel syndrome"),
    "irritable bowel": ("10743008", "Irritable bowel syndrome"),
    "bowel spasm": ("45352006", "Spasm"),
    "bowel syndrome": ("10743008", "Irritable bowel syndrome"),
    "bowel symptoms": ("21522001", "Stomach pain"),
    "bowel": ("71854001", "Bowel"),
    "ulcer": ("13200003", "Peptic ulcer"),
    # ── Urological ────────────────────────────────────────────────────────────
    "incontinence": ("165232002", "Incontinence"),
    "bladder control": ("165232002", "Incontinence"),
    "bladder": ("57773001", "Bladder"),
    "prostate": ("41216001", "Prostate"),
    # ── Musculoskeletal ───────────────────────────────────────────────────────
    "spasm": ("45352006", "Spasm"),
    "fracture": ("125605004", "Fracture"),
    "fractures": ("125605004", "Fracture"),
    # ── Mental health / neurology ─────────────────────────────────────────────
    "anxiety": ("48694002", "Anxiety"),
    "mood and sleep": ("366979004", "Low mood"),  # combined phrase
    "mood": ("366979004", "Low mood"),
    "insomnia": ("193462001", "Insomnia"),
    "sleep": ("193462001", "Insomnia"),
    "chronic migraine": ("37796009", "Migraine"),
    "chronic fatigue": ("52702003", "Chronic fatigue syndrome"),
    "chronic urticaria": ("400228002", "Urticaria"),
    "chronic rhinitis": ("40122008", "Rhinitis"),
    "dizziness": ("404640003", "Dizziness"),
    # ── Immunological / dermatological ────────────────────────────────────────
    "allergies": ("408439002", "Allergy"),
    "allergy": ("408439002", "Allergy"),
    "irritable skin": ("418290006", "Itch"),
    "dry eyes": ("46742003", "Dry eye syndrome"),
    # ── Infection ─────────────────────────────────────────────────────────────
    "infections": ("40733004", "Infection"),
    "infection": ("40733004", "Infection"),
    # ── Risk reduction (generic) ──────────────────────────────────────────────
    "risk of heart attack": ("22298006", "Myocardial infarction"),
    "risk of stroke": ("230690007", "Stroke"),
    "risk of blood clots": ("396275006", "Blood clot"),
    "risk of cardiovascular disease": ("49601007", "Cardiovascular disease"),
    "risk of heart disease": ("56265001", "Heart disease"),
    "risk of cvd": ("49601007", "Cardiovascular disease"),
    "risk of dizziness": ("404640003", "Dizziness"),
    "risk of side effects": (None, None),  # too generic for a code
    "risk": (None, None),  # bare "risk" — fall through to text
    # ── Miscellaneous ─────────────────────────────────────────────────────────
    "disease": (None, None),  # too generic
    "clots": ("396275006", "Blood clot"),
    "prophylaxis": ("169443000", "Prophylaxis"),
}

# ---------------------------------------------------------------------------
# Derived from INDICATIONS — sorted longest-key-first so substring matching
# is greedy (e.g. "neuropathic pain" wins over "pain", "high blood pressure"
# wins over "blood pressure").
# ---------------------------------------------------------------------------
INDICATION_TO_SNOMED = {
    k: {"code": code, "display": display}
    for k, (code, display) in sorted(
        INDICATIONS.items(), key=lambda kv: len(kv[0]), reverse=True
    )
    if code is not None
}
