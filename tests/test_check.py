"""후보 검증: 4장 표의 항목마다 경계값 후보를 만들어 검사한다. 요약과 CSV, cli check도 본다."""

import csv
from pathlib import Path

import pytest

from golden_set.candidates import GoldenCandidate, Source, make_id, write_candidates
from golden_set.check import CHECK_NAMES, CheckThresholds, check_candidates, check_one, duplicate_key, format_summary, summarize, write_csv

KO_CTX = "강호의 규율은 무공이 아니라 신의에서 나온다고 장문인은 말했다. 제자는 그 뜻을 오래도록 헤아리지 못했다."
EN_CTX = "The master never drew the sword, and the pupil did not understand why for many years."
CHUNK_IDS = {"a.pdf:p1:0:aaaa", "a.pdf:p2:0:aaaa", "b.txt:p0:0:bbbb"}


def cand(question: str = "장문인이 말한 규율의 근원은 무엇인가?", answer: str = "신의다.", contexts: list[str] | None = None, sources=None, generator: str = "ragas", n: int = 1, **extra) -> GoldenCandidate:
    values = dict(
        id=make_id(generator, n),
        question=question,
        reference_answer=answer,
        reference_contexts=[KO_CTX] if contexts is None else contexts,
        sources=[Source("a.pdf:p1:0:aaaa", "dir/a.pdf", 1)] if sources is None else sources,
        question_type="single_hop",
        language="ko",
        generator=generator,
        model="qwen",
    )
    values.update(extra)
    return GoldenCandidate(**values)


def reasons_of(c: GoldenCandidate) -> list[str]:
    return [r.split(":")[0] for r in check_one(c, CHUNK_IDS, CheckThresholds()).reasons]


def test_good_candidate_passes_with_metrics() -> None:
    r = check_one(cand(), CHUNK_IDS, CheckThresholds())
    assert r.passed and r.reasons == []
    assert (r.question_chars, r.question_language, r.context_language, r.source_count, r.sources) == (17, "ko", "ko", 1, ["a.pdf"])


@pytest.mark.parametrize("field, value", [("question", ""), ("question", "   "), ("answer", ""), ("contexts", []), ("contexts", ["", " "])])
def test_required_fields(field: str, value) -> None:
    c = cand(**{field: value})
    assert "required" in reasons_of(c)


def test_sources_must_exist_and_point_to_known_chunks() -> None:
    assert reasons_of(cand(sources=[])) == ["sources"]
    bad = cand(sources=[Source("a.pdf:p1:0:aaaa", "a.pdf", 1), Source("nope:p1:0:ffff", "nope.pdf", 1)])
    r = check_one(bad, CHUNK_IDS, CheckThresholds())
    assert r.reasons == ["sources: 1 chunk_id not in chunks.jsonl"]
    assert check_one(cand(), set(), CheckThresholds()).reasons == ["sources: 1 chunk_id not in chunks.jsonl"]


def test_question_length_boundaries_ignore_whitespace() -> None:
    assert reasons_of(cand(question=" ".join("가" * 10))) == []  # 10자 합격
    assert reasons_of(cand(question=" ".join("가" * 9))) == ["question_length"]
    assert reasons_of(cand(question="가" * 300)) == []  # 300자 합격
    assert reasons_of(cand(question="가" * 301)) == ["question_length"]
    assert reasons_of(cand(question="가" * 301, answer="")) == ["required", "question_length"]
    assert check_one(cand(question="왜?"), CHUNK_IDS, CheckThresholds(min_question_chars=2)).passed  # 기준값은 바꿀 수 있다
    assert not check_one(cand(question="왜?"), CHUNK_IDS, CheckThresholds(min_question_chars=3)).passed


def test_language_mismatch_by_hangul_ratio() -> None:
    assert reasons_of(cand(question="What did the master say about the rules?")) == ["language"]  # 한국어 근거에 영어 질문
    assert reasons_of(cand(question="장문인은 무엇을 말했는가?", contexts=[EN_CTX])) == ["language"]
    assert reasons_of(cand(question="RAG 파이프라인에서 chunk size는 왜 중요한가?")) == []  # 영어 용어가 섞여도 한글이 30% 이상
    strict = CheckThresholds(ko_hangul_ratio=0.9)
    assert not check_one(cand(question="RAG 파이프라인에서 chunk size는 왜 중요한가?"), CHUNK_IDS, strict).passed


