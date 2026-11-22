"""DeepEval 생성기: 결과 변환은 실제 Golden 객체로, 실패 처리는 프롬프트를 읽고 답하는 가짜 LLM으로 검사한다. 서버는 쓰지 않는다."""

import json

import pytest
from conftest import choice, completion, fake_chat
from deepeval.dataset.golden import Golden
from langchain_core.documents import Document

from golden_set.candidates import Source
from golden_set.generators import GenerateReport, Generator
from golden_set.generators.base import extract_json
from golden_set.generators.deepeval_gen import (
    STYLING,
    ChatDeepEvalModel,
    DeepEvalGenerator,
    build_contexts,
    candidates_from_deepeval,
    choose_contexts,
)
from golden_set.llm import Endpoint, LLMError, LLMSettings

KO = ["첫 장문인 청운은 황하 기슭의 폐사에서 문파를 열었다.", "둘째 장문인 백리는 검을 뽑지 않았다.", "셋째 장문인 운하는 십 년 동안 산문을 닫았다.", "넷째 장문인 소천은 문규를 고쳤다."]


def chunk(text: str, i: int, source: str = "a.pdf") -> Document:
    return Document(page_content=text, metadata={"source": source, "file_type": "pdf", "loader": "pymupdf", "page": i + 1, "chunk_id": f"{source}:p{i + 1}:0:abcd", "chunk_index": 0})


CHUNKS = [chunk(t, i) for i, t in enumerate(KO)] + [chunk("Chapter one of file b.", 0, "b.pdf"), chunk("Chapter two of file b.", 1, "b.pdf")]


# ---- JSON 꺼내기 ----


@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('설명입니다.\n```json\n{"a": [1, 2]}\n```\n끝', {"a": [1, 2]}),
        ('앞말 {"a": "중괄호 } 포함"} 뒷말 {"b": 2}', {"a": "중괄호 } 포함"}),
        ('[{"x": 1}] 꼬리', [{"x": 1}]),
    ],
)
def test_extract_json(text, expected) -> None:
    assert extract_json(text) == expected


def test_extract_json_errors() -> None:
    with pytest.raises(ValueError, match="no json"):
        extract_json("JSON 아님")
    with pytest.raises(ValueError, match="invalid json"):
        extract_json('{"a": }')


# ---- context 구성 ----


def test_build_contexts_groups_neighbors_per_file() -> None:
    groups = build_contexts(CHUNKS, 3)
    assert [[c.metadata["chunk_id"] for c in g.chunks] for g in groups] == [
        ["a.pdf:p1:0:abcd", "a.pdf:p2:0:abcd", "a.pdf:p3:0:abcd"],
        ["a.pdf:p4:0:abcd"],
        ["b.pdf:p1:0:abcd", "b.pdf:p2:0:abcd"],
    ]
    assert [len(g.chunks) for g in build_contexts(CHUNKS, 1)] == [1] * 6
    assert [len(g.chunks) for g in build_contexts(CHUNKS, 2)] == [2, 2, 2]
    with pytest.raises(ValueError):
        build_contexts(CHUNKS, 4)


def test_choose_contexts_round_robin_and_scaling() -> None:
    groups = build_contexts(CHUNKS, 1)  # a: 4개, b: 2개
    chosen, per = choose_contexts(groups, size=4, max_goldens_per_context=2)
    assert per == 2 and [g.source for g in chosen] == ["a.pdf", "b.pdf"]  # 파일을 돌아가며 2개
    chosen, per = choose_contexts(groups, size=30, max_goldens_per_context=2)
    assert len(chosen) == 6 and per == 5  # context 6개로 30개를 만들려면 5개씩. 상한 5
    chosen, per = choose_contexts(groups, size=7, max_goldens_per_context=2)
    assert len(chosen) == 4 and per == 2 and [g.source for g in chosen] == ["a.pdf", "b.pdf", "a.pdf", "b.pdf"]
    assert choose_contexts([], 5) == ([], 2)


