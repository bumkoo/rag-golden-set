"""생성기 공통: Generator 프로토콜, 실행 리포트, 근거 본문 ↔ 청크 대조."""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from langchain_core.documents import Document

from golden_set.candidates import GoldenCandidate, Source
from golden_set.llm import CallLog

GENERATOR_NAMES = ("ragas", "deepeval")


class GenerateError(Exception):
    """생성을 시작하지 못했거나 끝까지 하나도 만들지 못했을 때."""


@runtime_checkable
class Generator(Protocol):
    """모든 생성기가 지키는 프로토콜."""

    name: str  # "ragas" | "deepeval"

    def generate(self, chunks: list[Document], size: int) -> list[GoldenCandidate]: ...


@dataclass
class GenerateReport:
    """한 번의 생성 결과 집계. LLM 요청 수는 llm(CallLog)에, 항목 단위 실패는 skipped에 쌓인다."""

    generator: str
    requested: int = 0
    produced: int = 0
    skipped: list[str] = field(default_factory=list)  # 건너뛴 항목과 사유
    notes: list[str] = field(default_factory=list)  # 경고, 적용한 옵션 등
    llm: CallLog = field(default_factory=CallLog)
    embed: CallLog = field(default_factory=CallLog)

    def skip(self, reason: str) -> None:
        self.skipped.append(reason[:300])

    def summary(self) -> str:
        why = Counter(r.split(":")[0] for r in self.skipped)
        lines = [
            f"generator={self.generator}  requested={self.requested}  produced={self.produced}  skipped={len(self.skipped)}",
            f"llm    {self.llm.summary()}",
        ]
        if self.embed.requests:
            lines.append(f"embed  {self.embed.summary()}")
        for reason, n in why.most_common():
            lines.append(f"  skipped x{n}: {reason}")
        for note in self.notes:
            lines.append(f"  note: {note}")
        return "\n".join(lines)


# ---- 언어 ----

KO_HANGUL_RATIO = 0.3  # 글자(한글 음절 + 로마자) 중 한글 음절 비율이 이 이상이면 ko


def detect_language(text: str, ko_ratio: float = KO_HANGUL_RATIO) -> str:
    """한글 음절 비율로 ko 또는 en을 정한다. 글자가 하나도 없으면 en."""
    hangul = sum(1 for c in text if "가" <= c <= "힣")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    letters = hangul + latin
    if letters == 0:
        return "en"
    return "ko" if hangul / letters >= ko_ratio else "en"


# ---- 근거 본문 ↔ 청크 대조 ----

_SPACES = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


class ChunkIndex:
    """청크 본문으로 청크를 찾는다. 정확히 같으면 그것, 아니면 공백만 다른 것, 그래도 없으면 None."""

    def __init__(self, chunks: list[Document]):
        self.by_id: dict[str, Document] = {}
        self.exact: dict[str, Document] = {}
        self.normalized: dict[str, Document] = {}
        for c in chunks:
            self.by_id.setdefault(str(c.metadata.get("chunk_id", "")), c)
            self.exact.setdefault(c.page_content, c)
            self.normalized.setdefault(normalize_text(c.page_content), c)

    def find(self, text: str) -> Document | None:
        return self.exact.get(text) or self.normalized.get(normalize_text(text))

    def source_of(self, text: str) -> Source | None:
        chunk = self.find(text)
        if chunk is None:
            return None
        return source_from_chunk(chunk)


def source_from_chunk(chunk: Document) -> Source:
    page = chunk.metadata.get("page")
    return Source(chunk_id=str(chunk.metadata.get("chunk_id", "")), source=str(chunk.metadata.get("source", "")), page=page if isinstance(page, int) else None)


def sources_for(contexts: list[str], index: ChunkIndex) -> tuple[list[Source], int]:
    """근거 본문마다 출처를 찾는다. (찾은 출처들, 못 찾은 개수). 같은 청크는 한 번만 넣는다."""
    found: list[Source] = []
    missing = 0
    for text in contexts:
        src = index.source_of(text)
        if src is None:
            missing += 1
        elif src not in found:
            found.append(src)
    return found, missing


def get_generator(name: str, settings, report: GenerateReport | None = None, **options) -> Generator:
    """이름으로 생성기를 만든다. 해당 패키지가 없으면 GenerateError."""
    if name == "ragas":
        try:
            from golden_set.generators.ragas_gen import RagasGenerator
        except ImportError as e:
            raise GenerateError(f"ragas is not installed (pip install -e '.[generate]'): {e}") from e
        return RagasGenerator(settings, report=report, **options)
    if name == "deepeval":
        try:
            from golden_set.generators.deepeval_gen import DeepEvalGenerator
        except ImportError as e:
            raise GenerateError(f"deepeval is not installed (pip install -e '.[generate]'): {e}") from e
        return DeepEvalGenerator(settings, report=report, **options)
    raise GenerateError(f"unknown generator {name!r} (available: {', '.join(GENERATOR_NAMES)})")
