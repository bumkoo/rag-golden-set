from pathlib import Path

import pytest

from golden_set.loaders import UnsupportedError
from golden_set.registry import get_loader


def test_get_loader_default_by_extension() -> None:
    assert get_loader("a.txt").name == "stdlib"
    assert get_loader("A.TXT").name == "stdlib"


def test_get_loader_by_name() -> None:
    assert get_loader("a.txt", "stdlib").name == "stdlib"


def test_get_loader_unknown_name() -> None:
    with pytest.raises(UnsupportedError):
        get_loader("a.txt", "nope")


@pytest.mark.parametrize("name", ["a.xlsx", "a.doc", "a.ppt", "noext"])
def test_get_loader_unsupported_extension(name: str) -> None:
    with pytest.raises(UnsupportedError, match="unsupported"):
        get_loader(name)
