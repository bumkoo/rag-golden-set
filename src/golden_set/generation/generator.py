"""생성기 공통: Generator 프로토콜, 실행 리포트, 이름으로 생성기 만들기."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from langchain_core.documents import Document

from golden_set.domain.candidate import GoldenCandidate
from golden_set.generation.llm.client import CallLog
from golden_set.generation.progress import ProgressReporter

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
    unmatched: int = 0  # 근거 본문을 청크와 맞추지 못한 후보 수 (단계 요약에 쓴다)

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


def get_generator(name: str, settings, report: GenerateReport | None = None, reporter: ProgressReporter | None = None, **options) -> Generator:
    """이름으로 생성기를 만든다. 해당 패키지가 없으면 GenerateError. reporter를 안 주면 생성기가 화면용을 쓴다."""
    if name == "ragas":
        try:
            from golden_set.generation.ragas.generator import RagasGenerator
        except ImportError as e:
            raise GenerateError(f"ragas is not installed (pip install -e '.[generate]'): {e}") from e
        return RagasGenerator(settings, report=report, reporter=reporter, **options)
    if name == "deepeval":
        try:
            from golden_set.generation.deepeval.generator import DeepEvalGenerator
        except ImportError as e:
            raise GenerateError(f"deepeval is not installed (pip install -e '.[generate]'): {e}") from e
        return DeepEvalGenerator(settings, report=report, reporter=reporter, **options)
    raise GenerateError(f"unknown generator {name!r} (available: {', '.join(GENERATOR_NAMES)})")
