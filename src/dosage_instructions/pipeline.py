from transforms.api import Pipeline

from dosage_instructions import data_preparation, model, data_enrichment, for_review

my_pipeline = Pipeline()
my_pipeline.discover_transforms(data_preparation)
my_pipeline.discover_transforms(model)
my_pipeline.discover_transforms(data_enrichment)
my_pipeline.discover_transforms(for_review)
