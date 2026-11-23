"""단계 로그: 진행 보고(progress.py), ragas 단계의 순서·이름·집계, generate의 화면 출력과 로그 파일."""

import io
import re
from pathlib import Path

import pytest
from conftest import fake_chat, fake_embed
from ragas.testset.graph import KnowledgeGraph, Node, NodeType, Relationship
from ragas_fake import RagasResponder, fake_ragas_factory, law_chunks

from golden_set.generation import GenerateReport
from golden_set.generation.llm import CallLog, Endpoint, LLMSettings
from golden_set.generation.progress import (
    ABORTED,
    DEEPEVAL_STAGES,
    RAGAS_STAGES,
    ConsoleReporter,
    ListReporter,
    ProgressReporter,
    Stages,
    display_width,
    format_duration,
    pad,
)
from golden_set.generation.ragas.generator import RagasGenerator
from golden_set.generation.ragas.stages import relation_stats, relation_summary

# ---- 글자 ----


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0초"), (39.4, "39초"), (60, "1분 00초"), (219, "3분 39초"), (123.6, "2분 04초"), (3723, "1시간 2분 03초")],
)
def test_format_duration(seconds: float, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_pad_uses_display_width_for_korean() -> None:
    assert display_width("요약") == 4 and display_width("context 구성") == 12
    assert pad("요약", 8) == "요약    " and pad("abcdefghij", 4) == "abcdefghij"
    assert len({display_width(pad(name, 20)) for name in RAGAS_STAGES + DEEPEVAL_STAGES}) == 1  # 요약 줄의 열이 맞는다


# ---- ConsoleReporter ----


def run_stage(reporter: ProgressReporter, total: int, summary: str = "끝") -> None:
    reporter.stage_started(1, 6, "요약", total)
    for _ in range(total):
        reporter.advanced()
    reporter.stage_finished(summary)


def test_reporters_follow_the_protocol() -> None:
    assert isinstance(ConsoleReporter(), ProgressReporter) and isinstance(ListReporter(), ProgressReporter)


def test_not_a_terminal_prints_one_line_per_ten_percent() -> None:
    out = io.StringIO()  # isatty()가 False다
    run_stage(ConsoleReporter(stream=out), 74, "74/74  3분 39초  LLM 74회  실패 0")
    lines = out.getvalue().splitlines()
    assert "\r" not in out.getvalue() and "\033" not in out.getvalue()  # 막대를 다시 그리지 않는다
    progress, summary = lines[:-1], lines[-1]
    assert summary == "[1/6] 요약                  74/74  3분 39초  LLM 74회  실패 0"
    assert len(progress) == 9  # 10%, 20%, ..., 90%. 100%는 요약 줄이 대신한다
    percents = [int(re.search(r"(\d+)%", line).group(1)) for line in progress]
    assert [p // 10 for p in percents] == list(range(1, 10))
    assert progress[0] == "[1/6] 요약                  8/74  10%"


def test_not_a_terminal_small_and_uncounted_stages() -> None:
    out = io.StringIO()
    reporter = ConsoleReporter(stream=out)
    run_stage(reporter, 3)  # 33%, 66%에서 한 줄씩
    reporter.stage_started(3, 6, "관계", None)
    reporter.advanced()
    reporter.stage_finished("유사도 2개")
    assert out.getvalue().splitlines() == [
        "[1/6] 요약                  1/3  33%",
        "[1/6] 요약                  2/3  66%",
        "[1/6] 요약                  끝",
        "[3/6] 관계                  유사도 2개",
    ]


def test_terminal_redraws_in_place_and_log_gets_only_summaries() -> None:
    out, log = io.StringIO(), io.StringIO()
    reporter = ConsoleReporter(stream=out, log=log, tty=True)
    run_stage(reporter, 4, "4/4  1초")
    reporter.line("generator=ragas  requested=4")
    screen = out.getvalue()
    assert screen.count("\r\033[K") >= 5  # 시작 1번 + 진행 4번, 줄바꿈 없이 제자리에서
    assert "2/4  50%" in screen
    assert screen.endswith("[1/6] 요약                  4/4  1초\ngenerator=ragas  requested=4\n")
    assert screen.count("\n") == 2  # 진행 줄은 쌓이지 않는다
    assert log.getvalue() == "[1/6] 요약                  4/4  1초\ngenerator=ragas  requested=4\n"


# ---- Stages ----


def test_stages_number_stages_and_count_requests_by_difference() -> None:
    rep = ListReporter()
    llm, embed, skipped = CallLog(), CallLog(), []
    llm.ok([])  # 단계 전에 보낸 요청은 세지 않는다
    stages = Stages(rep, ("가", "나"), llm=llm, embed=embed, skipped=skipped)

    stages.start("가", 2)
    llm.ok([])
    llm.fail("APIConnectionError: x")
    embed.ok([])
    skipped.append("transform X: bad")
    stages.advance()
    stages.advance()
    assert (stages.llm_requests, stages.embed_requests, stages.failed_items, stages.new_skips) == (2, 1, 1, ["transform X: bad"])
    stages.finish("1/2", timed=False, failed=stages.failed_items, tail="꼬리")

    stages.start("나")
    stages.finish("끝", timed=False)
    stages.advance()  # 닫힌 뒤의 진행은 버린다
    assert rep.events == [
        ("started", 1, 2, "가", 2),
        ("advanced", 1),
        ("advanced", 1),
        ("finished", "1/2  LLM 2회(요청 실패 1)  임베딩 1회  실패 1  꼬리"),
        ("started", 2, 2, "나", None),
        ("finished", "끝"),
    ]
    assert rep.stages == [(1, 2, "가", 2), (2, 2, "나", None)] and rep.advanced_in("가") == 2


def test_stages_reject_wrong_order_and_abort_closes_open_stage() -> None:
    rep = ListReporter()
    stages = Stages(rep, ("가", "나"))
    with pytest.raises(RuntimeError, match="out of order"):
        stages.start("나")
    stages.start("가")
    with pytest.raises(RuntimeError, match="still open"):
        stages.start("나")
    stages.abort()
    stages.abort()  # 두 번 불러도 한 번만 닫는다
    assert rep.summaries == [ABORTED]
    stages.finish("이미 닫혔다")
    assert rep.summaries == [ABORTED]


def test_finish_includes_elapsed_time_by_default() -> None:
    rep = ListReporter()
    stages = Stages(rep, ("가",))
    stages.start("가")
    stages.finish("3/3", failed=0)
    assert re.fullmatch(r"3/3  \d+초  실패 0", rep.summaries[0])


# ---- 관계 집계: 손으로 만든 지식 그래프 ----


def hand_made_graph() -> KnowledgeGraph:
    """청크 5개와 문서 노드 1개. 유사도 선 2개, 개체명 겹침 선 3개, 종류를 모르는 선 1개. 청크 e는 선이 없다."""
    a, b, c, d, e = (Node(type=NodeType.CHUNK, properties={"page_content": name}) for name in "abcde")
    doc = Node(type=NodeType.DOCUMENT, properties={"page_content": "문서"})

    def rel(source: Node, target: Node, kind: str) -> Relationship:
        return Relationship(source=source, target=target, type=kind, bidirectional=True)

    relationships = [
        rel(a, b, "summary_similarity"),
        rel(b, c, "summary_similarity"),
        rel(a, b, "entities_overlap"),
        rel(a, c, "entities_overlap"),
        rel(c, d, "entities_overlap"),
        rel(a, d, "custom_link"),
    ]
    return KnowledgeGraph(nodes=[a, b, c, d, e, doc], relationships=relationships)


def test_relation_stats_match_the_graph() -> None:
    kg = hand_made_graph()
    by_type, isolated = relation_stats(kg)
    assert dict(by_type) == {"summary_similarity": 2, "entities_overlap": 3, "custom_link": 1}
    assert sum(by_type.values()) == len(kg.relationships)
    assert isolated == 1  # 청크 e. 선이 없는 문서 노드는 세지 않는다
    assert relation_summary(kg) == "유사도 2개, 개체명 겹침 3개, custom_link 1개, 선 없는 청크 1개"


def test_relation_stats_of_empty_graph() -> None:
    kg = KnowledgeGraph(nodes=[Node(type=NodeType.CHUNK, properties={"page_content": "x"})])
    assert relation_stats(kg) == ({}, 1)
    assert relation_summary(kg) == "유사도 0개, 개체명 겹침 0개, 선 없는 청크 1개"


# ---- ragas 생성기: 실제 ragas를 가짜 LLM으로 끝까지 돈다 ----


def ragas_generator(reporter, responder: RagasResponder | None = None, **options):
    chat, _ = fake_chat(responder or RagasResponder())
    embed, _ = fake_embed()
    settings = LLMSettings(llm=chat.endpoint, embed=Endpoint("http://emb.test/v1", "bge-test"), concurrency=2)
    report = GenerateReport("ragas")
    options.setdefault("adapt_prompts", False)
    return RagasGenerator(settings, report=report, chat=chat, embed=embed, reporter=reporter, **options), chat, embed, report


def llm_calls(summary: str) -> int:
    found = re.search(r"LLM (\d+)회", summary)
    return int(found.group(1)) if found else 0


def test_ragas_stages_arrive_in_order_with_names_and_totals() -> None:
    rep = ListReporter()
    gen, chat, embed, report = ragas_generator(rep)
    candidates = gen.generate(law_chunks(8), 6)
    assert len(candidates) == 6 and report.skipped == []

    assert [(index, total, name) for index, total, name, _ in rep.stages] == [(i + 1, 6, name) for i, name in enumerate(RAGAS_STAGES)]
    assert [total for *_, total in rep.stages] == [8, 24, None, None, None, 6]  # 요약 8, 추출 3종 x 8, 질문·정답 6
    kinds = [e[0] for e in rep.events if e[0] != "advanced"]
    assert kinds == ["started", "finished"] * 6  # 단계는 겹치지 않는다
    assert (rep.advanced_in("요약"), rep.advanced_in("임베딩·주제·개체명"), rep.advanced_in("질문·정답")) == (8, 24, 6)
    assert rep.advanced_in("관계") == 0 and rep.advanced_in("질문자") == 0 and rep.advanced_in("시나리오") == 0

    summary, extract, relate, personas, scenarios, samples = rep.summaries
    assert re.fullmatch(r"8/8  \d+초  LLM 8회  실패 0", summary)
    assert re.fullmatch(r"24/24  임베딩 8, 주제 8, 개체명 8  \d+초  LLM 16회  임베딩 8회  실패 0", extract)
    assert relate == "유사도 28개, 개체명 겹침 28개, 선 없는 청크 0개"  # 가짜 임베딩과 개체명이 모두 같아 8C2 = 28쌍
    assert personas == "3명: 형사 전문 변호사, 법학과 학생, 사법경찰관  LLM 3회"
    assert re.fullmatch(r"6개 \(단일 2, 넓은 주제 2, 특정 대상 2\)  \d+초  LLM \d+회", scenarios)
    assert re.fullmatch(r"6/6  \d+초  LLM 6회  실패 0  출처 못 찾음 0", samples)

    # 단계별 요청 수의 합이 전체 요청 수와 같다
    assert sum(llm_calls(s) for s in rep.summaries) == chat.log.requests
    assert embed.log.requests == 8


def test_ragas_stage_summaries_count_failures() -> None:
    rep = ListReporter()
    gen, chat, _, report = ragas_generator(rep, RagasResponder(fail_summary_containing="비밀본문003"))
    gen.generate(law_chunks(8), 6)
    summary, extract, relate, *_ = rep.summaries
    assert re.fullmatch(r"7/8  \d+초  LLM \d+회\(요청 실패 \d+\)  실패 1", summary)
    assert re.fullmatch(r"23/23  임베딩 7, 주제 8, 개체명 8  .*실패 0", extract)  # 요약이 없는 청크는 임베딩에서 빠진다
    assert relate == "유사도 21개, 개체명 겹침 28개, 선 없는 청크 0개"  # 7C2 = 21
    assert rep.stages[1][3] == 23
    assert sum(llm_calls(s) for s in rep.summaries) == chat.log.requests
    assert len(report.skipped) == 1 and report.skipped[0].startswith("transform SummaryExtractor")


def test_ragas_prompt_translation_is_counted_in_the_scenario_stage() -> None:
    rep = ListReporter()
    gen, chat, _, report = ragas_generator(rep, adapt_prompts=True)
    gen.generate(law_chunks(8), 6)  # 가짜 LLM은 번역 요청에 답하지 못한다. 실패는 리포트에 적히고 생성은 계속된다
    scenarios = rep.summaries[4]
    translated = int(re.search(r"\(프롬프트 번역 LLM (\d+)회 포함\)", scenarios).group(1))
    assert 0 < translated <= llm_calls(scenarios)
    assert sum(llm_calls(s) for s in rep.summaries) == chat.log.requests
    assert len(rep.summaries) == 6


def test_ragas_failure_closes_the_open_stage() -> None:
    class NoPersona(RagasResponder):
        def answer(self, title, fields, given, prompt):
            if fields == {"name", "role_description"}:
                raise RuntimeError("persona server down")
            return super().answer(title, fields, given, prompt)

    rep = ListReporter()
    gen, *_ = ragas_generator(rep, NoPersona())
    with pytest.raises(Exception, match="ragas: "):
        gen.generate(law_chunks(8), 6)
    assert [name for _, _, name, _ in rep.stages] == list(RAGAS_STAGES[:4])  # 질문자 단계에서 멈췄다
    assert len(rep.summaries) == 4 and rep.summaries[-1] == ABORTED  # 열린 채 남은 단계가 없다


def test_ragas_console_output_shows_stage_names_not_wrapper_names(capfd) -> None:
    out = io.StringIO()
    gen, *_ = ragas_generator(ConsoleReporter(stream=out))
    gen.generate(law_chunks(40), 6)
    screen = out.getvalue()
    stderr = capfd.readouterr().err
    for text in (screen, stderr):
        assert "GuardedTransform" not in text and "Guarded[" not in text
        assert "Applying" not in text and "Generating" not in text  # ragas 자체 막대는 꺼져 있다
    lines = screen.splitlines()
    finished = [line for line in lines if not re.search(r"\d+/\d+  \d+%$", line)]
    assert [line[:5] for line in finished] == [f"[{i}/6]" for i in range(1, 7)]
    assert [line.split("] ")[1].split("  ")[0].strip() for line in finished] == list(RAGAS_STAGES)
    for stage in ("[1/6]", "[2/6]"):  # 터미널이 아니면 단계마다 진행 줄은 많아야 9줄이다 (10% 단위)
        progress = [line for line in lines if line.startswith(stage) and re.search(r"\d+%$", line)]
        assert 1 <= len(progress) <= 9
    assert len(lines) < 40  # 청크 40개, 작업 160개를 돌려도 로그가 수백 줄이 되지 않는다


# ---- cli generate: 화면, 로그 파일 ----


def test_generate_prints_stages_above_report_and_writes_log_file(tmp_path: Path, capsys, monkeypatch) -> None:
    import golden_set.generation as generation
    from golden_set.cli import main
    from golden_set.domain.store import write_chunks

    monkeypatch.setenv("GOLDEN_LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("GOLDEN_LLM_MODEL", "qwen-test")
    monkeypatch.setenv("GOLDEN_LLM_API_KEY", "secret-key-123")
    monkeypatch.setenv("GOLDEN_EMBED_BASE_URL", "http://emb.test/v1")
    monkeypatch.setenv("GOLDEN_EMBED_MODEL", "bge-test")
    monkeypatch.setattr(generation, "get_generator", fake_ragas_factory())
    chunks, out, log = tmp_path / "chunks.jsonl", tmp_path / "candidates.jsonl", tmp_path / "generate.log"
    write_chunks(law_chunks(8), str(chunks))

    code = main(["generate", str(chunks), "--generator", "ragas", "--size", "6", "--out", str(out), "--no-adapt-prompts", "--log-file", str(log)])
    assert code == 0
    printed = capsys.readouterr().out
    lines = printed.splitlines()

    stage_lines = [line for line in lines if re.match(r"\[\d/6\] ", line) and not re.search(r"\d+%$", line)]
    assert len(stage_lines) == 6
    report_at = next(i for i, line in enumerate(lines) if line.startswith("generator=ragas"))
    assert all(lines.index(line) < report_at for line in stage_lines)  # 단계 요약은 마지막 리포트 위에 온다
    assert lines[report_at] == "generator=ragas  requested=6  produced=6  skipped=0"  # 기존 리포트는 그대로다
    assert lines[-1] == f"saved: {out}  (6 candidates, chunks=8)"

    # 단계별 LLM 요청 수의 합이 마지막 리포트의 requests와 같다
    requests = int(re.search(r"^llm    requests=(\d+)", printed, re.M).group(1))
    assert requests > 0 and sum(llm_calls(line) for line in stage_lines) == requests
    embed_requests = int(re.search(r"^embed  requests=(\d+)", printed, re.M).group(1))
    assert sum(int(n) for line in stage_lines for n in re.findall(r"임베딩 (\d+)회", line)) == embed_requests == 8

    # 로그 파일: 화면과 같은 단계 요약과 마지막 리포트. 진행 줄은 없다
    logged = log.read_text(encoding="utf-8")
    assert logged.splitlines() == stage_lines + lines[report_at:]
    for secret in ("비밀본문", "강호의 규율", "llm.test", "emb.test", "http://", "secret-key-123"):
        assert secret not in logged  # 본문, 서버 주소, 키는 쓰지 않는다


def test_generate_log_file_that_cannot_be_opened_is_an_error(tmp_path: Path, capsys, monkeypatch) -> None:
    from golden_set.cli import main
    from golden_set.domain.store import write_chunks

    monkeypatch.setenv("GOLDEN_LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("GOLDEN_LLM_MODEL", "qwen-test")
    chunks = tmp_path / "chunks.jsonl"
    write_chunks(law_chunks(2), str(chunks))
    code = main(["generate", str(chunks), "--generator", "deepeval", "--log-file", str(tmp_path / "no-such-dir" / "generate.log")])
    assert code == 2 and "error:" in capsys.readouterr().err
