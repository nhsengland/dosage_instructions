"""
Test cases for dosage instruction parsing.

HOW TO ADD TESTS
================

1. FULL TEXT (end-to-end):
   The buckets output uses " | " as separator between elements.

2. ELEMENT-SPECIFIC:
   Add to element_specific dict under the element_key name.
   - "capture": {"input text": "expected _clean value"}  → should match
   - "ignore":  ["input text", ...]                      → should NOT match

"""

# ─── FULL TEXT (end-to-end) ───────────────────────────────────────────────────
# input → expected buckets (exact match)

full_text = {
    "capture": {
        "one to be taken every day": "take | 1 | once every day",
        "take one and a half tablets on alternate days": "take | 1.5 tablets | once every 2 days",
        "Every day take 1": "take | 1 | once every day",
        "Take 1 every day": "take | 1 | once every day",
        "2 per day as directed": "2 | once every day | as directed",
        "1 at night": "1 | at night",
        "1 per day": "1 | once every day",
        "1 per day, home delivery service": "1 | once every day | home delivery service",
        "(amber 2) 1 per day": "1 | once every day | amber 2",
        "1 per day. replace every year": "1 | once every day | replace every year",
        "1 per day. replace every 2 days": "1 | once every day | replace every 2 days",
        "1 time with food": "once | with food",
        "1 tablet hourly": "1 tablet | once every hour",
        "as directed monthly": "once every month | as directed",
        # ── dose + frequency + route ──
        "take 2 tablets twice a day oral": "take | 2 tablets | 2 times every day | oral",
        "one capsule three times a day": "1 capsule | 3 times every day",
        # ── dose + frequency + when ──
        "take 1 tablet twice a day with food": "take | 1 tablet | 2 times every day | with food",
        "2 tablets at night when required": "2 tablets | at night | when required",
        # ── dose + frequency + duration ──
        "take 1 tablet three times a day for 5 days": "take | 1 tablet | 3 times every day | for 5 days",
        "2 capsules twice a day for 2 weeks": "2 capsules | 2 times every day | for 2 weeks",
        # ── dose + frequency + maxDose ──
        "1-2 tablets every 4 to 6 hours no more than 8 tablets in a day": "1 to 2 tablets | once every 4 to 6 hours | up to a maximum of 8 tablets in 1 day",
        # ── dose + frequency + for ──
        "take 1 tablet every day to lower cholesterol": "take | 1 tablet | once every day | to lower cholesterol",
        "2 tablets per day for pain": "2 tablets | once every day | for pain",
        # ── dose + rate ──
        "at a rate of 2 to 5 microgram per kilogram per hour": "at a rate of 2 to 5 microgram per kilogram per hour",
        # ── dose + asNeeded + purpose ──
        "1-2 tablets as needed for pain": "1 to 2 tablets | as needed for pain",
        # ── latin abbreviations (preprocessed) ──
        "one tablet bd": "1 tablet | 2 times every day",
        "2 capsules tds": "2 capsules | 3 times every day",
        # ── range dose + period ──
        "1-2 puffs every 4 hours as required": "1 to 2 puffs | once every 4 hours | as required",
        # ── dayOfWeek ──
        "take 1 tablet on mondays": "take | 1 tablet | on mondays",
        # ── timeOfDay ──
        "take 1 tablet at 8am": "take | 1 tablet | at 8am",
        # ── complex real-world ──
        "apply thinly twice a day": "apply | 2 times every day | thinly",
        "1 or 2 to be taken up to 3 times per day as directed": "take | 1 to 2 | up to 3 times every day | as directed",
        # ── simple dose + frequency combos ──
        "2 tablets every day": "2 tablets | once every day",
        "1 tablet(s) every day": "1 tablet | once every day",
        "2 tablet(s) every day": "2 tablets | once every day",
        "1 capsule per day": "1 capsule | once every day",
        "take 2 every morning": "take | 2 | every morning",
        "take 1 every night": "take | 1 | every night",
        "1 tablet twice a day": "1 tablet | 2 times every day",
        "2 capsules three times a day": "2 capsules | 3 times every day",
        "take 1 tablet four times a day": "take | 1 tablet | 4 times every day",
        "1 to be taken at night": "take | 1 | at night",
        "2 to be taken in the morning": "take | 2 | in the morning",
        # ── dose forms: puffs, drops, sachets ──
        "1-2 puffs twice a day": "1 to 2 puffs | 2 times every day",
        "2 puffs four times a day as required": "2 puffs | 4 times every day | as required",
        "1 sachet twice a day for constipation": "1 sachet | 2 times every day | for constipation",
        "2 drops in each eye twice a day": "2 drops | 2 times every day | in each eye",
        "up to 5 puffs as required": "up to 5 puffs | as required",
        # ── latin abbreviations (bd, tds, od, prn, nocte, mane) ──
        "1 tablet od": "1 tablet | once every day",
        "2 capsules bd for pain": "2 capsules | 2 times every day | for pain",
        "1 ttablet nocte": "1 tablet | at night",
        "take 1 mane": "take | 1 | every morning",
        "1-2 tablets prn": "1 to 2 tablets | when required",
        # ── milligram values and clarifications ──
        "take 5ml three times a day": "take | 5 ml | 3 times every day",
        "2.5ml twice a day": "2.5 ml | 2 times every day",
        "10ml three times a day for 5 days": "10 ml | 3 times every day | for 5 days",
        # ── duration and bounds ──
        "take 1 tablet per day for 3 weeks": "take | 1 tablet | once every day | for 3 weeks",
        "2 tablets three times a day for at least 5 days": "2 tablets | 3 times every day | for at least 5 days",
        "1 tablet per day for up to 2 weeks": "1 tablet | once every day | for up to 2 weeks",
        # ── max dose ──
        "1-2 tablets every 4 hours up to a maximum of 8 tablets in a day": "1 to 2 tablets | once every 4 hours | up to a maximum of 8 tablets in 1 day",
        "take 1-2 tablets every 6 hours no more than 6 tablets in a day": "take | 1 to 2 tablets | once every 6 hours | up to a maximum of 6 tablets in 1 day",
        "up to a maximum of 4 puffs per dose": "up to a maximum of 4 puffs per dose",
        # ── when/timing ──
        "take 1 tablet with food": "take | 1 tablet | with food",
        "1 tablet after a meal": "1 tablet | after a meal",
        "take 2 tablets with evening meal": "take | 2 tablets | with evening meal",
        "1 at bedtime": "1 | at bedtime",
        "take 1 tablet at least 2 minutes after waking": "take | 1 tablet | at least 2 minutes after waking",
        # ── asNeeded variants — all synonyms normalise to same bucket ──
        "1-2 tablets when required for pain": "1 to 2 tablets | as needed for pain",
        "1-2 tablets as required for pain": "1 to 2 tablets | as needed for pain",
        "1-2 tablets if needed for pain": "1 to 2 tablets | as needed for pain",
        "1-2 tablets when needed for pain": "1 to 2 tablets | as needed for pain",
        "1-2 tablets if required for anxiety": "1 to 2 tablets | as needed for anxiety",
        "1-2 tablets as necessary for nausea": "1 to 2 tablets | as needed for nausea",
        "take 1 if required": "take | 1 | if required",
        "1 tablet as required": "1 tablet | as required",
        # ── route ──
        "apply 1 patch transdermal every day": "apply | 1 patch | once every day | transdermal",
        "1 tablet sublingual as required": "1 tablet | sublingual | as required",
        # ── extras / additional instructions ──
        "take 1 tablet per day as directed": "take | 1 tablet | once every day | as directed",
        "1 tablet at ntight to help sleep": "1 tablet | at night | to help sleep",
        "2 per day sparingly": "2 | once every day | sparingly",
        "take 1 per day to reduce blood pressure": "take | 1 | once every day | to reduce blood pressure",
        # ── alternate day / other period patterns ──
        "1 tablet on alternate days": "1 tablet | once every 2 days",
        "take 2 tablets every other day": "take | 2 tablets | once every 2 days",
        "1 tablet every 2 weeks": "1 tablet | once every 2 weeks",
        "1 injection every 4 weeks": "1 injection | once every 4 weeks",
        # ── up to / range frequencies ──
        "1-2 tablets up to 4 times a day": "1 to 2 tablets | up to 4 times every day",
        "up to 2 puffs up to 4 times per day": "up to 2 puffs | up to 4 times every day",
        # ── count (no period) ──
        "take 2 tablets once": "take | 2 tablets | once",
        # ── complex real-world prescriptions ──
        "take 1-2 tablets every 4 to 6 hours as required for pain no more than 8 tablets in a day": "take | 1 to 2 tablets | once every 4 to 6 hours | as needed for pain | up to a maximum of 8 tablets in 1 day",
        "apply thinly to affected area twice a day": "apply | 2 times every day | to affected area | thinly",
        "to be taken twice a day with food for 5 days": "take | 2 times every day | with food | for 5 days",
        "1 capsule every morning for cholesterol": "1 capsule | every morning | for cholesterol",
        "take 1 tablet twice a day for heart failure": "take | 1 tablet | 2 times every day | for heart failure",
        "2 puffs twice a day via spacer": "2 puffs | 2 times every day | via spacer",
        "take 5ml four times a day for 5 days": "take | 5 ml | 4 times every day | for 5 days",
        "2 to 3 tablets per day as directed": "2 to 3 tablets | once every day | as directed",
        "take 1 tablet once a week": "take | 1 tablet | once every week",
        "half a tablet at night for nerve pain": "0.5 tablet | at night | for nerve pain",
        "1-2 x 5ml spoonful three times a day": "1 to 2 x 5ml spoonfuls | 3 times every day",
        "take 2 tablets every morning for diabetes": "take | 2 tablets | every morning | for diabetes",
        "1 tablet per day from 2.12.2024": "1 tablet | once every day | from 2.12.2024",
        "1 to 2 capsules up to twice a day when required": "1 to 2 capsules | up to 2 times every day | when required",
        "one - three a day": "1 to 3 | once every day",
        # ── dose_QuantityValueAndMaxOnly (bare range "1-2") + frequency ──
        "1-2 once every day": "1 to 2 | once every day",
        "2-bd": "2 | 2 times every day",
        "take 2 - twice daily": "take | 2 | 2 times every day",
        # ── frequencyBare must not duplicate when frequencyWithMethod wins ──
        "Take HALF a tablet To be taken Three Times Daily": "take | 0.5 tablet | 3 times every day",
        # ── dose + site + frequency (no when/timeOfDay) ──
        "1 drop both eyes 4 times a day": "1 drop | 4 times every day | both eyes",
        # ── instil as method (British spelling) ──
        "instil 1 drop every 4 hours": "instil | 1 drop | once every 4 hours",
    },
    "exclude": [
        "two tablets three a day",
        "as directed - one or two a day - 60 X200ml",
        "100",
        "Apply 2 pumps one daily",
        "take ONE capsule three a day",
        "take one capsule one daily",
        "take one tablet one at night to help lower cholesterol",
        "one half - 1 at night",
        "two at night - 200mg",
        "1 every day take",
        "1 take every day",
        "Take every day 1",
        "Every day 1 take",
        "2 per day may cause drowsiness",
        "take 2 tablets twice a day for 5 days then 1 tablet per day for constipation",
        "take 1",
        "1g",
        "1 tablet",
        "1 millilitre",
        "2.5ml at night (5mg)",
        "25ml (1000mg) twice daily",
        "Two x 2ml daily",
        "2 x 200mg per day",
        "1 per day home delivery service",
        "OneTo Be Taken in the morning",
        "1 per day on 12-01/23",
        "1 per day on 12/01-23",
        "1 per day on 12-01.23",
        "1 per day on 12/01.23",
        "1 tablet in the morning and 1 at night",
        "One To Be Taken Each Day for 10 years (2023-2033)",
        "1 - 2 times every day",
        "take 1 - 2 times every day",
        "take 120 every day",
        "take 11 every day",
        "take 2024mls every day",
        "take 2. 5ml every day",
        "take 1 or 2 - 3 times a day",  # not sure where this one is meant to sit
        "take 1 every other fortnight",
        "1 tablet (500mg) every 4 hours",
        "half 5mg to be taken daily",
        "quarter at 7am",
        "1 tablet every day in the eye(s)",  # (s) on site term not resolved — free text remains
        "1 3 times a day",  # bare number directly adjacent to frequency — no unit between
        "1 - 60mg tablet every day",  # strength embedded in dose form
        "take 1 tablet on monday",  # singular dayOfWeek without frequency/period (CC6)
    ],
}


