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
    assert len(rows) == 10
    status = {name: r["status"] for name, r in rows.items()}
    assert status == {
        "ko_utf8.txt": "pass",
        "ko_cp949.txt": "pass",
        "two_paragraphs.docx": "pass",
        "three_pages.pdf": "pass",
        "with_header.pdf": "pass",
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
    assert "pass=6  fail=1  error=1  unsupported=2" in printed
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


# ---- 4단계: compare ----


def test_compare_runs_every_loader_for_the_format(tmp_path: Path, capsys) -> None:
    p = make_pdf(tmp_path / "b.pdf")
    assert main(["compare", str(p)]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 3  # 머리줄 + 로더 2개
    assert lines[1].split()[:3] == ["pymupdf", "pass", "3"]
    assert lines[2].split()[:3] == ["pdfplumber", "pass", "3"]


def test_compare_samples_per_loader(tmp_path: Path, capsys) -> None:
    p = make_pdf(tmp_path / "b.pdf")
    main(["compare", str(p), "--samples", "1"])
    printed = capsys.readouterr().out
    assert "[pymupdf] page=1" in printed and "[pdfplumber] page=1" in printed


def test_compare_exit_1_when_default_loader_fails(tmp_path: Path) -> None:
    assert main(["compare", str(make_pdf(tmp_path / "blank.pdf", ["", ""]))]) == 1
    broken = tmp_path / "broken.pdf"
    broken.touch()
    assert main(["compare", str(broken)]) == 1


def test_compare_unsupported_or_missing_exit_2(tmp_path: Path) -> None:
    xlsx = tmp_path / "a.xlsx"
    xlsx.touch()
    assert main(["compare", str(xlsx)]) == 2
    assert main(["compare", str(tmp_path / "none.pdf")]) == 2


# ---- 2단계: prepare ----


def test_prepare_writes_chunks_and_reports_removed_headers(tmp_path: Path, capsys) -> None:
    from golden_set.prepare import read_chunks

    root = tmp_path / "docs"
    root.mkdir()
    body = "강호의 규율은 무공이 아니라 신의에서 나온다고 장문인은 말했다. " * 4
    make_pdf(root / "law.pdf", [f"법제처 국가법령정보센터\n{body}제{n}조 본문\n형법 - {n} -" for n in range(1, 6)])
    (root / "note.txt").write_text(KO_TEXT * 3, encoding="utf-8")
    (root / "sheet.xlsx").touch()
    out = tmp_path / "chunks.jsonl"

    assert main(["prepare", str(root), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "removed from" in printed and "[head] x5" in printed and "[tail] x5" in printed
    assert "sheet.xlsx  (unsupported)" in printed
    assert f"saved: {out}" in printed

    chunks = read_chunks(str(out))
    assert len(chunks) >= 6
    texts = [c.page_content for c in chunks]
    assert not any("법제처" in t or "형법 -" in t for t in texts)
    assert all(len(t) <= 1200 for t in texts)
    pdf_chunks = [c for c in chunks if c.metadata["file_type"] == "pdf"]
    assert {c.metadata["page"] for c in pdf_chunks} == {1, 2, 3, 4, 5}
    assert all(c.metadata["chunk_id"] and c.metadata["loader"] == "pymupdf" for c in pdf_chunks)


def test_prepare_on_fixture_dir_removes_header_pdf_lines(tmp_path: Path, capsys) -> None:
    from golden_set.prepare import read_chunks

    root = build_fixture_dir(tmp_path / "fx")
    out = tmp_path / "chunks.jsonl"
    assert main(["prepare", str(root), "--out", str(out)]) == 1  # broken.pdf 때문에 1
    printed = capsys.readouterr().out
    assert "removed from" in printed and "with_header.pdf" in printed and "[tail] x5" in printed
    header_chunks = [c for c in read_chunks(str(out)) if c.metadata["source"].endswith("with_header.pdf")]
    assert len(header_chunks) == 5
    assert not any("국가법령정보센터" in c.page_content or c.page_content.endswith("-") for c in header_chunks)


def test_prepare_exit_1_on_load_error_but_still_writes(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.txt").write_text(KO_TEXT * 3, encoding="utf-8")
    (root / "broken.pdf").touch()
    out = tmp_path / "chunks.jsonl"
    assert main(["prepare", str(root), "--out", str(out)]) == 1
    assert out.exists()


def test_prepare_exit_2_when_no_chunks_or_bad_args(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "short.txt").write_text("제목만", encoding="utf-8")
    out = tmp_path / "chunks.jsonl"
    assert main(["prepare", str(root), "--out", str(out)]) == 2
    assert not out.exists()
    assert main(["prepare", str(tmp_path / "nope"), "--out", str(out)]) == 2
    assert main(["prepare", str(root), "--out", str(out), "--chunk-size", "100", "--overlap", "100"]) == 2


def test_prepare_chunk_options(tmp_path: Path) -> None:
    from golden_set.prepare import read_chunks

    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.txt").write_text(" ".join(f"{n}번째 문장은 길게 이어진다." for n in range(200)), encoding="utf-8")
    out = tmp_path / "chunks.jsonl"
    assert main(["prepare", str(root), "--out", str(out), "--chunk-size", "300", "--overlap", "0", "--min-chars", "50"]) == 0
    chunks = read_chunks(str(out))
    assert len(chunks) > 5 and all(len(c.page_content) <= 300 for c in chunks)


# ---- 검토 1: cp949 출력에서 죽지 않는다 ----


def test_samples_survive_cp949_stdout(tmp_path: Path) -> None:
    import os

    # \~ 는 U+00A0(줄바꿈 없는 공백)이 되고, 이 글자는 cp949에 없다
    body = "".join(c if ord(c) < 128 else f"\\u{ord(c)}?" for c in KO_TEXT.replace("\n", " "))
    (tmp_path / "nbsp.rtf").write_bytes(("{\\rtf1\\ansi " + body + "\\~end\\par}").encode("ascii"))
    proc = subprocess.run(
        [sys.executable, "-m", "golden_set.cli", "validate", str(tmp_path), "--samples", "1"],
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp949"},
    )
    out, err = proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8", errors="replace")
    assert "Traceback" not in err and "Traceback" not in out
    assert proc.returncode in (0, 1)
    assert " end" in out and "강호에" in out  # 재설정 뒤에는 utf-8로 나온다
