"""임시 폴더에 픽스처를 깔고 종료 코드와 CSV 열 이름을 검사한다."""

import csv
import subprocess
import sys
from pathlib import Path

from conftest import KO_TEXT, PDF_PAGES, build_fixture_dir, make_pdf
from golden_set.cli import CSV_COLUMNS, main


def test_validate_exit_1_when_any_file_fails(tmp_path: Path, capsys) -> None:
    root = build_fixture_dir(tmp_path / "fx")
    out = tmp_path / "report.csv"
    assert main(["validate", str(root), "--out", str(out)]) == 1

    with open(out, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == CSV_COLUMNS
        rows = {Path(r["path"]).name: r for r in reader}
    assert len(rows) == 9
    status = {name: r["status"] for name, r in rows.items()}
    assert status == {
        "ko_utf8.txt": "pass",
        "ko_cp949.txt": "pass",
        "two_paragraphs.docx": "pass",
        "three_pages.pdf": "pass",
        "two_slides.pptx": "pass",
        "with_blank.pdf": "fail",
        "broken.pdf": "error",
        "old.doc": "unsupported",
        "sheet.xlsx": "unsupported",
    }
    assert rows["with_blank.pdf"]["doc_count"] == "4"
    assert rows["with_blank.pdf"]["empty_ratio"] == "0.500"
    assert "empty_ratio" in rows["with_blank.pdf"]["reasons"]
    assert rows["three_pages.pdf"]["loader"] == "pymupdf"
    assert rows["three_pages.pdf"]["meta_ok"] == "True"
    assert float(rows["three_pages.pdf"]["elapsed_sec"]) >= 0
    assert rows["broken.pdf"]["doc_count"] == "" and rows["broken.pdf"]["reasons"]

    printed = capsys.readouterr().out
    assert "pass=5  fail=1  error=1  unsupported=2" in printed
    assert all(name in printed for name in rows)


def test_validate_exit_0_when_all_pass_and_unsupported_is_only_reported(tmp_path: Path, capsys) -> None:
    (tmp_path / "a.txt").write_text(KO_TEXT, encoding="utf-8")
    make_pdf(tmp_path / "b.pdf")
    (tmp_path / "old.ppt").touch()
    assert main(["validate", str(tmp_path)]) == 0
    assert "unsupported=1" in capsys.readouterr().out


def test_validate_samples_prints_first_300_chars_of_n_docs(tmp_path: Path, capsys) -> None:
    make_pdf(tmp_path / "b.pdf", ["가" * 400 + "끝", PDF_PAGES[1], PDF_PAGES[2]])
    main(["validate", str(tmp_path), "--samples", "2"])
    printed = capsys.readouterr().out
    assert printed.count("--- ") == 2
    assert "page=1" in printed and "page=2" in printed and "page=3" not in printed
    assert "끝" not in printed  # 300자에서 잘린다


def test_validate_missing_folder_exit_2(tmp_path: Path) -> None:
    assert main(["validate", str(tmp_path / "nope")]) == 2


def test_module_entry_point_exit_code(tmp_path: Path) -> None:
    root = build_fixture_dir(tmp_path / "fx")
    proc = subprocess.run(
        [sys.executable, "-m", "golden_set.cli", "validate", str(root)], capture_output=True, text=True
    )
    assert proc.returncode == 1
    assert "with_blank.pdf" in proc.stdout
