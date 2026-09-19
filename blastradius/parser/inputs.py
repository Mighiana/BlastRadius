from pathlib import Path

from blastradius.parser.plan_parser import parse_plan_file
from blastradius.parser.terraform_parser import parse_directory, parse_file


def parse_input(path: str | Path, phase: str = "after"):
    source = Path(path)
    if source.is_dir():
        return parse_directory(source)
    if source.suffix.lower() == ".json":
        return parse_plan_file(source, phase)
    return parse_file(source)
