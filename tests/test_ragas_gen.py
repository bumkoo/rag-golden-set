"""Ragas 생성기: 결과 변환은 실제 ragas 데이터 객체로, 실패 처리는 가짜 LLM으로 검사한다. 서버는 쓰지 않는다."""

import asyncio

import pytest
from conftest import fake_chat, fake_embed
from ragas.dataset_schema import SingleTurnSample
from ragas.run_config import RunConfig
from ragas.testset.graph import KnowledgeGraph, Node, NodeType
from ragas.testset.persona import Persona
from ragas.testset.synthesizers.testset_schema import TestsetSample as RagasTestsetSample  # 이름에 Test가 있어 pytest가 수집하려 든다

from golden_set.domain.candidate import Source
from golden_set.domain.chunk import Chunk
from golden_set.generation import GenerateReport
from golden_set.generation.llm import Endpoint, LLMSettings
from golden_set.generation.ragas.adapters import ChatRagasEmbedding, ChatRagasLLM
from golden_set.generation.ragas.generator import RagasGenerator, candidates_from_ragas, strip_hop_prefix
from golden_set.generation.ragas.guards import FAILED_SAMPLE_STYLE, GuardedSynthesizer, GuardedTransform
from golden_set.generation.ragas.transforms import build_transforms

KO = "강호의 규율은 무공이 아니라 신의에서 나온다고 장문인은 말했다. 제자는 그 뜻을 오래도록 헤아리지 못했다."
EN = "The master never drew the sword, and the pupil did not understand why for many years."


def chunk(text: str, cid: str, page: int = 1, source: str = "dir/a.pdf") -> Chunk:
    return Chunk.from_metadata(text, {"source": source, "file_type": "pdf", "loader": "pymupdf", "page": page, "chunk_id": cid, "chunk_index": 0})


CHUNKS = [chunk(KO, "a.pdf:p1:0:aaaa", 1), chunk(EN, "a.pdf:p2:0:aaaa", 2)]


def sample(question: str, answer: str, contexts: list[str], name: str = "single_hop_specific_query_synthesizer", **extra) -> RagasTestsetSample:
    return RagasTestsetSample(eval_sample=SingleTurnSample(user_input=question, reference=answer, reference_contexts=contexts, **extra), synthesizer_name=name)


# ---- 변환 ----


def test_fields_are_transferred_and_sources_matched() -> None:
    samples = [
        sample("규율의 근원은 무엇인가?", "신의다.", [KO]),
        sample("Why did the pupil not understand?", "The text does not say.", [f"<1-hop>\n\n{KO}", f"<2-hop>\n\n{EN}"], "multi_hop_abstract_query_synthesizer"),
    ]
    report = GenerateReport("ragas")
    cands = candidates_from_ragas(samples, CHUNKS, "qwen-test", report)
    assert [c.id for c in cands] == ["ragas-0001", "ragas-0002"]
    a, b = cands
    assert (a.question, a.reference_answer, a.reference_contexts) == ("규율의 근원은 무엇인가?", "신의다.", [KO])
    assert a.sources == [Source("a.pdf:p1:0:aaaa", "dir/a.pdf", 1)]
    assert (a.question_type, a.language, a.generator, a.model) == ("single_hop_specific_query_synthesizer", "ko", "ragas", "qwen-test")
    assert a.created_at
    assert b.reference_contexts == [KO, EN]  # <n-hop> 표시는 뗀다
    assert [s.chunk_id for s in b.sources] == ["a.pdf:p1:0:aaaa", "a.pdf:p2:0:aaaa"]
    assert (b.question_type, b.language) == ("multi_hop_abstract_query_synthesizer", "en")
    assert report.skipped == [] and report.notes == []


def test_unmatched_context_leaves_sources_empty_and_notes_it() -> None:
    report = GenerateReport("ragas")
    (c,) = candidates_from_ragas([sample("질문?", "답.", ["청크에 없는 본문"])], CHUNKS, "m", report)
    assert c.sources == [] and c.reference_contexts == ["청크에 없는 본문"]
    assert report.notes == ["ragas-0001: 1 context(s) not matched to a chunk"]


def test_whitespace_only_difference_still_matches() -> None:
    (c,) = candidates_from_ragas([sample("q?", "a.", [KO.replace(" ", "  ")])], CHUNKS, "m")
    assert c.sources[0].chunk_id == "a.pdf:p1:0:aaaa"