# ─── PREPROCESSING ───────────────────────────────────────────────────────────
# step_name → {input: expected_dosage_lower}
# "full" = end-to-end preprocess_dosage; others test individual sub-steps.

preprocess_tests = {
    "full": {
        "Take ONE tablet": "take 1 tablet",
        "Take TWO Tablets Daily": "take 2 tablets every day",
        "2 and a half tablets per day": "2.5 tablets per day",
        "3 and a half of a tablet per day": "3.5 tablet per day",
        "half a tablet": "0.5 tablet",
        "half of one tablet": "0.5 tablet",
        "quarter of one tablet": "0.25 tablet",
        "3 quarters of one tablet": "0.75 tablet",
        "One tablet bd": "1 tablet . 2 times every day",
        "  take one tablet  ": "take 1 tablet",
        "take one tablet...": "take 1 tablet",
        # "1hr later": "1 hour later",
        # "take 2hrs before food": "take 2 hours before food",
        "take 1 tablet(s)": "take 1 tablet(s)",
        "take 2 tablet(s)": "take 2 tablet(s)",
        "from 2/12/2024 to 04/12/2024": "from 2.12.2024 to 04.12.2024",
        "from 2-12-2024 to 04-12-2024": "from 2.12.2024 to 04.12.2024",
        "until 2-12-2024": "until 2.12.2024",
        "on 2/12/2024": "on 2.12.2024",
        "on 04/12/2024": "on 04.12.2024",
        "on 30-09-2023": "on 30.09.2023",
        "on 1-4-1998": "on 1.4.1998",
        "on 24/12/2024": "on 24.12.2024",
        "on 2024/12/10": "on 2024.12.10",
        "on 14/12/2024": "on 14.12.2024",
        "on 04/12/2010": "on 04.12.2010",
        "on 23-09-2023": "on 23.09.2023",
        "on 2023-09-23": "on 2023.09.23",
        "on 12-01/2023": "on 12-01/2023",
        "on 12/01-2023": "on 12/01-2023",
        "on 12-01.2023": "on 12-01.2023",
        "on 12/01.2023": "on 12/01.2023",
        "Two 5ml Spoonfuls (5mg) To Be Taken Each Day": "2 x 5ml spoonfuls (5mg) to be taken each day",
    },
    "lower": {
        "ONE": "one",
        "Take TWO": "take two",
        "DAILY": "daily",
    },
    "latin": {
        "od": "every day",
        "bd": ". 2 times every day",
        "tds": ". 3 times every day",
        "prn": ". when required",
        "a.c.": "before food",
        "nocte": "at night",
        "mane": "every morning",
        "tamotidine": "tamotidine",
        "antidepressant": "antidepressant",
        "tidal breathing": "tidal breathing",
    },
    "words_to_digits": {
        "one tablet": "1 tablet",
        "two tablets": "2 tablets",
        "ten drops": "10 drops",
        "five ml": "5 ml",
    },
    "isolated_terms": {
        "daily": "every day",
        "weekly": "every week",
        "monthly": "every month",
        "twice a day": ". 2 times a day",
        "once or twice a day": ". 1 or 2 times a day",
        "half a tablet": "0.5 tablet",
        "half of a tablet": "0.5 tablet",
        "half of 1 tablet": "0.5 tablet",
        "quarter of 1 tablet": "0.25 tablet",
        "3 quarters of 1 tablet": "0.75 tablet",
        "2 and a half tablets": "2.5 tablets",
        "3 and 3 quarters of a tablet": "3.75 tablet",
        "1 and a quarter of a tablet": "1.25 tablet",
        # "1hr": "1 hour",
        # "2hrs": "2 hours",
        "half a tab in the morning and a quarter of a tablet at night": "0.5 tab in the morning and a 0.25 tablet at night",
    },
    "exclude": {
        "oneone": "",
        "twotwo": "",
        "2times": "",
        "2times/day": "",
        "2 times/day": "2 times/day",
        "2time": "",
        "2 time": "2 time",
        "0ne": "",
        "One": "one",
        "0": "0",
        "one half": "",
        "half": "half",
        "one": "one",
        "one and a half": "one and a half",
        "0.5": "0.5",
        "oneto": "",
        "&amp;": "",
        "&gt;": "",
        "&lt;": "",
        "2.5ml spoon": "2.5ml spoon",
        "2 .5ml spoon": "",
        "2 . 5ml spoon": "",
        "2. 5ml spoon": "",
        # ── Ambiguous fraction-number patterns (excluded) ─────────────────────
        "half - one tablet": "",
        "half - 1 tablet": "",
        "half one tablet": "",
        "half 1 tablet": "",
        "half - two tablets": "",
        "half 2 tablets": "",
        "quarter - one tablet": "",
        "quarter one tablet": "",
        "quarter 1 tablet": "",
        "3 quarters - one tablet": "",
        "3 quarters 2 tablets": "",
        "half of two tablets": "",
        "half of 2 tablets": "",
        "quarter of 4 tablets": "",
        # ── Clear fraction patterns (NOT excluded) ────────────────────────────
        "half to one tablet": "half to one tablet",
        "half or one tablet": "half or one tablet",
        "half of one tablet": "half of one tablet",
        "half a tablet": "half a tablet",
        "half of a tablet": "half of a tablet",
        "quarter to one tablet": "quarter to one tablet",
        "quarter of a tablet": "quarter of a tablet",
        "half once daily": "half once daily",
        # ── Ambiguous "<number> <period-adverb>" patterns (excluded) ──────────
        # These are ambiguous: "4 hourly" could mean "every 4 hours" or "4 per hour"
        "4 hourly": "",
        "4-6 hourly": "",
        "4-hourly": "",
        "12 hourly": "",
        "6 monthly": "",
        "6-monthly": "",
        "2 weekly": "",
        "2-weekly": "",
        "3-4 weekly": "",
        "2 daily": "",
        "3 yearly": "",
        "10 minutely": "",
        "two hourly": "",
        "three weekly": "",
        "four-hourly": "",
        "six monthly": "",
        "ten daily": "",
        "instil 1 drop 4 hourly": "",
        # ── "1 <period-adverb>" is NOT excluded (unambiguous = once per period) ──
        "1 hourly": "1 hourly",
        "1-hourly": "1-hourly",
        "one hourly": "one hourly",
    },
}


