"""context 구성: 같은 파일의 이웃한 청크를 묶고, 만들 후보 수에 맞춰 고른다."""

import math
from dataclasses import dataclass

from langchain_core.documents import Document

MAX_GOLDENS_PER_CONTEXT = 5  # context가 모자랄 때 context 하나에서 뽑는 상한


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
