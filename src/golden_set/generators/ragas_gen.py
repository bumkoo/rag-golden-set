"""Ragas 생성기. TestsetGenerator에 우리 LLM·임베딩을 넣고 청크 Document를 그대로 넘긴다.

확인한 버전: ragas 0.4.4 (NOTES.md 참고). 이 모듈은 ragas가 설치되어 있을 때만 import된다.
"""

import asyncio
import os
import re
from dataclasses import dataclass

os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")  # 사용 통계(t.explodinggradients.com) 전송을 끈다. import 전에 있어야 한다

from langchain_core.documents import Document
from langchain_core.outputs import Generation, LLMResult
from langchain_core.prompt_values import PromptValue
from ragas.dataset_schema import SingleTurnSample
from ragas.embeddings.base import BaseRagasEmbedding
from ragas.llms.base import BaseRagasLLM
from ragas.run_config import RunConfig
from ragas.testset import TestsetGenerator
from ragas.testset.graph import KnowledgeGraph, Node, NodeType
from ragas.testset.synthesizers import default_query_distribution
from ragas.testset.transforms import Parallel, apply_transforms
from ragas.testset.transforms.base import BaseGraphTransformation
from ragas.testset.transforms.extractors import EmbeddingExtractor
from ragas.testset.transforms.extractors.llm_based import NERExtractor, SummaryExtractor, ThemesExtractor
from ragas.testset.transforms.relationship_builders import CosineSimilarityBuilder, OverlapScoreBuilder

from golden_set.candidates import GoldenCandidate, make_id
from golden_set.generators.base import ChunkIndex, GenerateError, GenerateReport, detect_language, sources_for
from golden_set.llm import ChatClient, EmbedClient, LLMSettings

# 질문 생성 프롬프트의 llm_context 로 들어간다 (QueryCondition.llm_context). 언어를 근거 본문과 맞추는 지시다.
LANGUAGE_INSTRUCTION = {
    "ko": "Write the query and the answer in Korean (한국어), the same language as the context. Do not translate names or terms.",
    "en": "Write the query and the answer in English, the same language as the context.",
}
ADAPT_LANGUAGE = {"ko": "korean", "en": "english"}
_HOP_PREFIX = re.compile(r"^<\d+-hop>\s*")  # 멀티홉 근거 본문 앞에 ragas가 붙이는 표시

FAILED_SAMPLE_STYLE = "FAILED"  # 생성에 실패한 자리에 넣는 빈 샘플의 표시


# ---- ragas 쪽 어댑터 ----


class ChatRagasLLM(BaseRagasLLM):
    """ragas의 BaseRagasLLM을 ChatClient로 구현한다. 응답은 LLMResult로 돌려준다."""

    def __init__(self, client: ChatClient, run_config: RunConfig | None = None):
        super().__init__()
        self.client = client
        if run_config is not None:
            self.set_run_config(run_config)

    @staticmethod
    def _result(completions) -> LLMResult:
        return LLMResult(generations=[[Generation(text=c.text, generation_info={"finish_reason": c.finish_reason}) for c in completions]])

    def generate_text(self, prompt: PromptValue, n: int = 1, temperature: float = 0.01, stop=None, callbacks=None) -> LLMResult:
        return self._result(self.client.complete(prompt.to_messages(), json=True, temperature=temperature, n=n))

    async def agenerate_text(self, prompt: PromptValue, n: int = 1, temperature: float | None = 0.01, stop=None, callbacks=None) -> LLMResult:
        return self._result(await self.client.acomplete(prompt.to_messages(), json=True, temperature=temperature, n=n))

    def is_finished(self, response: LLMResult) -> bool:
        """max_tokens에 잘린 응답(finish_reason=length)은 끝나지 않은 것으로 본다."""
        for gens in response.generations:
            for g in gens:
                if (g.generation_info or {}).get("finish_reason") == "length":
                    return False
        return True


class ChatRagasEmbedding(BaseRagasEmbedding):
    """ragas의 BaseRagasEmbedding을 EmbedClient로 구현한다."""

    is_async = True  # EmbeddingExtractor가 이 속성을 보고 aembed_text를 쓴다

    def __init__(self, client: EmbedClient):
        super().__init__()
        self.client = client

    def embed_text(self, text: str, **kwargs) -> list[float]:
        return self.client.embed([text])[0]

    async def aembed_text(self, text: str, **kwargs) -> list[float]:
        return (await self.client.aembed([text]))[0]