# ─── ELEMENT SPECIFIC ─────────────────────────────────────────────────────────
# element_key → {"capture": {input: expected_clean}, "ignore": [inputs...]}

element_specific = {
    # ──────────────────────────────────────────────────────────────────────────
    "methodDirect": {
        "capture": {
            "take": "take",
            "to take": "take",
            "spray": "spray",
            "suck": "suck",
        },
        "partial": {
            "to be take": ["to be", "take"],
        },
        "ignore": [
            "takes",
            "to be taken",
            "supply",
            "dispense",
            "issue",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "methodPassive": {
        "capture": {
            "to be taken": "take",
            "taken": "take",
            "used": "use",
            "to be used": "use",
        },
        "ignore": [
            "take",
            "to be take",
            "to be takes",
            "to be taked",
            "takes",
            "take",
            "took",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "doseQuantity": {
        "capture": {
            "4 x 5 ml spoonful": "4 x 5ml spoonfuls",
            "4 x 5 ml spoon": "4 x 5ml spoonfuls",
            "4 x 5 mls spoonful": "4 x 5ml spoonfuls",
            "4 x 5ml spoonful": "4 x 5ml spoonfuls",
            "4 tablets": "4 tablets",
            "2 chewable tablets": "2 chewable tablets",
            "1 capsule": "1 capsule",
            "1 tablet": "1 tablet",
            "1 x 5ml spoonful": "1 x 5ml spoonfuls",
            "2 tablets": "2 tablets",
            "5 sprays": "5 sprays",
            "1 spray": "1 spray",
            "2 sucks": "2 sucks",
            "1 suck": "1 suck",
        },
        "ignore": [
            "tablets",
            "many tablets",
            "4.5 x 5ml spoonfuls",
            "4.25 x 5ml spoonfuls",
            "4.1 x 5ml spoonfuls",
            "11 x 5ml spoonfuls",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "dose_QuantityValueOnly": {
        "capture": {
            "1": "1",
            "3.25": "3.25",
            "0.5": "0.5",
            "10": "10",
            "2": "2",
            "120": "120",  # captures here but removes later with number validity rules
            "11": "11",  # captures here but removes later with number validity rules
        },
        "ignore": ["5.6", "eleven", "one hundred", "3-5"],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "doseXMilliValueOnly": {
        "capture": {
            "120 x 42ml": "120 x 42 ml",
            "120 x 42 ml": "120 x 42 ml",
            "120 x 42 mls": "120 x 42 mls",
            "120 x 42mls": "120 x 42 mls",
            "1 x 42ml": "1 x 42 ml",
            "5 x 4 millilitre": "5 x 4 millilitre",
            "5 x 4 milligram": "5 x 4 milligram",
            "5 x 4 mg": "5 x 4 mg",
            "1 x 1ml": "1 x 1 ml",
            "1 x 1mg": "1 x 1 mg",
            "2 x 2ml": "2 x 2 ml",
            "2 x 2mg": "2 x 2 mg",
        },
        "ignore": [
            "120",
            "42ml",
            "1 x x5ml",
            "1 x no.8ml",
            "no.8 x 1ml",
            "week1 x week1ml",
            "sulfate)2.5 x 1ml",
            "1 x case***5ml",
            "3.25 x 42ml",
            "0.5 x 42ml",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "dose_QuantityValueAndMaxOnly": {
        "capture": {
            "1-2": "1 to 2",
            "3.25 to 4": "3.25 to 4",
            "0.5 or 1": "0.5 to 1",
            "1 to 2": "1 to 2",
            "1 or 2": "1 to 2",
            "2 to 3": "2 to 3",
        },
        "ignore": [
            "5.6 - 5.7",
            "4 then 5",
            "2 and 3",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "doseRange": {
        "capture": {
            "1-2 tablets": "1 to 2 tablets",
            "2-3 tablets": "2 to 3 tablets",
            "up to 5 tablets": "up to 5 tablets",
            "up to 1 puff": "up to 1 puff",
            "2-3 x 5ml spoonful": "2 to 3 x 5ml spoonfuls",
            "1-4 x 5 ml spoonful": "1 to 4 x 5ml spoonfuls",
        },
        "ignore": [
            "tablets",
            "5 tablets",
            "1-2.2 tablets",
            "2.1-3 tablets",
            "up to 5.2 tablets",
            "up to 1.234 spray",
            "1 to 4.5 x 5ml spoonfuls",
            "1 or 4.25 x 5ml spoonfuls",
            "3 - 4.1 x 5ml spoonfuls",
            "2-11 x 5ml spoonfuls",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "rateRatio": {
        "capture": {
            "at a rate of 4 per day": "at a rate of 4 per day",
            "at a rate of 3 every 2 weeks": "at a rate of 3 every 2 weeks",
            "at a rate of 1 per day": "at a rate of 1 per day",
            "at a rate of 2 per day": "at a rate of 2 per day",
        },
        "ignore": [
            "4 per day",
            "rate of 4",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "rateRange": {
        "capture": {
            "at a rate of 1 to 4 litres per minute": "at a rate of 1 to 4 litres per minute",
            "at a rate of 1 to 2 litres per minute": "at a rate of 1 to 2 litres per minute",
            "at a rate of 2 to 3 litres per minute": "at a rate of 2 to 3 litres per minute",
            "at a rate of 2 to 3 milligrams per minute": "at a rate of 2 to 3 milligrams per minute",
            "at a rate of 2 to 5 microgram per kilogram per hour": "at a rate of 2 to 5 microgram per kilogram per hour",
        },
        "ignore": [
            "1 to 4 litres per minute",
            "at a rate of 5 litres per minute",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "rateQuantity": {
        "capture": {
            "at a rate of 5 litres per minute": "at a rate of 5 litres per minute",
            "at a rate of 1 litres per minute": "at a rate of 1 litres per minute",
            "at a rate of 2 milligrams per minute": "at a rate of 2 milligrams per minute",
            "at a rate of 2 microgram per kilogram per hour": "at a rate of 2 microgram per kilogram per hour",
        },
        "ignore": [
            "5 litres per minute",
            "at a rate of 1 to 4 litres per minute",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "durationValue": {
        "capture": {
            "over 5 days": "over 5 days",
            "over 1 day": "over 1 day",
            "over 2 days": "over 2 days",
            "over 4 hours": "over 4 hours",
            "over 30 minutes": "over 30 minutes",
        },
        "ignore": [
            "5 days",
            "for 5 days",
            "over 2 weeks",
            "over 1 fortnight",
            "over 3 months",
            "over 1 year",
            "over 2 annual",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "durationMax": {
        "capture": {
            "max 5 weeks": "maximum 5 weeks",
            "max 1 week": "maximum 1 week",
            "max 2 weeks": "maximum 2 weeks",
            "max 2 days": "maximum 2 days",
            "maximum 3 days": "maximum 3 days",
            "maximum 1 day": "maximum 1 day",
            "maximum 2 days": "maximum 2 days",
        },
        "ignore": [
            "5 weeks",
            "over 5 weeks",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "frequencyBare": {
        "capture": {
            "4 times per day": "4 times every day",
            "2 times per day": "2 times every day",
            "2 times each week": "2 times every week",
            "once a day": "once every day",
            "once every fortnight": "once every fortnight",
            "2 times a fortnight": "2 times every fortnight",
            "1 to 3 times per week": "1 to 3 times every week",
            "2 to 3 times per day": "2 to 3 times every day",
            "1-2 times a day": "1 to 2 times every day",
            "2-3 times a day": "2 to 3 times every day",
            "up to 6 times per week": "up to 6 times every week",
            "up to 2 times per day": "up to 2 times every day",
            "up to once per week": "up to once every week",
            "up to once per day": "up to once every day",
        },
        "ignore": [
            "4 times",
            "per day",
            "1 time a month",
        ],
        "partial": {
            "to be taken 4 times per day": ["to be taken", "4 times every day"],
        },
    },
    # ──────────────────────────────────────────────────────────────────────────
    "frequencyWithMethod": {
        "capture": {
            "to be taken 4 times per day": "4 times every day",
            "to be taken 2 times per day": "2 times every day",
            "to be taken 2 times each week": "2 times every week",
            "to be taken once a day": "once every day",
            "to be taken once every fortnight": "once every fortnight",
            "to be taken 2 times every fortnight": "2 times every fortnight",
            "to be taken 1 to 3 times per week": "1 to 3 times every week",
            "to be taken 2 to 3 times per day": "2 to 3 times every day",
            "to be taken 1-2 times a day": "1 to 2 times every day",
            "to be taken 2-3 times a day": "2 to 3 times every day",
            "to be taken up to 6 times per week": "up to 6 times every week",
            "to be taken up to 2 times per day": "up to 2 times every day",
        },
        "ignore": [
            "4 times per day",
            "once a day",
            "take 4 times per day",
            "to be take up to 2 times per day",
            "to be taked 2-3 times a day",
            "to be takes 2-3 times a day",
            "to be took 2-3 times a day",
            "to be taken 1 time a month",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "count": {
        "capture": {
            "2 times": "2 times",
            "5 times": "5 times",
            "once": "once",
            "up to 4 times": "up to 4 times",
            "up to 2 times": "up to 2 times",
        },
        "ignore": [
            "three - four times",
        ],
        "partial": {"1 - 2 times": ["1 -", "2 times"]},
    },
    # ──────────────────────────────────────────────────────────────────────────
    "periodElement": {
        "capture": {
            "every day": "once every day",
            "per day": "once every day",
            "each week": "once every week",
            "every month": "once every month",
            "a minute": "once every minute",
            "per 4 days": "once every 4 days",
            "per 2 days": "once every 2 days",
            "every 5 weeks": "once every 5 weeks",
            "every 2 days": "once every 2 days",
            "every 1-2 days": "once every 1 to 2 days",
            "every 2-3 days": "once every 2 to 3 days",
            "per 4 to 5 weeks": "once every 4 to 5 weeks",
            "per 2 to 3 days": "once every 2 to 3 days",
            "every other day": "once every 2 days",
            "each other week": "once every 2 weeks",
            "every 1 day": "once every day",
        },
        "ignore": [
            "day",
            "week",
            "monthly",  # converted to every month up during preprocessing
            "hourly",  # converted to every hour up during preprocessing
            "every year",  # year/annual excluded from periodElement
            "per year",
            "each annual",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "whenBare": {
        "capture": {
            "after a meal": "after a meal",
            "with evening meal": "with evening meal",
            "at noon": "at noon",
            "at least 12 minutes after waking": "at least 12 minutes after waking",
            "at least 2 minutes after waking": "at least 2 minutes after waking",
            "at least 2 days after waking": "at least 2 days after waking",
        },
        "ignore": [
            "meal",
            "evening meal",
            "noon",
        ],
        "partial": {
            "to be taken after a meal": ["to be taken", "after a meal"],
        },
    },
    # ──────────────────────────────────────────────────────────────────────────
    "whenWithMethod": {
        "capture": {
            "to be taken with food": "to be taken with food",
            "to be applied after main meal": "to be applied after main meal",
            "to be taken at least 12 minutes after waking": "to be taken at least 12 minutes after waking",
            "to be taken at least 2 days after waking": "to be taken at least 2 days after waking",
        },
        "ignore": [
            "with food",
            "after a meal",
            "take with food",
            "to be take 2 days after waking",
            "to be taked 2 days after waking",
            "to be takes 2 days after waking",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "milligramMax": {
        "capture": {
            "4 to 5 mls": "4 to 5 mls",
            "2 to 3 mls": "2 to 3 mls",
            "1 to 2 milligrams": "1 to 2 milligrams",
            "2 to 3 milligrams": "2 to 3 milligrams",
            "1 to 2 micrograms": "1 to 2 micrograms",
            "2 to 3 microgram": "2 to 3 microgram",
            "1 to 2 grams": "1 to 2 grams",
            "2 to 3 gram": "2 to 3 gram",
            # pattern2: low has its own unit
            "100mg to 200mg": "100 to 200 mg",
            "500mg to 1g": "500 to 1 g",
            "2ml to 5ml": "2 to 5 ml",
        },
        "ignore": [
            "5ml",
            "5 x 6ml",
            "4 ml",
            "1 to 5",
            "1 to case***5 ml",
            "sulfate)2.5 to 1ml",
            "week1 - 4 ml",
            "no.8 or 1ml",
            "no8ml",
            "-5",
            "3=0.5",
            ".5",
            "&gt;20",
            "(10",
            "10-20",
            # Dash-separated ranges: "-" deliberately excluded from pattern1
            # to avoid ambiguity (e.g. "1- 60mg" could be a typo). See comment
            # in MilligramMaxElement.define_pattern().
            "4 - 5 ml",
            "2 - 3 ml",
            "4 - 5 g",
            "2 - 3g",
            "4 - 5 gs",
            "2 - 3gs",
            "4 - 5 mcg",
            "2 - 3 mcgs",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "milligramValue": {
        "capture": {
            "4.5ml": "4.5 ml",
            "5.25mg": "5.25 mg",
            "3 mls": "3 mls",
            "2 milligrams": "2 milligrams",
            "1millilitre": "1 millilitre",
            "2ml": "2 ml",
            "2mg": "2 mg",
            "2 mls": "2 mls",
            "2millilitres": "2 millilitres",
            "2024 mls": "2024 mls",  # captured here but excluded in numerical validation later
            "0 ml": "0 ml",  # captured here but excluded later by avoid_zero numeric validation
        },
        "ignore": [
            "ml",
            "milligrams",
            "5",
            "case***5 ml",
            "sulfate)2.5ml",
            "week1 ml",
            "no.8 ml",
            "no8ml",
            "08:00 millilitres",
            "-5 mls",
            "mg][20:00ml",
            "take2.5 ml",
            "mg(2.5ml",
            "mls(5mg",
            "x5ml",
            ".5ml",
            "/2.5 ml",
            "day1ml",
            "6.12.24ml",
            "wk1ml",
            "sept23 ml",
            "o.5ml",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "dayOfWeek": {
        "capture": {
            "on monday": "on monday",
            "on mondays": "on mondays",
            "on tue": "on tue",
            "on mon": "on mon",
        },
        "ignore": [
            "monday",
            "tuesday",
        ],
        "partial": {
            "on tuesday and wednesday": ["and wednesday", "on tuesday"],
            "on wednesday, thursday and friday": [
                ", thursday and friday",
                "on wednesday",
            ],
        },
    },
    # ──────────────────────────────────────────────────────────────────────────
    "timeOfDay": {
        "capture": {
            "at 5pm": "at 5pm",
            "at 1am": "at 1am",
            "at 12 noon": "at 12 noon",
            "at 03:30": "at 03:30",
            "at 15:30": "at 15:30",
            "at 02:00": "at 02:00",
            "at 2am": "at 2am",
            "at 2pm": "at 2pm",
        },
        "ignore": [
            "5pm",
            "1am",
            "15:30",
            "at 1:45",  # ambiguous: could be 1:45am or 1:45pm
        ],
        "partial": {
            "at 1pm, 3pm and 5pm": [", 3pm and 5pm", "at 1pm"],
        },
    },
    # ──────────────────────────────────────────────────────────────────────────
    "maxDosePerPeriod": {
        "capture": {
            "up to a maximum of 3 tablets in 4 days": "up to a maximum of 3 tablets in 4 days",
            "maximum of 3 tablets in 4 weeks": "up to a maximum of 3 tablets in 4 weeks",
            "up to a maximum of 8 tablets in a day": "up to a maximum of 8 tablets in 1 day",
            "up to a maximum of 3 tablets in a day": "up to a maximum of 3 tablets in 1 day",
            "maximum of 3 tablets in a week": "up to a maximum of 3 tablets in 1 week",
            "up to a maximum of 3 tablets every day": "up to a maximum of 3 tablets in 1 day",
            "maximum of 3 tablets each week": "up to a maximum of 3 tablets in 1 week",
            "no more than 3 tablets in 4 days": "up to a maximum of 3 tablets in 4 days",
            "not more than 3 tablets in 4 weeks": "up to a maximum of 3 tablets in 4 weeks",
            "no more than 3 tablets in a day": "up to a maximum of 3 tablets in 1 day",
            "no more than 3 tablets every day": "up to a maximum of 3 tablets in 1 day",
            "up to a maximum of 2 tablets in 2 days": "up to a maximum of 2 tablets in 2 days",
            "maximum of 2 tablets in 2 days": "up to a maximum of 2 tablets in 2 days",
            "up to a max of 2 tablets in 2 days": "up to a maximum of 2 tablets in 2 days",
            "up to a maximum of 2 tablets in a day": "up to a maximum of 2 tablets in 1 day",
            "maximum of 2 tablets in a day": "up to a maximum of 2 tablets in 1 day",
            "up to a maximum of 2 tablets every day": "up to a maximum of 2 tablets in 1 day",
            "maximum of 2 tablets each week": "up to a maximum of 2 tablets in 1 week",
            "no more than 2 tablets in 2 days": "up to a maximum of 2 tablets in 2 days",
            "not more than 2 tablets in 2 days": "up to a maximum of 2 tablets in 2 days",
            "no more than 2 tablets in a day": "up to a maximum of 2 tablets in 1 day",
            "no more than 2 tablets every day": "up to a maximum of 2 tablets in 1 day",
        },
        "ignore": [
            "3 tablets in 4 days",
            "maximum 3 tablets",
            "up to a maximum of 3.2 tablets in 4 days",
            "up to a maximum of 3 tablets in 4.5 days",
            "maximum of 3.4 tablets in 4 weeks",
            "maximum of 3 tablets in 4.25 weeks",
            "up to a max of 3.12 tablets in 4 years",
            "up to a max of 3 tablets in 4.1 years",
            "up to a maximum of 3.2 tablets in a day",
            "maximum of 3.2 tablets in a week",
            "up to a maximum of 3.2 tablets every day",
            "maximum of 3.2 tablets each week",
            "no more than 3.2 tablets in 4 days",
            "not more than 3.2 tablets in 4 weeks",
            "no more than 3 tablets in 4.5 days",
            "not more than 3 tablets in 4.5 weeks",
            "no more than 3.2 tablets in a day",
            "no more than 3.2 tablets every day",
            # fortnight/month/year excluded from denom_options
            "up to a maximum of 3 tablets in a month",
            "no more than 3 tablets in a year",
            "maximum of 3 tablets per fortnight",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "maxDosePerAdministration": {
        "capture": {
            "up to a maximum of 5 puffs per dose": "up to a maximum of 5 puffs per dose",
            "up to a max of 5 puffs per dose": "up to a maximum of 5 puffs per dose",
            "no more than 5 puffs per dose": "up to a maximum of 5 puffs per dose",
            "not more than 5 puffs per dose": "up to a maximum of 5 puffs per dose",
            "up to a maximum of 2 tablets per dose": "up to a maximum of 2 tablets per dose",
            "up to a max of 2 tablets per dose": "up to a maximum of 2 tablets per dose",
            "no more than 2 tablets per dose": "up to a maximum of 2 tablets per dose",
            "not more than 2 tablets per dose": "up to a maximum of 2 tablets per dose",
        },
        "ignore": [
            "5 puffs per dose",
            "maximum 5 puffs",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "maxDosePerLifetime": {
        "capture": {
            "up to a maximum of 5 puffs per lifetime of the patient": "up to a maximum of 5 puffs for the lifetime of patient",
            "up to a max of 5 puffs for the lifetime of patient": "up to a maximum of 5 puffs for the lifetime of patient",
            "maximum of 5 puffs per lifetime of the patient": "up to a maximum of 5 puffs for the lifetime of patient",
            "not more than 5 puffs per lifetime of the patient": "up to a maximum of 5 puffs for the lifetime of patient",
            "up to a maximum of 2 tablets per lifetime of the patient": "up to a maximum of 2 tablets for the lifetime of patient",
            "up to a max of 2 tablets for the lifetime of patient": "up to a maximum of 2 tablets for the lifetime of patient",
            "maximum of 2 tablets per lifetime of the patient": "up to a maximum of 2 tablets for the lifetime of patient",
            "not more than 2 tablets per lifetime of the patient": "up to a maximum of 2 tablets for the lifetime of patient",
        },
        "ignore": [
            "5 puffs per lifetime",
            "maximum 5 puffs",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "boundsDuration": {
        "capture": {
            "for 5 days": "for 5 days",
            "for 3 weeks": "for 3 weeks",
            "for 1 to 3 months": "for 1 to 3 months",
            "for at least 4 hours": "for at least 4 hours",
            "for up to 5 days": "for up to 5 days",
            "for 2 days": "for 2 days",
            "for 2 to 3 days": "for 2 to 3 days",
            "for at least 2 days": "for at least 2 days",
            "for up to 2 days": "for up to 2 days",
        },
        "ignore": [
            "5 days",
            "over 5 days",
            "for two days",
            "for three weeks",
            "for 5 minutes",  # minute excluded from boundsDuration
            "for 30 minutes",
            "for at least 2 minutes",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "boundsPeriod": {
        "capture": {
            "from 2.12.2024 to 04.12.2024": "from 2.12.2024 to 04.12.2024",
            "from 30.09.2023 to 1.4.1998": "from 30.09.2023 to 1.4.1998",
            "from 2024.12.2 to 2024.12.04": "from 2024.12.2 to 2024.12.04",
            "from 2023.09.30 to 1998.1.4": "from 2023.09.30 to 1998.1.4",
        },
        "ignore": [
            "from 2.12.24 to 04.12.24",
            "from 41/12/24 to 04/12/24",
            "from 30.13.2023 to 1.4.1998",
            "from 24/13/2 to 24/12/04",
            "from 2023.30.09 to 1998.1.4",
            "from 2/12/24 to 04/12/24",
            "from 30/09/2023 to 1/4/1998",
            "from 24-12-2 to 24-12-04",
            "from 2023-30-09 to 1998-1-4",
            "from 2024.12.2 to 05.12.2024",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "boundsAPeriodStartEnd": {
        "capture": {
            "from 2.12.2024": "from 2.12.2024",
            "from 04.12.2024": "from 04.12.2024",
            "from 30.09.2023": "from 30.09.2023",
            "from 1.4.1998": "from 1.4.1998",
            "from 24.12.2024": "from 24.12.2024",
            "from 2024.12.10": "from 2024.12.10",
            "from 2023.09.23": "from 2023.09.23",
            "until 4.12.2024": "until 4.12.2024",
            "until 04.12.2010": "until 04.12.2010",
            "until 21.09.2009": "until 21.09.2009",
            "until 2024.12.24": "until 2024.12.24",
            "until 24.12.2010": "until 24.12.2010",
            "until 2023.09.23": "until 2023.09.23",
        },
        "ignore": [
            "2024.4.65",
            "from 1823/9/9",
            "from 2.12.1024",
            "from 04.12.24",
            "from 24.12.24",
            "from 24.12.10",
            "until 4.12.24",
            "until 24.12.24",
            "until 24.12.10",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "event": {
        "capture": {
            "on 2.12.2024": "on 2.12.2024",
            "on 04.12.2024": "on 04.12.2024",
            "on 30.09.2023": "on 30.09.2023",
            "on 1.4.1998": "on 1.4.1998",
            "on 2024.12.24": "on 2024.12.24",
            "on 24.12.2010": "on 24.12.2010",
            "on 14.12.2024": "on 14.12.2024",
            "on 04.12.2010": "on 04.12.2010",
            "on 23.09.2023": "on 23.09.2023",
        },
        "ignore": [
            "on 2.12.24",
            "on 2024-4-65",
            "on 1823/9/9",
            "30-09-2023",
            "on 30-09-2023",  # doesn't capture as needs \d-\d\d-\d to \d.\d\d.\d conversion
            "on 23/09/2023",  # doesn't capture as needs \d/\d\d/\d to \d.\d\d.\d conversion
            "on 2023.09.2023",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    # REGEX-EXTRACTED ELEMENTS (not spaCy matchers)
    # These use reg_extract_and_tag_element (regex, not spaCy matchers).
    # They grab text verbatim — no cleaning/formatting applied.
    # ──────────────────────────────────────────────────────────────────────────
    "forElement": {
        "capture": {
            "to help lower cholesterol": "to help lower cholesterol",
            "to reduce blood pressure": "to reduce blood pressure",
            "for pain": "for pain",
            "for anxiety": "for anxiety",
            "for nausea": "for nausea",
            "for high blood pressure": "for high blood pressure",
            "for your heart": "for your heart",
            "for diabetes": "for diabetes",
            "to lower cholesterol": "to lower cholesterol",
            "for neuropathic pain": "for neuropathic pain",
            "for your cholesterol": "for your cholesterol",
            "for high cholesterol": "for high cholesterol",
            "to reduce risk of stroke": "to reduce risk of stroke",
            "for sleep": "for sleep",
            "for constipation": "for constipation",
            "to help stomach": "to help stomach",
            "to help thyroid": "to help thyroid",
            "for your mood and sleep": "for your mood and sleep",
            "for your neuropathic pain": "for your neuropathic pain",
        },
        "partial": {
            "as needed for pain": ["as needed", "for pain"],
        },
        "ignore": [
            "pain",
            "cholesterol",
            "as needed",  # bare asNeeded without indication
            "take 1 tablet",
            "every day",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    # asNeededCodeableConcept:
    # Compound element — matched as "asNeededBoolean + for_config" in one regex.
    # After matching, the asNeeded prefix is stripped so _clean = indication only
    # (e.g. "for pain"). The bucket builder prepends "as needed " for display.
    # All synonym forms normalise to the same _clean value.
    # ──────────────────────────────────────────────────────────────────────────
    "asNeededCodeableConcept": {
        # NOTE: the expected value here is what the raw regex captures (full phrase
        # including the asNeeded prefix). The prefix-stripping step happens later
        # in matcher_run via ASNEEDED_STRIP_PATTERN — it's a Spark column transform,
        # not part of the regex match itself. The full_text tests verify end-to-end
        # that the bucket shows "as needed for pain" (prefix prepended at bucket time).
        "capture": {
            "as needed for pain": "as needed for pain",
            "when required for pain": "when required for pain",
            "as required for pain": "as required for pain",
            "if needed for pain": "if needed for pain",
            "as needed for anxiety": "as needed for anxiety",
            "as needed for nausea": "as needed for nausea",
            "as needed for high blood pressure": "as needed for high blood pressure",
            "as needed to reduce blood pressure": "as needed to reduce blood pressure",
            "as needed for your cholesterol": "as needed for your cholesterol",
        },
        "ignore": [
            "for pain",  # indication alone without asNeeded prefix
            "as needed",  # asNeeded without indication
            "take 1 tablet",
            "every day",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "route": {
        "capture": {
            "oral": "oral",
            "subcutaneous": "subcutaneous",
            "intravenous": "intravenous",
            "nasal": "nasal",
            "rectal": "rectal",
            "sublingual": "sublingual",
            "intramuscular": "intramuscular",
            "transdermal": "transdermal",
        },
        "partial": {
            "take 1 tablet oral": ["take 1 tablet", "oral"],
            "2mg subcutaneous injection": ["2mg injection", "subcutaneous"],
            "intravenous infusion 5ml": ["infusion 5ml", "intravenous"],
        },
        "ignore": [
            "take 1 tablet",
            "2mg daily",
            "apply to skin",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "asNeededBoolean": {
        "capture": {
            "as required": "as required",
            "when required": "when required",
            "if required": "if required",
            "as needed": "as needed",
            "if needed": "if needed",
            "when necessary": "when necessary",
            "as necessary": "as necessary",
            "if necessary": "if necessary",
        },
        "partial": {
            "take 1 as required": ["take 1", "as required"],
            "2 tablets when required": ["2 tablets", "when required"],
            "use if needed for pain": ["use for pain", "if needed"],
        },
        "ignore": [
            "take 1 tablet",
            "every day",
            "as directed",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "extras": {
        "capture": {
            "sparingly": "sparingly",
            "thinly": "thinly",
        },
        "partial": {
            "sparingly to affected area": ["to affected area", "sparingly"],
        },
        "ignore": [
            "as directed",  # now captured by extrasAsDirected, not extras
            "take 1 tablet",
            "every day",
            "2 tablets at night",
            "for heart failure",
            "for pain",
            "to lower cholesterol",
            "for constipation",
            "to reduce blood pressure",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "extrasAsDirected": {
        "capture": {
            "as directed": "as directed",
        },
        "partial": {
            "take 1 as directed": ["take 1", "as directed"],
        },
        "ignore": [
            "take 1 tablet",
            "every day",
            "sparingly",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "extrasALTER": {
        "capture": {
            "may cause drowsiness": "may cause drowsiness",
        },
        "partial": {
            "2 per day may cause drowsiness": ["2 per day", "may cause drowsiness"],
        },
        "ignore": [
            "take 1 tablet",
            "2 per day",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "extrasPAUSE": {
        "capture": {
            "not for long term use": "not for long term use",
            "these tablets are addictive so do not take regularly": "these tablets are addictive so do not take regularly",
            "potentially addictive": "potentially addictive",
        },
        "partial": {
            "take 1 not for long term use": ["take 1", "not for long term use"],
        },
        "ignore": [
            "take 1 tablet daily",
            "for short term use",
        ],
    },
    # ──────────────────────────────────────────────────────────────────────────
    "extras_b": {
        "capture": {
            "replace every 2 days": "replace every 2 days",
            "replace every 12 months": "replace every 12 months",
        },
        "partial": {
            "1 per day. replace every 2 days": ["1 per day.", "replace every 2 days"],
        },
        "ignore": [
            "take every 2 days",
            "1 per day",
        ],
    },
}