def test_duplicates_ignore_whitespace_punctuation_and_case_within_generator() -> None:
    assert duplicate_key("장문인이 말한, 규율의 근원은 무엇인가?") == duplicate_key("장문인이말한규율의근원은무엇인가")
    assert duplicate_key("Why Did He Leave?") == duplicate_key("why did he leave")
    cands = [
        cand(n=1),
        cand(n=2, question="장문인이 말한 규율의 근원은 무엇인가"),
        cand(n=3, question="  장문인이 말한 규율의 근원은 무엇인가?!  "),
        cand(n=1, generator="deepeval"),  # 다른 생성기의 같은 질문은 중복이 아니다
        cand(n=4, question="제자는 무엇을 헤아리지 못했는가?"),
    ]
    results = check_candidates(cands, CHUNK_IDS)
    assert [r.passed for r in results] == [True, False, False, True, True]
    assert results[1].reasons == ["duplicate: same question seen earlier"] and results[2].reasons == results[1].reasons


@pytest.mark.parametrize(
    "text",
    [
        "<think>생각</think>장문인이 말한 규율의 근원은?",
        "장문인이 말한 규율의 근원은? </think>",
        "```json\n{...}\n```",
        '{"query": "장문인이 말한 규율의 근원은?"}',
        '"answer": "신의다"',
    ],
)
def test_residue_in_question_or_answer(text: str) -> None:
    assert "residue" in reasons_of(cand(question=text))
    assert "residue" in reasons_of(cand(answer=text))


def test_plain_quotes_and_braces_in_prose_are_not_residue() -> None:
    assert "residue" not in reasons_of(cand(question='장문인이 "신의"라고 부른 것은 무엇인가?'))
    assert "residue" not in reasons_of(cand(answer="문규 {제1조}는 신의를 말한다. 집합 {1, 2}와는 무관하다."))


@pytest.mark.parametrize(
    "question",
    ["위 글에서 장문인이 말한 규율의 근원은?", "이 문서에 따르면 제자는 무엇을 몰랐나?", "본문에서 말하는 규율의 근원은?", "According to the passage, what did the master say?", "What does THE CONTEXT say about the pupil?", "Based on this document, who left?"],
)
def test_deictic_questions(question: str) -> None:
    contexts = [EN_CTX] if question.isascii() else None
    assert "deictic" in reasons_of(cand(question=question, contexts=contexts))


def test_deictic_phrase_must_start_at_a_word_boundary() -> None:
    assert "deictic" not in reasons_of(cand(question="장문인이 문서에 적은 규율의 근원은 무엇인가?"))  # "...인이 문서에"는 "이 문서"가 아니다
    assert "deictic" not in reasons_of(cand(question="창건 당시 문서에 적힌 첫 조항은 무엇인가?"))  # "문서"만으로는 아니다
    assert "deictic" in reasons_of(cand(question="이 문서에 적힌 첫 조항은 무엇인가?"))
    # 한계: 문구 자체를 찾으므로 "the passage of time"처럼 다른 뜻으로 쓰인 경우도 걸린다. 검수자가 본다
    assert "deictic" in reasons_of(cand(question="What is the passage of time in the chronicle?", contexts=[EN_CTX]))


def test_all_check_names_are_exercised_and_reason_prefixes_match() -> None:
    failing = [
        cand(question=""),
        cand(sources=[]),
        cand(question="짧다?"),
        cand(question="English question about the rules?"),
        cand(question="<think>x</think> 장문인이 말한 규율의 근원은 무엇인가?"),
        cand(question="위 글에서 장문인이 말한 규율의 근원은?"),
    ]
    prefixes = {r.split(":")[0] for c in failing for r in check_one(c, CHUNK_IDS, CheckThresholds()).reasons}
    dup = check_candidates([cand(n=1), cand(n=2)], CHUNK_IDS)[1]
    prefixes |= {r.split(":")[0] for r in dup.reasons}
    assert prefixes == set(CHECK_NAMES)


def test_thresholds_defaults_match_plan() -> None:
    th = CheckThresholds()
    assert (th.min_question_chars, th.max_question_chars, th.ko_hangul_ratio) == (10, 300, 0.3)
    assert "위 글" in th.deictic_phrases and "the passage" in th.deictic_phrases and "the context" in th.deictic_phrases
    assert any("think" in p for p in th.residue_patterns)


# ---- 요약 ----


