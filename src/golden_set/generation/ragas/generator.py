"""Ragas 생성기. TestsetGenerator에 우리 LLM·임베딩을 넣고 청크 Document를 그대로 넘긴다."""

import asyncio
import re
from dataclasses import dataclass

from langchain_core.documents import Document
from ragas.run_config import RunConfig
from ragas.testset import TestsetGenerator
from ragas.testset.graph import KnowledgeGraph, Node, NodeType
from ragas.testset.persona import generate_personas_from_kg
from ragas.testset.synthesizers import default_query_distribution
from ragas.testset.transforms import apply_transforms

from golden_set.domain.candidate import GoldenCandidate, make_id
from golden_set.domain.language import detect_language
from golden_set.generation.generator import GenerateError, GenerateReport
from golden_set.generation.llm.client import ChatClient, EmbedClient
from golden_set.generation.llm.settings import LLMSettings
from golden_set.generation.matching import ChunkIndex, sources_for
from golden_set.generation.progress import RAGAS_STAGES, ConsoleReporter, ProgressReporter, Stages
from golden_set.generation.ragas.adapters import ChatRagasEmbedding, ChatRagasLLM
from golden_set.generation.ragas.guards import FAILED_SAMPLE_STYLE, GuardedSynthesizer
from golden_set.generation.ragas.stages import TRANSFORM_LABELS, SampleStages, kinds_summary, quiet_ragas_bars, relation_summary
from golden_set.generation.ragas.transforms import build_transforms

# 질문 생성 프롬프트의 llm_context 로 들어간다 (QueryCondition.llm_context). 언어를 근거 본문과 맞추는 지시다.
LANGUAGE_INSTRUCTION = {
    "ko": "Write the query and the answer in Korean (한국어), the same language as the context. Do not translate names or terms.",
    "en": "Write the query and the answer in English, the same language as the context.",
}
ADAPT_LANGUAGE = {"ko": "korean", "en": "english"}
_HOP_PREFIX = re.compile(r"^<\d+-hop>\s*")  # 멀티홉 근거 본문 앞에 ragas가 붙이는 표시


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
            report.unmatched += 1
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

    def __init__(self, settings: LLMSettings, report: GenerateReport | None = None, chat: ChatClient | None = None, embed: EmbedClient | None = None, reporter: ProgressReporter | None = None, **options):
        if settings.embed is None and embed is None:
            raise GenerateError("ragas needs an embedding model: set GOLDEN_EMBED_BASE_URL / GOLDEN_EMBED_MODEL")
        self.settings = settings
        self.options = RagasOptions(**options)
        self.report = report or GenerateReport(self.name)
        self.reporter = reporter or ConsoleReporter()
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
        # 요청 수는 클라이언트의 집계에서 읽는다 (밖에서 넣은 클라이언트면 리포트의 집계와 다른 객체일 수 있다)
        stages = Stages(self.reporter, RAGAS_STAGES, llm=self.chat.log, embed=self.embed_client.log, skipped=self.report.skipped)
        try:
            return self._generate(docs, size, stages)
        finally:
            stages.abort()  # 예외로 나갈 때 열려 있는 단계를 닫는다

    def _run_transform(self, kg: KnowledgeGraph, transform, stages: Stages, name: str, counted: bool) -> None:
        """변환 하나를 단계 하나로 돌린다. counted가 아니면 진행 칸을 세지 않는다 (관계 단계)."""
        transform.on_plan = lambda n: stages.start(name, n if counted else None)
        transform.on_step = stages.advance if counted else None
        with quiet_ragas_bars():
            apply_transforms(kg, transform, run_config=self.run_config)

    def _generate(self, docs: list[Document], size: int, stages: Stages) -> list[GoldenCandidate]:
        language = self.options.language if self.options.language != "auto" else detect_language(" ".join(c.page_content for c in docs))
        llm_context = LANGUAGE_INSTRUCTION[language]
        self.report.notes.append(f"language={language}  llm_context={llm_context!r}")

        kg = KnowledgeGraph(nodes=[Node(type=NodeType.CHUNK, properties={"page_content": c.page_content, "document_metadata": dict(c.metadata)}) for c in docs])
        summary, extract, relate = build_transforms(self.llm, self.embedding, self.report)

        self._run_transform(kg, summary, stages, RAGAS_STAGES[0], counted=True)
        done, failed = sum(summary.done.values()), sum(summary.failed.values())
        stages.finish(f"{done}/{done + failed}", failed=failed)

        self._run_transform(kg, extract, stages, RAGAS_STAGES[1], counted=True)
        done, failed = sum(extract.done.values()), sum(extract.failed.values())
        stages.finish(f"{done}/{done + failed}  {kinds_summary(extract.done, TRANSFORM_LABELS)}".rstrip(), failed=failed)

        self._run_transform(kg, relate, stages, RAGAS_STAGES[2], counted=False)
        failed = sum(relate.failed.values())
        stages.finish(relation_summary(kg), timed=False, failed=failed or None)

        try:
            distribution = default_query_distribution(self.llm, kg, llm_context)
        except ValueError as e:  # 쓸 수 있는 합성기가 하나도 없다 (추출이 전부 실패했거나 청크가 너무 적다)
            raise GenerateError(f"ragas: {e}") from e
        self.report.notes.append("synthesizers: " + ", ".join(s.name for s, _ in distribution))

        stages.start(RAGAS_STAGES[3])
        try:
            with quiet_ragas_bars():
                personas = generate_personas_from_kg(llm=self.llm, kg=kg, num_personas=self.options.num_personas)
        except Exception as e:
            raise GenerateError(f"ragas: {type(e).__name__}: {e}") from e
        stages.finish(f"{len(personas)}명: " + ", ".join(p.name for p in personas), timed=False)

        # 시나리오 단계는 프롬프트 번역(adapt_prompts)부터다. 번역에 쓴 요청 수는 요약 줄에 따로 적는다.
        stages.start(RAGAS_STAGES[4])
        translated = 0
        if language == "ko" and self.options.adapt_prompts:
            self._adapt_prompts(distribution, language)
            translated = stages.llm_requests
        events = SampleStages(stages, RAGAS_STAGES[5], scenario_tail=f"(프롬프트 번역 LLM {translated}회 포함)" if translated else "")

        generator = TestsetGenerator(llm=self.llm, embedding_model=self.embedding, knowledge_graph=kg, persona_list=personas, llm_context=llm_context)
        guarded = [(GuardedSynthesizer(s, self.report, events), p) for s, p in distribution]
        try:
            with quiet_ragas_bars():
                testset = generator.generate(testset_size=size, query_distribution=guarded, num_personas=self.options.num_personas, run_config=self.run_config, raise_exceptions=True)
        except Exception as e:
            raise GenerateError(f"ragas: {type(e).__name__}: {e}") from e
        events.open_samples()  # 시나리오가 하나도 없었으면 여기서 질문·정답 단계가 열린다

        unmatched_before = self.report.unmatched
        made = candidates_from_ragas(testset.samples, docs, self.chat.model, self.report)
        candidates = made[:size]
        self.report.produced = len(candidates)
        tail = f"출처 못 찾음 {self.report.unmatched - unmatched_before}"
        if len(made) > size:
            tail += f"  요청한 {size}개만 저장"
        stages.finish(f"{len(made)}/{events.total}", failed=stages.failed_items, tail=tail)
        return candidates