class GuardedTransform(BaseGraphTransformation):
    """변환 하나를 감싼다. 노드 하나의 추출이 실패해도 전체를 멈추지 않고 리포트에 적는다.

    실패한 노드는 그 속성이 비어 다음 단계에서 자연히 빠진다 (관계 빌더의 filter_nodes 참고).
    """

    def __init__(self, inner, report: GenerateReport):
        self.inner = inner
        self.report = report
        self.name = f"Guarded[{inner.__class__.__name__}]"
        self.filter_nodes = getattr(inner, "filter_nodes", lambda node: True)

    async def transform(self, kg: KnowledgeGraph):
        return await self.inner.transform(kg)

    def generate_execution_plan(self, kg: KnowledgeGraph):
        return [self._guard(coro) for coro in self.inner.generate_execution_plan(kg)]

    async def _guard(self, coro):
        try:
            return await coro
        except Exception as e:
            self.report.skip(f"transform {self.inner.__class__.__name__}: {type(e).__name__}: {e}")
            return None


class GuardedSynthesizer:
    """질문 합성기를 감싼다. 샘플 하나가 실패하면 빈 샘플을 돌려주고 사유를 리포트에 적는다."""

    def __init__(self, inner, report: GenerateReport):
        self.inner = inner
        self.report = report

    @property
    def name(self) -> str:
        return self.inner.name

    async def generate_scenarios(self, n: int, knowledge_graph, persona_list, callbacks=None):
        try:
            return await self.inner.generate_scenarios(n=n, knowledge_graph=knowledge_graph, persona_list=persona_list, callbacks=callbacks)
        except Exception as e:
            self.report.skip(f"{self.inner.name} scenarios (n={n}): {type(e).__name__}: {e}")
            return []

    async def generate_sample(self, scenario, callbacks=None) -> SingleTurnSample:
        try:
            return await self.inner.generate_sample(scenario=scenario, callbacks=callbacks)
        except Exception as e:
            self.report.skip(f"{self.inner.name} sample: {type(e).__name__}: {e}")
            return SingleTurnSample(user_input="", reference="", reference_contexts=[], query_style=FAILED_SAMPLE_STYLE)


def _chunk_with(prop: str):
    def ok(node: Node) -> bool:
        return node.type == NodeType.CHUNK and node.get_property(prop) is not None

    return ok


def build_transforms(llm: BaseRagasLLM, embedding: BaseRagasEmbedding, report: GenerateReport) -> list:
    """ragas의 default_transforms_for_prechunked와 같은 구성에 실패 보호를 더한 것.

    차이: 각 변환을 GuardedTransform으로 감싸고, 뒷단계는 앞단계 속성이 있는 노드만 본다.
    CustomNodeFilter는 미리 나눈 청크에는 부모 요약이 없어 아무것도 하지 않으므로(ragas 0.4.4 filters.py) 뺐다.
    """
    chunk = _chunk_with("page_content")
    return [
        GuardedTransform(SummaryExtractor(llm=llm, filter_nodes=chunk), report),
        GuardedTransform(
            Parallel(
                EmbeddingExtractor(embedding_model=embedding, property_name="summary_embedding", embed_property_name="summary", filter_nodes=_chunk_with("summary")),
                ThemesExtractor(llm=llm, filter_nodes=chunk),
                NERExtractor(llm=llm, filter_nodes=chunk),
            ),
            report,
        ),
        GuardedTransform(
            Parallel(
                CosineSimilarityBuilder(property_name="summary_embedding", new_property_name="summary_similarity", threshold=0.7, filter_nodes=_chunk_with("summary_embedding")),
                OverlapScoreBuilder(threshold=0.01, filter_nodes=_chunk_with("entities")),
            ),
            report,
        ),
    ]


# ---- 결과 변환 ----


def strip_hop_prefix(context: str) -> str:
    return _HOP_PREFIX.sub("", context, count=1)


def candidates_from_ragas(samples, chunks: list[Document], model: str, report: GenerateReport | None = None) -> list[GoldenCandidate]:
    """ragas TestsetSample 목록을 GoldenCandidate로 옮긴다. 근거 본문은 청크와 대조해 sources를 채운다.

    질문이나 정답이 빈 샘플은 건너뛰고 리포트에 적는다. 출처를 못 찾은 샘플은 sources를 비워 두고 검증에 맡긴다.
    """
    report = report or GenerateReport("ragas")
    index = ChunkIndex(chunks)
    out: list[GoldenCandidate] = []
    for sample in samples:
        eval_sample = getattr(sample, "eval_sample", sample)
        if getattr(eval_sample, "query_style", None) == FAILED_SAMPLE_STYLE:
            continue  # 실패 사유는 GuardedSynthesizer가 이미 적었다
        question = (getattr(eval_sample, "user_input", None) or "").strip()
        answer = (getattr(eval_sample, "reference", None) or "").strip()
        contexts = [strip_hop_prefix(c) for c in (getattr(eval_sample, "reference_contexts", None) or []) if c]
        if not question or not answer:
            report.skip(f"empty question or answer: {question[:60]!r}")
            continue
        sources, missing = sources_for(contexts, index)
        if missing:
            report.notes.append(f"{make_id('ragas', len(out) + 1)}: {missing} context(s) not matched to a chunk")
        out.append(
            GoldenCandidate(
                id=make_id("ragas", len(out) + 1),
                question=question,
                reference_answer=answer,
                reference_contexts=contexts,
                sources=sources,
                question_type=str(getattr(sample, "synthesizer_name", "") or ""),
                language=detect_language(question),
                generator="ragas",
                model=model,
            )
        )
    return out


