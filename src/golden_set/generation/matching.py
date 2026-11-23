"""도구 출력을 우리 형식으로 옮길 때 쓰는 것: 응답에서 JSON 꺼내기, 근거 본문 ↔ 청크 대조."""

import re

from golden_set.domain.candidate import Source
from golden_set.domain.chunk import Chunk


def extract_json(text: str):
    """응답 본문에서 첫 JSON 값(객체나 배열)을 꺼낸다. ```json 울타리가 있으면 그 안을 먼저 본다.

    앞뒤의 설명 문장은 무시한다. JSON이 없거나 깨져 있으면 ValueError.
    """
    import json

    body = text
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        body = fence.group(1)
    starts = [i for i in (body.find("{"), body.find("[")) if i != -1]
    if not starts:
        raise ValueError("no json object in response")
    try:
        value, _ = json.JSONDecoder().raw_decode(body[min(starts) :])
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid json: {e.msg} at {e.pos}") from e
    return value


_SPACES = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


class ChunkIndex:
    """청크 본문으로 청크를 찾는다. 정확히 같으면 그것, 아니면 공백만 다른 것, 그래도 없으면 None."""

    def __init__(self, chunks: list[Chunk]):
        self.by_id: dict[str, Chunk] = {}
        self.exact: dict[str, Chunk] = {}
        self.normalized: dict[str, Chunk] = {}
        for c in chunks:
            self.by_id.setdefault(c.chunk_id, c)
            self.exact.setdefault(c.text, c)
            self.normalized.setdefault(normalize_text(c.text), c)

    def find(self, text: str) -> Chunk | None:
        return self.exact.get(text) or self.normalized.get(normalize_text(text))

    def source_of(self, text: str) -> Source | None:
        chunk = self.find(text)
        if chunk is None:
            return None
        return source_from_chunk(chunk)


def source_from_chunk(chunk: Chunk) -> Source:
    return Source(chunk_id=chunk.chunk_id, source=chunk.source, page=chunk.page)


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