# ---- 변환 ----


def golden(question: str, answer: str | None, contexts: list[str], evolutions=("Reasoning",), source: str | None = "a.pdf") -> Golden:
    return Golden(input=question, expected_output=answer, context=contexts, source_file=source, additional_metadata={"evolutions": list(evolutions), "synthetic_input_quality": 0.8})


def test_fields_transferred_and_sources_exact() -> None:
    report = GenerateReport("deepeval")
    goldens = [golden("청운은 어디서 문파를 열었나?", "황하 기슭의 폐사에서.", KO[:2]), golden("Which chapter?", "Chapter one.", ["Chapter one of file b."], evolutions=())]
    a, b = candidates_from_deepeval(goldens, CHUNKS, "qwen-test", report)
    assert (a.id, a.question, a.reference_answer) == ("deepeval-0001", "청운은 어디서 문파를 열었나?", "황하 기슭의 폐사에서.")
    assert a.reference_contexts == KO[:2]
    assert a.sources == [Source("a.pdf:p1:0:abcd", "a.pdf", 1), Source("a.pdf:p2:0:abcd", "a.pdf", 2)]
    assert (a.question_type, a.language, a.generator, a.model) == ("Reasoning", "ko", "deepeval", "qwen-test")
    assert (b.id, b.question_type, b.language, b.sources[0].chunk_id) == ("deepeval-0002", "", "en", "b.pdf:p1:0:abcd")
    assert report.skipped == [] and report.notes == []


def test_missing_expected_output_is_skipped_and_unmatched_noted() -> None:
    report = GenerateReport("deepeval")
    cands = candidates_from_deepeval([golden("q?", None, KO[:1]), golden("q2?", "a.", ["모르는 본문"], evolutions=("Reasoning", "Multi-context"))], CHUNKS, "m", report)
    assert [c.id for c in cands] == ["deepeval-0001"] and cands[0].sources == [] and cands[0].question_type == "Reasoning+Multi-context"
    assert report.skipped == ["empty question or answer: 'q?'"] and report.notes == ["deepeval-0001: 1 context(s) not matched to a chunk"]


# ---- 모델 어댑터 ----


def test_model_returns_schema_instance_or_text() -> None:
    from deepeval.synthesizer.schema import InputFeedback, Response, SyntheticDataList

    chat, fake = fake_chat('<think>생각</think>{"data": [{"input": "질문 하나?"}, {"input": "질문 둘?"}]}', "자유 응답 본문")
    model = ChatDeepEvalModel(chat)
    assert isinstance(model, ChatDeepEvalModel) and model.get_model_name() == "qwen-test"
    out = model.generate("p", schema=SyntheticDataList)
    assert isinstance(out, SyntheticDataList) and [d.input for d in out.data] == ["질문 하나?", "질문 둘?"]
    assert fake.calls[0]["response_format"] == {"type": "json_object"}
    assert model.generate("p") == "자유 응답 본문" and "response_format" not in fake.calls[1]
    assert chat.log.think_stripped == 1
    # Response(response: str)는 deepeval이 자유 텍스트(진화, 기대 정답)를 받는 스키마다. JSON 모드를 끄고 본문을 그대로 담는다
    out = model.generate("p", schema=Response)
    assert isinstance(out, Response) and out.response == "자유 응답 본문" and "response_format" not in fake.calls[2]
    assert model.parse_failures == []
    with pytest.raises(LLMError):
        model.generate("p", schema=InputFeedback)  # 키가 둘인 스키마에 JSON이 아닌 답
    assert model.parse_failures and "InputFeedback" in model.parse_failures[0]
    assert not isinstance(LLMError("x"), TypeError)  # deepeval이 TypeError를 다른 뜻으로 쓴다


