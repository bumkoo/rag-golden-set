"""DeepEval 생성기. Synthesizer.generate_goldens_from_contexts에 우리 청크로 만든 context를 넘긴다."""

import asyncio
from dataclasses import dataclass, field

from deepeval.dataset.golden import Golden
from deepeval.synthesizer.config import EvolutionConfig, FiltrationConfig, StylingConfig
from langchain_core.documents import Document

from golden_set.domain.candidate import GoldenCandidate, make_id
from golden_set.domain.language import detect_language
from golden_set.generation.deepeval.adapters import ChatDeepEvalModel
from golden_set.generation.deepeval.contexts import ContextGroup, build_contexts, choose_contexts
from golden_set.generation.generator import GenerateError, GenerateReport
from golden_set.generation.llm.client import ChatClient
from golden_set.generation.llm.settings import LLMSettings
from golden_set.generation.matching import ChunkIndex, sources_for

# StylingConfig로 질문·정답 언어를 근거 본문과 맞춘다. 템플릿 자체는 언어를 지정하지 않는다 (deepeval 4.3.4).
STYLING = {
    "ko": StylingConfig(
        input_format="A single question written in Korean (한국어), the same language as the context, answerable from the context alone. Do not translate names or terms.",
        expected_output_format="A complete answer written in Korean (한국어) using only information from the context.",
    ),
    "en": StylingConfig(
        input_format="A single question written in English, the same language as the context, answerable from the context alone.",
        expected_output_format="A complete answer written in English using only information from the context.",
    ),
}


# ---- 결과 변환 ----


def candidates_from_deepeval(goldens: list[Golden], chunks: list[Document], model: str, report: GenerateReport | None = None) -> list[GoldenCandidate]:
    """deepeval Golden 목록을 GoldenCandidate로 옮긴다. context는 우리 청크 본문 그대로라 sources를 정확히 채운다."""
    report = report or GenerateReport("deepeval")
    index = ChunkIndex(chunks)
    out: list[GoldenCandidate] = []
    for g in goldens:
        question = (g.input or "").strip()
        answer = (g.expected_output or "").strip()
        contexts = [c for c in (g.context or []) if c]
        if not question or not answer:
            report.skip(f"empty question or answer: {question[:60]!r}")
            continue
        sources, missing = sources_for(contexts, index)
        if missing:
            report.notes.append(f"{make_id('deepeval', len(out) + 1)}: {missing} context(s) not matched to a chunk")
        evolutions = (g.additional_metadata or {}).get("evolutions") or []
        out.append(
            GoldenCandidate(
                id=make_id("deepeval", len(out) + 1),
                question=question,
                reference_answer=answer,
                reference_contexts=contexts,
                sources=sources,
                question_type="+".join(str(getattr(e, "value", e)) for e in evolutions),
                language=detect_language(question),
                generator="deepeval",
                model=model,
            )
        )
    return out


# ---- 생성기 ----


@dataclass
class DeepEvalOptions:
    language: str = "auto"
    context_chunks: int = 3  # context 하나에 넣는 이웃 청크 수 (1~3)
    max_goldens_per_context: int = 2  # deepeval 기본값
    evolutions: int = 1  # deepeval 기본값. 0이면 질문을 그대로 쓴다
    styling: dict = field(default_factory=lambda: dict(STYLING))


class DeepEvalGenerator:
    """Generator 프로토콜 구현."""

    name = "deepeval"

    def __init__(self, settings: LLMSettings, report: GenerateReport | None = None, chat: ChatClient | None = None, **options):
        self.settings = settings
        self.options = DeepEvalOptions(**options)
        self.report = report or GenerateReport(self.name)
        self.chat = chat or ChatClient(settings.llm, settings, log=self.report.llm)
        self.model = ChatDeepEvalModel(self.chat, self.report)

    def _synthesizer(self, language: str):
        from deepeval.synthesizer import Synthesizer

        return Synthesizer(
            model=self.model,
            async_mode=True,
            max_concurrent=self.settings.concurrency,
            filtration_config=FiltrationConfig(critic_model=self.model),  # critic도 우리 모델. 비우면 OpenAI 기본 모델을 만든다
            evolution_config=EvolutionConfig(num_evolutions=self.options.evolutions),
            styling_config=self.options.styling[language],
        )

    async def _run(self, synthesizer, groups: list[ContextGroup], per_context: int) -> list[Golden]:
        from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

        sem = asyncio.Semaphore(self.settings.concurrency)
        results: list[Golden] = []

        async def one(i: int, group: ContextGroup, progress, pbar_id):
            async with sem:
                try:
                    goldens = await synthesizer.a_generate_goldens_from_contexts(
                        contexts=[group.texts],
                        include_expected_output=True,
                        max_goldens_per_context=per_context,
                        source_files=[group.source],
                        _progress=progress,
                        _pbar_id=pbar_id,
                        _reset_cost=False,
                    )
                except Exception as e:  # context 하나의 실패는 건너뛴다. deepeval은 안에서 잡지 않는다
                    self.report.skip(f"context #{i} ({group.source}): {type(e).__name__}: {str(e).splitlines()[0][:160]}")
                    return
                results.extend(goldens)

        # 진행 표시는 하나만 만든다. 호출마다 만들면 rich가 동시 표시를 거부한다
        with Progress(TextColumn("{task.description}"), BarColumn(), TimeElapsedColumn(), transient=True) as progress:
            pbar_id = progress.add_task(f"deepeval: {len(groups)} contexts x {per_context}", total=len(groups))
            await asyncio.gather(*(one(i, g, progress, pbar_id) for i, g in enumerate(groups)))
        return results

    def generate(self, chunks: list[Document], size: int) -> list[GoldenCandidate]:
        docs = [c for c in chunks if c.page_content.strip()]
        if not docs:
            raise GenerateError("no chunks")
        self.report.requested = size
        language = self.options.language if self.options.language != "auto" else detect_language(" ".join(c.page_content for c in docs))
        groups, per_context = choose_contexts(build_contexts(docs, self.options.context_chunks), size, self.options.max_goldens_per_context)
        self.report.notes.append(f"language={language}  contexts={len(groups)} (of {len(build_contexts(docs, self.options.context_chunks))}) x {per_context} goldens  evolutions={self.options.evolutions}")

        synthesizer = self._synthesizer(language)
        try:
            goldens = asyncio.run(self._run(synthesizer, groups, per_context))
        except Exception as e:
            raise GenerateError(f"deepeval: {type(e).__name__}: {e}") from e
        if self.model.parse_failures:
            self.report.notes.append(f"json parse failures: {len(self.model.parse_failures)}")
        candidates = candidates_from_deepeval(goldens, docs, self.chat.model, self.report)[:size]
        self.report.produced = len(candidates)
        return candidates
