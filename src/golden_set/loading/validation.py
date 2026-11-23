"""로더 출력 검증. 입력은 list[Document]뿐이라 로더를 바꿔도 이 코드는 바뀌지 않는다."""

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.documents import Document


@dataclass(frozen=True)
class Thresholds:
    """합격 기준값. 기준은 전부 여기에만 둔다."""

    min_doc_count: int = 1
    empty_doc_chars: int = 20  # 공백 제거 후 이 글자 수 미만이면 빈 문서로 센다
    max_empty_ratio_paged: float = 0.30  # pdf, pptx
    max_empty_ratio_other: float = 0.0  # 그 외 형식
    paged_types: tuple[str, ...] = ("pdf", "pptx")  # 쪽 단위 형식. page 메타데이터가 필수다
    min_avg_chars: float = 50.0
    max_broken_ratio: float = 0.005
    required_meta: tuple[str, ...] = ("source", "file_type", "loader")


@dataclass
class FileReport:
    """파일 하나의 검증 결과."""

    path: str
    loader: str
    file_type: str
    doc_count: int
    empty_ratio: float
    avg_chars: float
    broken_ratio: float
    hangul_ratio: float
    meta_ok: bool
    elapsed_sec: float | None
    passed: bool
    reasons: list[str] = field(default_factory=list)


def _is_broken(ch: str) -> bool:
    """U+FFFD이거나 개행(\\n, \\r)과 탭이 아닌 제어문자인지."""
    return ch == "�" or (unicodedata.category(ch) == "Cc" and ch not in "\n\r\t")


def _is_hangul_syllable(ch: str) -> bool:
    """한글 음절(U+AC00~U+D7A3)인지."""
    return "가" <= ch <= "힣"


def _meta_ok(docs: list[Document], file_type: str, th: Thresholds) -> bool:
    """모든 문서에 필수 메타데이터 키가 있는지. 쪽 단위 형식은 1 이상의 page도 있어야 한다."""
    for doc in docs:
        if any(not doc.metadata.get(key) for key in th.required_meta):
            return False
        if file_type in th.paged_types:
            page = doc.metadata.get("page")
            if not isinstance(page, int) or isinstance(page, bool) or page < 1:
                return False
    return True


def validate_docs(
    path: str,
    loader_name: str,
    docs: list[Document],
    thresholds: Thresholds | None = None,
    elapsed_sec: float | None = None,
) -> FileReport:
    """파일 하나의 로더 출력으로 지표를 계산하고 합격 여부를 판정한다."""
    th = thresholds or Thresholds()
    file_type = Path(path).suffix.lower().lstrip(".")
    texts = [doc.page_content for doc in docs]
    total_chars = sum(len(t) for t in texts)
    visible_chars = sum(len("".join(t.split())) for t in texts)

    doc_count = len(docs)
    empty = sum(1 for t in texts if len("".join(t.split())) < th.empty_doc_chars)
    empty_ratio = empty / doc_count if doc_count else 0.0
    avg_chars = total_chars / doc_count if doc_count else 0.0
    broken_ratio = sum(_is_broken(c) for t in texts for c in t) / total_chars if total_chars else 0.0
    hangul_ratio = (
        sum(_is_hangul_syllable(c) for t in texts for c in t) / visible_chars if visible_chars else 0.0
    )
    meta_ok = _meta_ok(docs, file_type, th)

    max_empty = th.max_empty_ratio_paged if file_type in th.paged_types else th.max_empty_ratio_other
    reasons: list[str] = []
    if doc_count < th.min_doc_count:
        reasons.append(f"doc_count {doc_count} < {th.min_doc_count}")
    if empty_ratio > max_empty:
        reasons.append(f"empty_ratio {empty_ratio:.1%} > {max_empty:.1%}")
    if avg_chars < th.min_avg_chars:
        reasons.append(f"avg_chars {avg_chars:.1f} < {th.min_avg_chars:g}")
    if broken_ratio > th.max_broken_ratio:
        reasons.append(f"broken_ratio {broken_ratio:.2%} > {th.max_broken_ratio:.2%}")
    if not meta_ok:
        reasons.append("meta_ok false")

    return FileReport(
        path=str(path),
        loader=loader_name,
        file_type=file_type,
        doc_count=doc_count,
        empty_ratio=empty_ratio,
        avg_chars=avg_chars,
        broken_ratio=broken_ratio,
        hangul_ratio=hangul_ratio,
        meta_ok=meta_ok,
        elapsed_sec=elapsed_sec,
        passed=not reasons,
        reasons=reasons,
    )
