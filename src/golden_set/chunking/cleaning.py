"""반복 머리글·바닥글 제거. 쪽 단위 파일(page 메타데이터가 있는 Document)만 다룬다."""

import re
from collections import Counter
from dataclasses import dataclass, field

from langchain_core.documents import Document


@dataclass(frozen=True)
class CleanSettings:
    """제거 기준. 기준은 전부 여기에만 둔다."""

    min_ratio: float = 0.60  # 전체 쪽 중 이 비율 이상에서 반복되는 줄만 지운다
    min_pages: int = 3  # 쪽 수가 이보다 적은 파일은 건드리지 않는다 (비교할 쪽이 모자란다)


@dataclass(frozen=True)
class RemovedLine:
    """지운 줄 하나. pattern은 숫자를 #으로 바꾼 꼴, example은 실제로 지운 줄 가운데 하나다."""

    position: str  # "head" | "tail"
    pattern: str
    example: str
    count: int


@dataclass
class CleanReport:
    """파일 하나의 제거 결과."""

    source: str
    page_count: int
    removed: list[RemovedLine] = field(default_factory=list)


_DIGITS = re.compile(r"\d+")
_SPACES = re.compile(r"\s+")


def line_key(line: str) -> str:
    """비교용 열쇠. 공백을 하나로 모으고 숫자는 #으로 바꿔서 쪽 번호만 다른 줄을 같은 줄로 본다."""
    return _DIGITS.sub("#", _SPACES.sub(" ", line.strip()))


def _edge_index(lines: list[str], position: str) -> int | None:
    """첫(또는 끝) 비어 있지 않은 줄의 번호. 전부 빈 줄이면 None."""
    order = range(len(lines)) if position == "head" else range(len(lines) - 1, -1, -1)
    for i in order:
        if lines[i].strip():
            return i
    return None


def _clean_file(docs: list[Document], settings: CleanSettings) -> tuple[list[Document], CleanReport]:
    """한 파일의 쪽들에서 반복되는 첫 줄과 끝 줄을 지운다."""
    source = str(docs[0].metadata.get("source", ""))
    report = CleanReport(source=source, page_count=len(docs))
    if len(docs) < settings.min_pages:
        return docs, report

    pages = [doc.page_content.split("\n") for doc in docs]
    edges = {pos: [_edge_index(lines, pos) for lines in pages] for pos in ("head", "tail")}
    # 한 쪽에 줄이 하나뿐이면 head와 tail이 같은 줄이다. tail에서 두 번 세지 않는다.
    for i, lines in enumerate(pages):
        if edges["tail"][i] is not None and edges["tail"][i] == edges["head"][i]:
            edges["tail"][i] = None

    to_remove: dict[str, set[str]] = {}
    for pos in ("head", "tail"):
        counts = Counter(line_key(pages[i][idx]) for i, idx in enumerate(edges[pos]) if idx is not None)
        keep = {key for key, n in counts.items() if key and n / len(docs) >= settings.min_ratio}
        to_remove[pos] = keep
        for key in sorted(keep):
            example = next(pages[i][idx].strip() for i, idx in enumerate(edges[pos]) if idx is not None and line_key(pages[i][idx]) == key)
            report.removed.append(RemovedLine(pos, key, example, counts[key]))

    if not any(to_remove.values()):
        return docs, report

    cleaned: list[Document] = []
    for i, (doc, lines) in enumerate(zip(docs, pages)):
        drop = {
            edges[pos][i]
            for pos in ("head", "tail")
            if edges[pos][i] is not None and line_key(lines[edges[pos][i]]) in to_remove[pos]
        }
        if not drop:
            cleaned.append(doc)
            continue
        kept = [line for j, line in enumerate(lines) if j not in drop]
        text = "\n".join(kept).strip("\n")
        cleaned.append(Document(page_content=text, metadata=dict(doc.metadata)))
    return cleaned, report


def clean_docs(docs: list[Document], settings: CleanSettings | None = None) -> tuple[list[Document], list[CleanReport]]:
    """같은 source의 쪽들을 묶어 반복 머리글·바닥글을 지운다. 순서와 개수는 그대로다.

    page 메타데이터가 없는 문서(txt, docx, doc)는 손대지 않고 리포트에도 넣지 않는다.
    """
    st = settings or CleanSettings()
    groups: dict[str, list[int]] = {}
    for i, doc in enumerate(docs):
        if doc.metadata.get("page") is not None:
            groups.setdefault(str(doc.metadata.get("source", "")), []).append(i)

    out = list(docs)
    reports: list[CleanReport] = []
    for source, indexes in groups.items():
        cleaned, report = _clean_file([docs[i] for i in indexes], st)
        for i, doc in zip(indexes, cleaned):
            out[i] = doc
        reports.append(report)
    return out, reports