# ---- 생성기 ----


@dataclass
class RagasOptions:
    language: str = "auto"  # "auto" | "ko" | "en"
    adapt_prompts: bool = True  # ko일 때 ragas의 adapt_prompts로 질문 생성 프롬프트의 예시를 번역한다 (LLM 호출)
    num_personas: int = 3


class RagasGenerator:
    """Generator 프로토콜 구현."""

    name = "ragas"

    def __init__(self, settings: LLMSettings, report: GenerateReport | None = None, chat: ChatClient | None = None, embed: EmbedClient | None = None, **options):
        if settings.embed is None and embed is None:
            raise GenerateError("ragas needs an embedding model: set GOLDEN_EMBED_BASE_URL / GOLDEN_EMBED_MODEL")
        self.settings = settings
        self.options = RagasOptions(**options)
        self.report = report or GenerateReport(self.name)
        self.chat = chat or ChatClient(settings.llm, settings, log=self.report.llm)
        self.embed_client = embed or EmbedClient(settings.embed, settings, log=self.report.embed)
        self.run_config = RunConfig(timeout=int(settings.timeout), max_retries=3, max_wait=10, max_workers=settings.concurrency)
        self.llm = ChatRagasLLM(self.chat, self.run_config)
        self.embedding = ChatRagasEmbedding(self.embed_client)

    def _adapt_prompts(self, distribution, language: str) -> None:
        """합성기들의 프롬프트 예시를 문서 언어로 번역한다. 실패하면 영어 예시 그대로 두고 리포트에 적는다."""

        async def adapt_all():
            for synth, _ in distribution:
                adapted = await synth.adapt_prompts(ADAPT_LANGUAGE[language], llm=self.llm)
                synth.set_prompts(**adapted)

        try:
            asyncio.run(adapt_all())
            self.report.notes.append(f"adapt_prompts({ADAPT_LANGUAGE[language]}) applied to {len(distribution)} synthesizer(s)")
        except Exception as e:
            self.report.skip(f"adapt_prompts: {type(e).__name__}: {e}")

    def generate(self, chunks: list[Document], size: int) -> list[GoldenCandidate]:
        docs = [c for c in chunks if c.page_content.strip()]
        if not docs:
            raise GenerateError("no chunks")
        self.report.requested = size
        language = self.options.language if self.options.language != "auto" else detect_language(" ".join(c.page_content for c in docs))
        llm_context = LANGUAGE_INSTRUCTION[language]
        self.report.notes.append(f"language={language}  llm_context={llm_context!r}")

        kg = KnowledgeGraph(nodes=[Node(type=NodeType.CHUNK, properties={"page_content": c.page_content, "document_metadata": dict(c.metadata)}) for c in docs])
        apply_transforms(kg, build_transforms(self.llm, self.embedding, self.report), run_config=self.run_config)

        try:
            distribution = default_query_distribution(self.llm, kg, llm_context)
        except ValueError as e:  # 쓸 수 있는 합성기가 하나도 없다 (추출이 전부 실패했거나 청크가 너무 적다)
            raise GenerateError(f"ragas: {e}") from e
        self.report.notes.append("synthesizers: " + ", ".join(s.name for s, _ in distribution))
        if language == "ko" and self.options.adapt_prompts:
            self._adapt_prompts(distribution, language)

        generator = TestsetGenerator(llm=self.llm, embedding_model=self.embedding, knowledge_graph=kg, llm_context=llm_context)
        guarded = [(GuardedSynthesizer(s, self.report), p) for s, p in distribution]
        try:
            testset = generator.generate(testset_size=size, query_distribution=guarded, num_personas=self.options.num_personas, run_config=self.run_config, raise_exceptions=True)
        except Exception as e:
            raise GenerateError(f"ragas: {type(e).__name__}: {e}") from e
        candidates = candidates_from_ragas(testset.samples, docs, self.chat.model, self.report)[:size]
        self.report.produced = len(candidates)
        return candidates