def test_empty_and_failed_samples_are_skipped() -> None:
    report = GenerateReport("ragas")
    samples = [
        sample("", "답.", [KO]),
        sample("질문?", "", [KO]),
        sample("", "", [], query_style=FAILED_SAMPLE_STYLE),  # GuardedSynthesizer가 넣은 자리. 사유는 이미 적혀 있다
        sample("정상?", "정상.", [KO]),
    ]
    cands = candidates_from_ragas(samples, CHUNKS, "m", report)
    assert [c.question for c in cands] == ["정상?"] and cands[0].id == "ragas-0001"
    assert len(report.skipped) == 2 and all(r.startswith("empty question or answer") for r in report.skipped)


def test_strip_hop_prefix() -> None:
    assert strip_hop_prefix("<12-hop>\n\n본문") == "본문" and strip_hop_prefix("본문 <1-hop>") == "본문 <1-hop>"


# ---- ChatRagasLLM: 실제 ragas 프롬프트 + 가짜 LLM ----


def ragas_llm(*texts):
    chat, fake = fake_chat(*texts)
    return ChatRagasLLM(chat, RunConfig(max_retries=2, max_wait=0, max_workers=1)), chat, fake


def run_query_prompt(llm):
    from ragas.testset.synthesizers.single_hop.prompts import QueryAnswerGenerationPrompt, QueryCondition

    data = QueryCondition(persona=Persona(name="독자", role_description="무협지를 즐겨 읽는다"), term="신의", query_style="Formal", query_length="Short", context=KO, llm_context="Write in Korean.")
    return asyncio.run(QueryAnswerGenerationPrompt().generate(llm=llm, data=data))


def test_well_formed_json_is_parsed_by_ragas_prompt() -> None:
    llm, chat, fake = ragas_llm('{"query": "규율의 근원은?", "answer": "신의다."}')
    out = run_query_prompt(llm)
    assert (out.query, out.answer) == ("규율의 근원은?", "신의다.")
    assert chat.log.requests == 1 and chat.log.successes == 1
    assert fake.calls[0]["response_format"] == {"type": "json_object"}
    assert "Write in Korean." in fake.calls[0]["messages"][0]["content"]  # llm_context가 프롬프트에 들어간다


def test_think_tags_are_stripped_before_ragas_parses() -> None:
    llm, chat, _ = ragas_llm('<think>{"draft": [1]} 생각 중</think>\n{"query": "q?", "answer": "a."}')
    out = run_query_prompt(llm)
    assert (out.query, out.answer) == ("q?", "a.") and chat.log.think_stripped == 1


def test_broken_json_is_retried_by_ragas_then_raised_not_hung() -> None:
    from ragas.exceptions import RagasOutputParserException

    llm, chat, _ = ragas_llm("이건 JSON이 아니다")  # 고쳐 달라는 재요청에도 같은 답
    with pytest.raises(RagasOutputParserException):
        run_query_prompt(llm)
    assert chat.log.requests >= 2 and chat.log.successes == chat.log.requests  # 응답은 왔으나 ragas가 파싱에 실패


def test_empty_response_is_retried_then_raised() -> None:
    from golden_set.generation.llm import LLMError

    llm, chat, _ = ragas_llm("<think>추론만")
    with pytest.raises(LLMError):
        run_query_prompt(llm)
    assert chat.log.requests == 2 and len(chat.log.failures) == 2  # RunConfig(max_retries=2)


def test_truncated_response_is_not_finished() -> None:
    from langchain_core.outputs import Generation, LLMResult

    llm, _, _ = ragas_llm("x")
    assert llm.is_finished(LLMResult(generations=[[Generation(text="a", generation_info={"finish_reason": "stop"})]]))
    assert not llm.is_finished(LLMResult(generations=[[Generation(text="a", generation_info={"finish_reason": "length"})]]))


def test_embedding_adapter() -> None:
    embed, fake = fake_embed(dim=3)
    e = ChatRagasEmbedding(embed)
    assert e.is_async and e.embed_text("가") == [1.0, 0.0, 0.0]
    assert asyncio.run(e.aembed_text("나")) == [1.0, 0.0, 0.0]
    assert fake.calls[1] == {"model": "bge-test", "input": ["나"]}


# ---- 실패 보호: 변환 ----


def test_guarded_transform_skips_failing_node_and_reports() -> None:
    from ragas.testset.transforms import apply_transforms
    from ragas.testset.transforms.base import Extractor

    class FlakyExtractor(Extractor):
        async def extract(self, node):
            if "실패" in node.properties["page_content"]:
                raise ValueError("bad json")
            return "summary", "요약"

    kg = KnowledgeGraph(nodes=[Node(type=NodeType.CHUNK, properties={"page_content": t}) for t in ["정상", "실패하는 청크", "정상 2"]])
    report = GenerateReport("ragas")
    apply_transforms(kg, [GuardedTransform(FlakyExtractor(), report)], run_config=RunConfig(max_workers=2))
    assert [n.get_property("summary") for n in kg.nodes] == ["요약", None, "요약"]
    assert report.skipped == ["transform FlakyExtractor: ValueError: bad json"]


