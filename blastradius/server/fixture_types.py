from typing import TypedDict


class DemoFixture(TypedDict):
    title: str
    root_cause: str
    change: str
    before_files: dict[str, str]
    after_files: dict[str, str]
