# Dosage Instructions

**NOTE:**

Dosage instructions is still in POC phase and going through testing. It is not ready for production until further review and testing has been complete.


## Overview
`dosage_instructions` is a Python-based project designed to extract, standardise, and model medication dosage instructions from clinical text. The aim is to convert free‑text instructions into structured representations suitable for analytics, downstream modelling, medication safety tooling, and operational reporting.

This codebase includes end‑to‑end components for data preparation, feature engineering, modelling, and evaluation. The project is designed to be modular, testable, and easy to extend.

---

## Running the model

#### To run model - appending to existing lookup
- Ensure eps_dose_clean and test40 datasets are up to date.
- Check that model/config/batch_size is as required 
    - Note that this model takes around 24 hours to run 10 million rows.
    - 2 hours 45 to run 1 million.
- In "Data Lineage", Shift to multiselect dosage_count, unioned_inputs and lookup_from_models and all the reports. Select Build
- Rerun (loop) through as many batches as required
- Once finished running as much data as required, select Build on refined_lookup


#### To run a full refresh of the lookup (wiping old matches)
- DON'T delete the lookup table.
- run_model.py holds a second transform, which is commented out, below the main one. To do a full reset of the lookup, use """ to comment out the first transform, and uncomment the second one. Run, this will wipe the lookup table. Then recomment the second transform, uncomment the first transform and run again as normal (see above).
##### Note: 
The lookup refresh method is a workaround due to foundry limitations - if foundry is updated this workaround should be removed and replaced with:
- Output should take the input "mode"="overwrite", 
- or the table itself can be rolled back to when it was empty.

---

## Repository Structure
```bash
dosage_instructions/
    data_enrichment/
        functions.py
        refine_lookup_output.py
    data_preparation/
        functions.py
        setup_group_doses.py
        setup_union_inputs.py
    for_review/
        lookup_reports.py
    model/
        config.py
        constants.py
        element_order_rules.py
        functions.py
        matcher_classes.py
        matcher_run.py
        run_model.py
    open_code_checklist.md
    pipeline.py
    to_test
test/
    constants/
    logic/
    outputs/
setup.py
README.md
LICENCE.md
```

### Key Components

**data_preparation/**  
Handles initial cleaning, parsing, and tokenisation of dosage text, including:
- lists and gives count of unique instructions from inputs  
- unions real with test data

**model/**  
- joins to the existing lookup table 
- identifies unmapped instructions and creates next batch for modelling 
Core modelling logic, including:
- configuration settings  
- shared functions  
- definitions of all the element classes used to align text to standardised element instructions
- definitions of all the element order grammar validity rules
- the main modelling and parsing pipeline  

**data_enrichment/**  
- refines the output to required format for users

**tests/**  
- constant tests: these check the configs, constants and elements that a developer may have added/removed. Ensuring that some rules are adhered to or considered.
- logic tests: Unit tests validating parsing logic, transformation behaviour, and model functions. In particular testing the logic of all the element classes.
- output tests: run these after the model has completed, to check for errors in the final output.

---

## Features

- **Structured dosage extraction:** Convert instructions such as  
  _“Take 2 tablets twice daily”_  
  into structured dosage instruction elements (like quantity, unit, route, frequency, timing, and duration) in a json format.

- **Configurable pipeline:** Modular design makes it easy to add or modify models, rules, or pattern libraries.

- **Clinically informed logic:** Incorporates common UK prescribing conventions.

- **Testable architecture:** `pytest` support ensures the whole workflow is checked and reproducible.

- **Single instructions:** The model does not try to capture instructions which capture multiple sequences or instances. This is to prevent risk of incorrectly mapping the input.

---

## Getting Started

### Installation

Clone the repository and install in editable mode:

```bash
pip install -e .
```
### Usage example

```bash

from dosage_instructions.model.pipeline import DosagePipeline

pipeline = DosagePipeline()

instruction = "Take 1 tablet by mouth every morning"

parsed = pipeline.parse(instruction)
print(parsed)
```

#### Example structured output
```bash
{
    "quantity": 1,
    "unit": "tablet",
    "route": "oral",
    "frequency": "once daily",
    "time_of_day": "morning"
}
```

### Development
#### Running tests
```bash
pytest
```

#### Local development in Foundry
If working in Foundry, you can:

- Use the Work locally option for fast iteration
Develop using VS Code with Foundry tooling. 
- Access native support for Python transforms

#### Contributing

Model is designed by the NHS England Data Science team and owned by NHS England Digital Meds team (Andy Pritchard) - england.digitalmedicines@nhs.net 

## Licence

The dosage instructions codebase is released under the MIT License.

The documentation is © Crown copyright and available under the terms of the Open Government 3.0 licence.

