"""공통 스키마 GoldenCandidate. 두 생성기의 출력은 전부 이 꼴이다. 읽기·쓰기는 domain.store에 있다."""

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone


class CandidateError(ValueError):
    """후보 한 줄을 읽지 못했을 때 (필드 누락, 형식 오류)."""


@dataclass(frozen=True)
class Source:
    """근거 청크의 출처 하나."""

    chunk_id: str
    source: str  # 파일 경로
    page: int | None = None


@dataclass
class GoldenCandidate:
    """사람이 검수하기 전의 질문-정답 후보 하나."""

    id: str  # 생성기 이름 + 일련번호, 예: ragas-0001
    question: str
    reference_answer: str
    reference_contexts: list[str]
    sources: list[Source]
    question_type: str  # 도구가 붙인 유형. 없으면 ""
    language: str  # "ko" | "en"
    generator: str  # "ragas" | "deepeval"
    model: str  # 생성에 쓴 LLM 이름
    created_at: str = field(default_factory=lambda: now_iso())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, row: dict) -> "GoldenCandidate":
        """dict에서 만든다. 필수 필드가 없거나 타입이 다르면 CandidateError."""
        required = {f.name for f in fields(cls)} - {"created_at"}
        missing = sorted(required - set(row))
        if missing:
            raise CandidateError(f"missing fields: {', '.join(missing)}")
        try:
            sources = [Source(**s) for s in row["sources"]]
            contexts = list(row["reference_contexts"])
        except TypeError as e:
            raise CandidateError(f"bad sources or reference_contexts: {e}") from e
        for name in ("id", "question", "reference_answer", "question_type", "language", "generator", "model"):
            if not isinstance(row[name], str):
                raise CandidateError(f"field {name} must be a string")
        return cls(
            id=row["id"],
            question=row["question"],
            reference_answer=row["reference_answer"],
            reference_contexts=contexts,
            sources=sources,
            question_type=row["question_type"],
            language=row["language"],
            generator=row["generator"],
            model=row["model"],
            created_at=str(row.get("created_at") or now_iso()),
        )


def now_iso() -> str:
    """생성 시각. 초 단위 UTC ISO 8601."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_id(generator: str, number: int) -> str:
    """후보 id: 생성기 이름 + 네 자리 일련번호."""
    return f"{generator}-{number:04d}"