def test_summary_per_generator() -> None:
    cands = [
        cand(n=1),
        cand(n=2, question="제자는 무엇을 헤아리지 못했는가?", question_type="multi_hop", sources=[Source("a.pdf:p1:0:aaaa", "a.pdf", 1), Source("b.txt:p0:0:bbbb", "b.txt", None)]),
        cand(n=3, question="Why?", language="en"),  # 짧고 언어 불일치
        cand(n=1, generator="deepeval", question_type="Reasoning"),
        cand(n=2, generator="deepeval", question="위 글에서 규율의 근원은?", question_type="", sources=[]),
    ]
    summaries = summarize(check_candidates(cands, CHUNK_IDS))
    assert [s.generator for s in summaries] == ["deepeval", "ragas"]
    de, ra = summaries
    assert (ra.count, ra.passed, round(ra.pass_rate, 3)) == (3, 2, 0.667)
    assert ra.reasons == {"question_length": 1, "language": 1}
    assert ra.question_types == {"single_hop": 2, "multi_hop": 1} and ra.languages == {"ko": 2, "en": 1}
    assert ra.files == {"a.pdf": 3, "b.txt": 1}
    assert (de.count, de.passed) == (2, 1) and de.reasons == {"sources": 1, "deictic": 1}
    assert de.question_types == {"Reasoning": 1, "(none)": 1} and de.files == {"a.pdf": 1, "(no source)": 1}

    text = format_summary(summaries)
    assert "generator  candidates  passed  pass_rate" in text
    assert "ragas               3       2     66.7%" in text and "deepeval            2       1     50.0%" in text
    for title in ("fail reasons", "question types", "languages", "candidates per file"):
        assert title in text
    assert format_summary([]) == "no candidates"


def test_csv_columns_and_encoding(tmp_path: Path) -> None:
    results = check_candidates([cand(n=1), cand(n=2, question="짧다?")], CHUNK_IDS)
    out = tmp_path / "report.csv"
    write_csv(results, str(out))
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == ["id", "generator", "status", "question_chars", "question_language", "context_language", "source_count", "question_type", "language", "sources", "reasons", "question"]
    assert rows[0]["status"] == "pass" and rows[1]["status"] == "fail" and "question_length" in rows[1]["reasons"]
    assert rows[0]["question"] == "장문인이 말한 규율의 근원은 무엇인가?" and rows[0]["sources"] == "a.pdf"


# ---- cli ----


def write_chunks_file(path: Path) -> None:
    from langchain_core.documents import Document

    from golden_set.prepare import write_chunks

    docs = [Document(page_content=KO_CTX, metadata={"source": "dir/a.pdf", "file_type": "pdf", "loader": "t", "page": 1, "chunk_id": "a.pdf:p1:0:aaaa", "chunk_index": 0})]
    write_chunks(docs, str(path))


def test_cli_check_prints_table_summary_and_csv(tmp_path: Path, capsys) -> None:
    from golden_set.cli import main

    write_chunks_file(tmp_path / "chunks.jsonl")
    cands_path = tmp_path / "candidates.jsonl"
    write_candidates([cand(n=1), cand(n=2, question="Why?"), cand(n=1, generator="deepeval")], str(cands_path))
    out = tmp_path / "report.csv"
    assert main(["check", str(cands_path), "--out", str(out)]) == 0  # 옆의 chunks.jsonl을 찾는다
    printed = capsys.readouterr().out
    assert "ragas-0002" in printed and "question_length" in printed and "language" in printed
    assert "ragas               2       1     50.0%" in printed and "deepeval            1       1    100.0%" in printed
    assert f"saved: {out}" in printed and out.exists()


def test_cli_check_exit_codes(tmp_path: Path) -> None:
    from golden_set.cli import main

    chunks = tmp_path / "c" / "chunks.jsonl"
    chunks.parent.mkdir()
    write_chunks_file(chunks)
    cands_path = tmp_path / "candidates.jsonl"
    write_candidates([cand(n=1, sources=[])], str(cands_path))
    assert main(["check", str(cands_path), "--chunks", str(chunks)]) == 1  # 합격 0개
    assert main(["check", str(cands_path), "--chunks", str(tmp_path / "none.jsonl")]) == 2
    assert main(["check", str(tmp_path / "none.jsonl"), "--chunks", str(chunks)]) == 2
    (tmp_path / "bad.jsonl").write_text("{broken\n", encoding="utf-8")
    assert main(["check", str(tmp_path / "bad.jsonl"), "--chunks", str(chunks)]) == 2
    import os

    cwd = os.getcwd()
    os.chdir(tmp_path)  # 옆에도 현재 폴더에도 chunks.jsonl이 없다
    try:
        assert main(["check", str(cands_path)]) == 2
    finally:
        os.chdir(cwd)
