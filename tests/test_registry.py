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


# ---- 2단계: load_dir ----

from conftest import KO_TEXT, make_docx, make_pdf, make_pptx
from golden_set.loaders import LoadError
from golden_set.registry import Failure, load_dir


@pytest.mark.parametrize(
    "name,expected",
    [("a.pdf", "pymupdf"), ("a.docx", "docx2txt"), ("a.pptx", "python-pptx"), ("a.txt", "stdlib")],
)
def test_default_loader_per_format(name: str, expected: str) -> None:
    assert get_loader(name).name == expected


def test_load_dir_recurses_and_collects_failures(tmp_path: Path) -> None:
    (tmp_path / "sub" / "deep").mkdir(parents=True)
    (tmp_path / "a.txt").write_text(KO_TEXT, encoding="utf-8")
    (tmp_path / "broken.pdf").touch()  # 0바이트 pdf
    make_pdf(tmp_path / "sub" / "b.pdf")
    make_docx(tmp_path / "sub" / "c.docx")
    make_pptx(tmp_path / "sub" / "deep" / "d.pptx")
    (tmp_path / "sub" / "old.doc").touch()
    (tmp_path / "sheet.xlsx").touch()
    (tmp_path / ".hidden.txt").write_text("x", encoding="utf-8")

    docs, failures = load_dir(str(tmp_path))

    # 깨진 pdf가 이름순으로 b.pdf보다 먼저 오지만 실행은 끝까지 간다
    by_type: dict[str, int] = {}
    for d in docs:
        by_type[d.metadata["file_type"]] = by_type.get(d.metadata["file_type"], 0) + 1
    assert by_type == {"txt": 1, "pdf": 3, "docx": 1, "pptx": 2}

    reasons = {Path(f.path).name: f.reason for f in failures}
    assert set(reasons) == {"broken.pdf", "old.doc", "sheet.xlsx"}
    assert reasons["old.doc"] == "unsupported"
    assert reasons["sheet.xlsx"] == "unsupported"
    assert reasons["broken.pdf"] != "unsupported" and reasons["broken.pdf"]
    assert all(isinstance(f, Failure) for f in failures)


def test_load_dir_not_a_directory(tmp_path: Path) -> None:
    with pytest.raises(LoadError):
        load_dir(str(tmp_path / "nope"))


# ---- 4단계: 대안 로더 등록 ----

from golden_set.registry import loaders_for


def test_alt_loaders_registered_after_default() -> None:
    assert [l.name for l in loaders_for("a.pdf")] == ["pymupdf", "pdfplumber"]
    assert [l.name for l in loaders_for("a.docx")] == ["docx2txt", "python-docx"]
    assert [l.name for l in loaders_for("a.pptx")] == ["python-pptx", "unstructured"]
    assert [l.name for l in loaders_for("a.txt")] == ["stdlib"]
    assert loaders_for("a.xlsx") == []
    assert get_loader("a.pdf", "pdfplumber").name == "pdfplumber"
    with pytest.raises(UnsupportedError):
        get_loader("a.pdf", "docx2txt")  # 다른 형식의 로더 이름
