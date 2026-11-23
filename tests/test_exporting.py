"""exporting: 골든 후보를 awx1 형식으로 바꾼다."""

import json
from pathlib import Path

from golden_set.cli import main
from golden_set.domain.candidate import GoldenCandidate, Source, make_id
from golden_set.domain.store import write_candidates
from golden_set.exporting import EXPORTERS
from golden_set.exporting.awx import to_awx1, write_awx1


def candidate(n: int, question: str, answer: str, generator: str = "ragas") -> GoldenCandidate:
    return GoldenCandidate(make_id(generator, n), question, answer, ["근거 본문"], [Source("a.pdf:p1:0:aaaa", "a.pdf", 1)], "t", "ko", generator, "m")


CANDIDATES = [
    candidate(7, "이 사용자 매뉴얼은 어떤 시스템 버전 기준인가?", "AgenticWorks 1.1.4 기준으로 작성되었습니다."),
    candidate(1, "  평가를 새로 만들 때 누르는 버튼은?\n", " 평가 생성 버튼을 누릅니다. ", "deepeval"),
]


def test_to_awx1_has_exactly_three_keys_and_numbers_from_one() -> None:
    rows = to_awx1(CANDIDATES)
    assert rows == [
        {"id": 1, "query": "이 사용자 매뉴얼은 어떤 시스템 버전 기준인가?", "expected_response": "AgenticWorks 1.1.4 기준으로 작성되었습니다."},
        {"id": 2, "query": "평가를 새로 만들 때 누르는 버튼은?", "expected_response": "평가 생성 버튼을 누릅니다."},
    ]
    assert all(list(r) == ["id", "query", "expected_response"] and isinstance(r["id"], int) for r in rows)
    assert to_awx1([]) == []


def test_write_awx1_is_a_json_array_with_korean_as_is(tmp_path: Path) -> None:
    out = tmp_path / "golden.awx1.json"
    assert write_awx1(CANDIDATES, str(out)) == 2
    text = out.read_text(encoding="utf-8")
    assert text.startswith('[\n  {\n    "id": 1,\n    "query": "이 사용자 매뉴얼은') and text.endswith("]\n")
    assert "\\u" not in text
    assert json.loads(text) == to_awx1(CANDIDATES)
    assert EXPORTERS["awx1"] is write_awx1


def test_cli_export(tmp_path: Path, capsys) -> None:
    src, out = tmp_path / "candidates.jsonl", tmp_path / "golden.awx1.json"
    write_candidates(CANDIDATES, str(src))
    assert main(["export", str(src), "--format", "awx1", "--out", str(out)]) == 0
    assert capsys.readouterr().out == f"saved: {out}  (2 items, format=awx1)\n"
    assert [r["id"] for r in json.loads(out.read_text(encoding="utf-8"))] == [1, 2]


def test_cli_export_errors(tmp_path: Path, capsys) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert main(["export", str(empty), "--format", "awx1", "--out", str(tmp_path / "o.json")]) == 1
    assert main(["export", str(tmp_path / "none.jsonl"), "--format", "awx1", "--out", str(tmp_path / "o.json")]) == 2
    src = tmp_path / "candidates.jsonl"
    write_candidates(CANDIDATES, str(src))
    assert main(["export", str(src), "--format", "awx1", "--out", str(tmp_path / "no-dir" / "o.json")]) == 2
    assert capsys.readouterr().err.count("error:") == 3