def test_text_field_detection() -> None:
    from deepeval.synthesizer.schema import InputFeedback, Response, RewrittenInput, SyntheticData, SyntheticDataList

    assert ChatDeepEvalModel.text_field(Response) == "response"
    assert ChatDeepEvalModel.text_field(RewrittenInput) == "rewritten_input"
    assert ChatDeepEvalModel.text_field(SyntheticData) is None  # input + used_source_files
    assert ChatDeepEvalModel.text_field(SyntheticDataList) is None and ChatDeepEvalModel.text_field(InputFeedback) is None


# ---- 실패 보호: 실제 Synthesizer를 가짜 LLM으로 돈다 ----


def responder(kwargs) -> object:
    """deepeval 프롬프트를 읽고 스키마에 맞는 답을 낸다. '실패' 가 든 context의 입력 생성에는 깨진 JSON을 돌려준다."""
    prompt = kwargs["messages"][0]["content"]
    if "'data' key" in prompt:
        if "실패" in prompt:
            return completion(choice("<think>흠</think> 이건 JSON이 아닙니다"))
        return completion(choice(json.dumps({"data": [{"input": "청운은 어디서 문파를 열었나?"}, {"input": "백리는 왜 검을 뽑지 않았나?"}]}, ensure_ascii=False)))
    if "'feedback' and 'score' keys" in prompt:
        return completion(choice('{"feedback": "좋다", "score": 0.9}'))
    if "'rewritten_input' key" in prompt:
        return completion(choice('{"rewritten_input": "다시 쓴 질문?"}'))
    if "'input' key only" in prompt:
        return completion(choice('{"input": "형식을 맞춘 질문?"}'))
    if "Generated Response:" in prompt:
        return completion(choice("<think>정답 생각</think>근거 본문에 따른 정답이다."))
    return completion(choice("진화한 질문?"))  # 진화 프롬프트는 자유 텍스트


def test_generate_skips_failed_context_and_reports() -> None:
    chat, fake = fake_chat(responder)
    settings = LLMSettings(llm=chat.endpoint, concurrency=2)
    report = GenerateReport("deepeval")
    chunks = [chunk(t, i) for i, t in enumerate(KO[:2])] + [chunk("이 청크는 실패해야 한다.", 0, "fail.pdf")]
    gen = DeepEvalGenerator(settings, report=report, chat=chat, context_chunks=2, language="ko")
    assert isinstance(gen, Generator)
    cands = gen.generate(chunks, size=4)

    assert len(cands) == 2  # context 2개 중 하나 실패 → 2개 후보
    assert all(c.generator == "deepeval" and c.language == "ko" and c.model == "qwen-test" for c in cands)
    assert all(c.reference_answer == "근거 본문에 따른 정답이다." for c in cands)
    assert all([s.chunk_id for s in c.sources] == ["a.pdf:p1:0:abcd", "a.pdf:p2:0:abcd"] for c in cands)
    assert all(c.question_type for c in cands)  # 진화 이름이 붙는다
    assert cands[0].question == "형식을 맞춘 질문?"  # input_format 지정으로 마지막에 형식 맞춤 재작성이 돈다

    assert len(report.skipped) == 1 and report.skipped[0].startswith("context #1 (fail.pdf): LLMError")
    assert report.produced == 2 and report.requested == 4
    assert any("json parse failures: 1" in n for n in report.notes)
    assert chat.log.requests > 5 and len(chat.log.failures) == 1 and chat.log.think_stripped >= 3
    first_prompt = fake.calls[0]["messages"][0]["content"]
    assert "Korean" in first_prompt  # StylingConfig의 input_format이 프롬프트에 들어간다
    assert all(kw["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}} for kw in fake.calls)


def test_generator_errors_without_chunks_and_language_styling() -> None:
    settings = LLMSettings(llm=Endpoint("http://llm.test/v1", "qwen"))
    gen = DeepEvalGenerator(settings)
    with pytest.raises(Exception, match="no chunks"):
        gen.generate([], 3)
    assert "Korean" in STYLING["ko"].input_format and "English" in STYLING["en"].expected_output_format
