import os

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORKFLOWS = os.path.join(REPO_ROOT, ".github", "workflows")


def load(name):
    with open(os.path.join(WORKFLOWS, name)) as f:
        return yaml.safe_load(f)


def test_all_workflows_parse():
    for name in os.listdir(WORKFLOWS):
        if name.endswith((".yml", ".yaml")):
            assert load(name) is not None
