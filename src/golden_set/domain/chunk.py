"""청크의 표현과 chunk_id 규칙. 청킹의 출력부터 생성과 평가까지 이 타입으로 주고받는다."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

_FIELD_KEYS = ("source", "file_type", "loader", "page", "chunk_id")  # metadata에서 필드로 올라오는 키


@dataclass(frozen=True)
class Chunk:
    """문서에서 잘라 낸 조각 하나. chunks.jsonl의 한 줄이다."""

    chunk_id: str
    text: str
    source: str = ""  # 파일 경로
    page: int | None = None  # 쪽 단위 형식(pdf, pptx)만
    file_type: str = ""
    loader: str = ""
    extra: dict = field(default_factory=dict, hash=False)  # 그 밖의 메타데이터 (chunk_index 등)

    @property
    def metadata(self) -> dict:
        """chunks.jsonl의 metadata 꼴: 로더 메타데이터(source, file_type, loader, page), chunk_id, 그 밖의 것 순서다."""
        out: dict = {}
        for key in ("source", "file_type", "loader"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        if self.page is not None:
            out["page"] = self.page
        out["chunk_id"] = self.chunk_id
        out.update(self.extra)
        return out

    @classmethod
    def from_metadata(cls, text: str, metadata: dict) -> "Chunk":
        """본문과 metadata dict로 만든다. chunk_id가 없으면 KeyError. 정수가 아닌 page는 extra에 그대로 둔다."""
        page = metadata.get("page")
        page_is_number = isinstance(page, int) and not isinstance(page, bool)
        return cls(
            chunk_id=str(metadata["chunk_id"]),
            text=text,
            source=str(metadata.get("source", "")),
            page=page if page_is_number else None,
            file_type=str(metadata.get("file_type", "")),
            loader=str(metadata.get("loader", "")),
            extra={k: v for k, v in metadata.items() if k not in _FIELD_KEYS or (k == "page" and not page_is_number and page is not None)},
        )


def make_chunk_id(source: str, page: int | None, index: int) -> str:
    """파일 경로, 쪽, 순번으로 만든 고정 값. 같은 입력이면 언제 돌려도 같다."""
    digest = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:8]
    return f"{Path(str(source)).name}:p{page or 0}:{index}:{digest}"
