#!/usr/bin/env python
"""Python project setup script."""

import os
from setuptools import find_packages, setup

setup(
    name=os.environ["PKG_NAME"],
    version=os.environ["PKG_VERSION"],
    description="Python data transformation project",
    author="Product | Advanced Analytics Cross-Cutting Teams - National Analytics | User Workspace",
    packages=find_packages(exclude=["contrib", "docs", "test"]),
    # Please specify your dependencies in conda_recipe/meta.yaml instead.
    install_requires=[],
    entry_points={
        "transforms.pipelines": ["root = dosage_instructions.pipeline:my_pipeline"]
    },
)
