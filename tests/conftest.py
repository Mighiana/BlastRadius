from pathlib import Path

import pytest

from blastradius.graph import analyze, build_graph
from blastradius.parser import parse_directory

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
SAFE_DIR = EXAMPLES / "safe"
VULNERABLE_DIR = EXAMPLES / "vulnerable"


@pytest.fixture
def safe_config():
    return parse_directory(SAFE_DIR)


@pytest.fixture
def vulnerable_config():
    return parse_directory(VULNERABLE_DIR)


@pytest.fixture
def safe_result():
    return analyze(build_graph(parse_directory(SAFE_DIR)), "safe")


@pytest.fixture
def vulnerable_result():
    return analyze(build_graph(parse_directory(VULNERABLE_DIR)), "vulnerable")
