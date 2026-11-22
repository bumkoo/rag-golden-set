"""GoldenCandidate를 쓰고 다시 읽는다. 한글 보존과 필드 누락 오류를 본다."""

import json
from pathlib import Path

import pytest

from golden_set.candidates import (
    CandidateError,
    GoldenCandidate,
    Source,
    make_id,
    read_candidates,
    write_candidates,
)


def candidate(n: int = 1, **override) -> GoldenCandidate:
    values = dict(
        id=make_id("ragas", n),
        question="장문인이 말한 규율의 근원은 무엇인가?",
        reference_answer="신의다.",
        reference_contexts=["강호의 규율은 무공이 아니라 신의에서 나온다고 장문인은 말했다."],
        sources=[Source(chunk_id="a.pdf:p1:0:deadbeef", source="a.pdf", page=1)],
        question_type="single_hop_specific",
        language="ko",
        generator="ragas",
        model="qwen",
    )
    values.update(override)
    return GoldenCandidate(**values)


def test_make_id_format() -> None:
    assert make_id("ragas", 1) == "ragas-0001" and make_id("deepeval", 123) == "deepeval-0123"


def test_roundtrip_preserves_hangul_and_fields(tmp_path: Path) -> None:
    cands = [candidate(1), candidate(2, language="en", question="Who said it?", sources=[])]
    out = tmp_path / "c.jsonl"
    write_candidates(cands, str(out))
    raw = out.read_text(encoding="utf-8")
    assert raw.count("\n") == 2 and "장문인" in raw and "\\u" not in raw
    back = read_candidates(str(out))
    assert back == cands
    assert back[0].sources[0] == Source("a.pdf:p1:0:deadbeef", "a.pdf", 1)
    assert back[0].created_at.endswith("+00:00")


def test_append_mode(tmp_path: Path) -> None:
    out = tmp_path / "c.jsonl"
    write_candidates([candidate(1)], str(out))
    write_candidates([candidate(2)], str(out), append=True)
    assert [c.id for c in read_candidates(str(out))] == ["ragas-0001", "ragas-0002"]


@pytest.mark.parametrize("missing", ["question", "sources", "reference_contexts", "model", "generator"])
def test_missing_field_is_an_error_with_line_number(tmp_path: Path, missing: str) -> None:
    row = candidate().to_dict()
    del row[missing]
    p = tmp_path / "c.jsonl"
    p.write_text(json.dumps(candidate().to_dict(), ensure_ascii=False) + "\n" + json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(CandidateError, match=f"c.jsonl:2: missing fields: {missing}"):
        read_candidates(str(p))


def test_bad_json_and_bad_types_are_errors(tmp_path: Path) -> None:
    p = tmp_path / "c.jsonl"
    p.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(CandidateError, match="c.jsonl:1: not json"):
        read_candidates(str(p))
    row = candidate().to_dict()
    row["sources"] = [{"chunk": "wrong key"}]
    with pytest.raises(CandidateError, match="bad sources"):
        GoldenCandidate.from_dict(row)
    row = candidate().to_dict()
    row["question"] = 3
    with pytest.raises(CandidateError, match="question must be a string"):
        GoldenCandidate.from_dict(row)


def test_created_at_defaults_when_absent() -> None:
    row = candidate().to_dict()
    del row["created_at"]
    assert GoldenCandidate.from_dict(row).created_at
