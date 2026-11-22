"""DeepEval 생성기. Synthesizer.generate_goldens_from_contexts에 우리 청크로 만든 context를 넘긴다.

확인한 버전: deepeval 4.3.4 (NOTES.md 참고). 파일을 도구가 직접 읽는 generate_goldens_from_docs는 쓰지 않는다.
이 모듈은 deepeval이 설치되어 있을 때만 import된다.
"""

import asyncio
import math
import os
from dataclasses import dataclass, field

# 사용 통계(PostHog)와 .deepeval/ 폴더 생성, .env 자동 읽기를 끈다. import 전에 있어야 한다.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("DEEPEVAL_DISABLE_DOTENV", "1")

from deepeval.dataset.golden import Golden
from deepeval.models import DeepEvalBaseLLM
from deepeval.synthesizer.config import EvolutionConfig, FiltrationConfig, StylingConfig
from langchain_core.documents import Document

from golden_set.candidates import GoldenCandidate, make_id
from golden_set.generators.base import ChunkIndex, GenerateError, GenerateReport, detect_language, extract_json, sources_for
from golden_set.llm import ChatClient, LLMError, LLMSettings

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
MAX_GOLDENS_PER_CONTEXT = 5  # context가 모자랄 때 context 하나에서 뽑는 상한


class ChatDeepEvalModel(DeepEvalBaseLLM):
    """DeepEvalBaseLLM을 ChatClient로 구현한다.

    schema가 오면 JSON 모드로 요청해 그 pydantic 모델 인스턴스를 돌려준다. 파싱이 안 되면 LLMError를 낸다
    (TypeError가 아니어야 한다: deepeval은 TypeError를 "schema를 못 받는 모델"로 해석해 다른 경로로 간다).
    """

    def __init__(self, client: ChatClient, report: GenerateReport | None = None):
        self.client = client
        self.report = report
        self.parse_failures: list[str] = []
        super().__init__(model=client.model)

    def load_model(self, *args, **kwargs):
        return self.client

    def get_model_name(self, *args, **kwargs) -> str:
        return self.client.model

    @staticmethod
    def text_field(schema) -> str | None:
        """문자열 필드 하나뿐인 스키마(예: Response.response)면 그 필드 이름. deepeval은 이런 스키마로 자유 텍스트를 받는다."""
        fields = getattr(schema, "model_fields", {})
        if len(fields) == 1:
            (name, info), = fields.items()
            if info.annotation is str:
                return name
        return None

    def _to_schema(self, text: str, schema):
        field = self.text_field(schema)
        try:
            return schema.model_validate(extract_json(text))
        except Exception as e:  # ValueError(JSON 없음)나 pydantic ValidationError
            if field is not None:  # 프롬프트가 자유 텍스트를 요구한 경우다. 본문을 그대로 담는다
                return schema(**{field: text})
            reason = f"{schema.__name__}: {type(e).__name__}: {str(e).splitlines()[0][:120]}"
            self.parse_failures.append(reason)
            self.client.log.fail(f"json parse ({reason})")
            raise LLMError(f"response did not match {reason}") from e

    def _json_mode(self, schema) -> bool:
        """JSON 키를 지정한 프롬프트에만 JSON 모드를 쓴다. 자유 텍스트 스키마(Response)는 서버가 JSON을 강제하면 안 된다."""
        return schema is not None and self.text_field(schema) is None

    def generate(self, prompt: str, schema=None, **kwargs):
        (c,) = self.client.complete([("user", prompt)], json=self._json_mode(schema))
        return c.text if schema is None else self._to_schema(c.text, schema)

    async def a_generate(self, prompt: str, schema=None, **kwargs):
        (c,) = await self.client.acomplete([("user", prompt)], json=self._json_mode(schema))
        return c.text if schema is None else self._to_schema(c.text, schema)


# ---- context 구성 ----


@dataclass
class ContextGroup:
    """같은 파일의 이웃한 청크 1~3개."""

    chunks: list[Document]

    @property
    def texts(self) -> list[str]:
        return [c.page_content for c in self.chunks]

    @property
    def source(self) -> str:
        return str(self.chunks[0].metadata.get("source", ""))


def build_contexts(chunks: list[Document], per_context: int = 3) -> list[ContextGroup]:
    """파일별로 청크를 순서대로 per_context개씩 묶는다. 마지막 묶음은 더 짧을 수 있다."""
    if not 1 <= per_context <= 3:
        raise ValueError("per_context must be 1..3")
    by_source: dict[str, list[Document]] = {}
    for c in chunks:
        if c.page_content.strip():
            by_source.setdefault(str(c.metadata.get("source", "")), []).append(c)
    groups: list[ContextGroup] = []
    for docs in by_source.values():
        for i in range(0, len(docs), per_context):
            groups.append(ContextGroup(docs[i : i + per_context]))
    return groups


def choose_contexts(groups: list[ContextGroup], size: int, max_goldens_per_context: int = 2) -> tuple[list[ContextGroup], int]:
    """size개를 만들기 위해 쓸 context와 context당 후보 수를 정한다. 파일을 돌아가며 고른다.

    context가 모자라면 context당 후보 수를 올린다 (상한 MAX_GOLDENS_PER_CONTEXT).
    """
    if not groups:
        return [], max_goldens_per_context
    per_context = max_goldens_per_context
    needed = math.ceil(size / per_context)
    if needed > len(groups):
        per_context = min(MAX_GOLDENS_PER_CONTEXT, math.ceil(size / len(groups)))
        needed = len(groups)
    by_source: dict[str, list[ContextGroup]] = {}
    for g in groups:
        by_source.setdefault(g.source, []).append(g)
    chosen: list[ContextGroup] = []
    queues = list(by_source.values())
    while len(chosen) < needed and any(queues):
        for q in queues:
            if q and len(chosen) < needed:
                chosen.append(q.pop(0))
    return chosen, per_context


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