def test_build_transforms_has_three_guarded_stages() -> None:
    chat, _ = fake_chat("x")
    embed, _ = fake_embed()
    stages = build_transforms(ChatRagasLLM(chat), ChatRagasEmbedding(embed), GenerateReport("ragas"))
    assert len(stages) == 3 and all(isinstance(s, GuardedTransform) for s in stages)
    node_ok = Node(type=NodeType.CHUNK, properties={"page_content": "x", "summary": "s", "summary_embedding": [1.0], "entities": ["a"]})
    node_bare = Node(type=NodeType.CHUNK, properties={"page_content": "x"})
    for builder in stages[2].inner.transformations:  # 관계 빌더는 앞단계 속성이 있는 노드만 본다
        assert builder.filter_nodes(node_ok) and not builder.filter_nodes(node_bare)


# ---- 실패 보호: 합성기 (실제 TestsetGenerator.generate 를 LLM 없이 돈다) ----


class FakeSynthesizer:
    """ragas 합성기와 같은 겉모습. 시나리오 n개를 만들고, '실패' 표시가 있는 샘플에서 예외를 낸다."""

    def __init__(self, name: str, fail_scenarios: bool = False, fail_every: int = 0):
        self.name = name
        self.fail_scenarios = fail_scenarios
        self.fail_every = fail_every

    async def generate_scenarios(self, n, knowledge_graph, persona_list, callbacks=None):
        if self.fail_scenarios:
            raise RuntimeError("No clusters found in the knowledge graph")
        return [{"i": i, "fail": self.fail_every and (i + 1) % self.fail_every == 0} for i in range(n)]

    async def generate_sample(self, scenario, callbacks=None):
        if scenario["fail"]:
            raise ValueError("broken json")
        return SingleTurnSample(user_input=f"{self.name} 질문 {scenario['i']}?", reference="답.", reference_contexts=[KO])


def test_generate_continues_past_failed_samples_and_reports_them() -> None:
    from ragas.testset import TestsetGenerator

    report = GenerateReport("ragas")
    chat, _ = fake_chat("x")
    embed, _ = fake_embed()
    kg = KnowledgeGraph(nodes=[Node(type=NodeType.CHUNK, properties={"page_content": KO})])
    gen = TestsetGenerator(llm=ChatRagasLLM(chat), embedding_model=ChatRagasEmbedding(embed), knowledge_graph=kg, persona_list=[Persona(name="독자", role_description="r")])
    distribution = [
        (GuardedSynthesizer(FakeSynthesizer("single", fail_every=2), report), 0.5),
        (GuardedSynthesizer(FakeSynthesizer("multi", fail_scenarios=True), report), 0.5),
    ]
    testset = gen.generate(testset_size=6, query_distribution=distribution, run_config=RunConfig(max_workers=2), raise_exceptions=True)
    cands = candidates_from_ragas(testset.samples, CHUNKS, "qwen-test", report)
    assert [c.question for c in cands] == ["single 질문 0?", "single 질문 2?"]  # 3개 중 2번째가 실패
    assert all(c.question_type == "single" and c.sources[0].chunk_id == "a.pdf:p1:0:aaaa" for c in cands)
    assert sorted(report.skipped) == ["multi scenarios (n=3): RuntimeError: No clusters found in the knowledge graph", "single sample: ValueError: broken json"]
    assert chat.log.requests == 0  # LLM은 부르지 않았다


def test_generator_options_and_language_instruction() -> None:
    from golden_set.generation.ragas.generator import LANGUAGE_INSTRUCTION, RagasOptions

    settings = LLMSettings(llm=Endpoint("http://llm.test/v1", "qwen"), embed=Endpoint("http://emb.test/v1", "bge"), concurrency=3, timeout=30)
    g = RagasGenerator(settings, language="ko", adapt_prompts=False)
    assert g.options == RagasOptions(language="ko", adapt_prompts=False)
    assert (g.run_config.max_workers, g.run_config.timeout, g.run_config.max_retries) == (3, 30, 3)
    assert "Korean" in LANGUAGE_INSTRUCTION["ko"] and "English" in LANGUAGE_INSTRUCTION["en"]
    with pytest.raises(Exception, match="no chunks"):
        g.generate([], 5)
