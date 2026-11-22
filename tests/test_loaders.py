from pathlib import Path

import pytest

from conftest import KO_TEXT
from golden_set.loaders import LoadError, Loader, TxtLoader
from golden_set.registry import load_path


def assert_common_meta(doc, path: Path, file_type: str, loader: str) -> None:
    assert doc.metadata["source"] == str(path)
    assert doc.metadata["file_type"] == file_type
    assert doc.metadata["loader"] == loader


def test_txt_utf8(txt_utf8: Path) -> None:
    docs = load_path(str(txt_utf8))
    assert len(docs) == 1
    assert docs[0].page_content == KO_TEXT
    assert_common_meta(docs[0], txt_utf8, "txt", "stdlib")
    assert "page" not in docs[0].metadata


def test_txt_cp949_is_read_by_retry(txt_cp949: Path) -> None:
    with pytest.raises(UnicodeDecodeError):
        txt_cp949.read_text(encoding="utf-8")  # utf-8로는 정말 안 읽히는 픽스처인지 확인
    docs = load_path(str(txt_cp949))
    assert docs[0].page_content == KO_TEXT


def test_txt_undecodable_raises_load_error(tmp_path: Path) -> None:
    p = tmp_path / "bad.txt"
    p.write_bytes(b"\xff\xff\xff\xff")
    with pytest.raises(LoadError):
        load_path(str(p))


def test_txt_missing_file_raises_load_error(tmp_path: Path) -> None:
    with pytest.raises(LoadError):
        load_path(str(tmp_path / "none.txt"))


def test_txt_loader_satisfies_protocol() -> None:
    assert isinstance(TxtLoader(), Loader)
