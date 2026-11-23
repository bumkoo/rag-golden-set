"""Document → Chunk. 글자 수 기준으로 문단과 문장 경계에서 자른다. 저장은 domain.store가 한다."""

import re
from dataclasses import dataclass

from langchain_core.documents import Document

from golden_set.domain.chunk import Chunk, make_chunk_id


@dataclass(frozen=True)
class ChunkSettings:
    """청킹 기준. 기준은 전부 여기에만 둔다."""

    size: int = 1200  # 청크 하나의 최대 글자 수 (공백 포함)
    overlap: int = 150  # 앞 청크 끝부분을 다음 청크 앞에 다시 넣는 글자 수 (상한)
    min_chars: int = 100  # 공백 제거 후 이 글자 수 미만인 청크는 버린다

    def __post_init__(self) -> None:
        if self.size <= 0 or self.overlap < 0 or self.overlap >= self.size:
            raise ValueError(f"need 0 <= overlap < size, got size={self.size} overlap={self.overlap}")


_PARAGRAPH = re.compile(r"\n[ \t]*\n+")
# 문장 끝: 마침표·물음표·느낌표 뒤의 공백, 또는 줄바꿈. 숫자 바로 뒤의 마침표("1. ", "제11. ")는 번호로 보고 자르지 않는다.
_SENTENCE_END = re.compile(r"(?<=[^\d\s][.!?])\s+|(?<=[。！？])\s*|\n")


def _hard_split(text: str, size: int, overlap: int) -> list[str]:
    """경계를 찾을 수 없는 긴 조각을 size 글자씩 자른다. 조각 사이는 overlap만큼 겹친다."""
    step = size - overlap
    return [text[i : i + size] for i in range(0, max(len(text) - overlap, 1), step)]


def split_units(text: str, settings: ChunkSettings) -> list[tuple[str, str]]:
    """자를 수 있는 가장 작은 단위 목록. (단위 앞에 붙는 구분자, 본문) 쌍이다.

    문단(빈 줄로 나뉨)이 size 이하면 문단 하나가 단위다. 더 길면 문장(또는 줄)으로 나누고,
    문장 하나가 size를 넘으면 글자 수로 억지로 나눈다.
    """
    units: list[tuple[str, str]] = []
    for p_i, para in enumerate(_PARAGRAPH.split(text)):
        para = para.strip()
        if not para:
            continue
        sep = "\n\n" if p_i else ""
        if len(para) <= settings.size:
            units.append((sep, para))
            continue
        for s_i, sentence in enumerate(s for s in _SENTENCE_END.split(para) if s and s.strip()):
            sentence = sentence.strip()
            s_sep = sep if s_i == 0 else " "
            if len(sentence) <= settings.size:
                units.append((s_sep, sentence))
                continue
            for h_i, piece in enumerate(_hard_split(sentence, settings.size, settings.overlap)):
                units.append((s_sep if h_i == 0 else " ", piece))
    if units:
        units[0] = ("", units[0][1])
    return units


def _joined_len(units: list[tuple[str, str]]) -> int:
    return sum(len(sep) + len(body) for sep, body in units) - (len(units[0][0]) if units else 0)


def _join(units: list[tuple[str, str]]) -> str:
    return "".join(body if i == 0 else sep + body for i, (sep, body) in enumerate(units))


def chunk_text(text: str, settings: ChunkSettings | None = None) -> list[str]:
    """글 하나를 size 이하의 청크로 나눈다. 다음 청크는 앞 청크의 마지막 단위들을 overlap 글자까지 다시 품는다."""
    st = settings or ChunkSettings()
    units = split_units(text, st)
    chunks: list[str] = []
    current: list[tuple[str, str]] = []
    for unit in units:
        if current and _joined_len(current + [unit]) > st.size:
            chunks.append(_join(current))
            carry: list[tuple[str, str]] = []
            for prev in reversed(current):
                if _joined_len([prev] + carry) > st.overlap:
                    break
                carry.insert(0, prev)
            current = carry
        current.append(unit)
    if current:
        chunks.append(_join(current))
    return [c for c in chunks if len("".join(c.split())) >= st.min_chars]


def chunk_docs(docs: list[Document], settings: ChunkSettings | None = None) -> list[Chunk]:
    """Document마다 청크를 만든다. 청크는 원본 메타데이터를 물려받고 chunk_id, chunk_index를 얻는다."""
    st = settings or ChunkSettings()
    out: list[Chunk] = []
    for doc in docs:
        source = str(doc.metadata.get("source", ""))
        page = doc.metadata.get("page")
        for i, text in enumerate(chunk_text(doc.page_content, st)):
            metadata = dict(doc.metadata)
            metadata["chunk_id"] = make_chunk_id(source, page, i)
            metadata["chunk_index"] = i
            out.append(Chunk.from_metadata(text, metadata))
    return out
