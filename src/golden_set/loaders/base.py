"""로더 공통 인터페이스."""

from pathlib import Path
from typing import Protocol, runtime_checkable

from langchain_core.documents import Document


class LoadError(Exception):
    """파일을 읽지 못했을 때. 원인 메시지를 담는다."""


class UnsupportedError(LoadError):
    """지원하지 않는 확장자이거나 등록되지 않은 로더 이름일 때."""


@runtime_checkable
class Loader(Protocol):
    """모든 로더가 지키는 프로토콜."""

    name: str  # 리포트에 찍히는 도구 이름, 예: "pymupdf"
    extensions: tuple[str, ...]  # 예: (".pdf",)

    def load(self, path: str) -> list[Document]: ...


def make_doc(text: str, path: str, loader_name: str, page: int | None = None) -> Document:
    """메타데이터 규약(source, file_type, loader, page)을 채운 Document를 만든다."""
    metadata: dict[str, object] = {
        "source": str(path),
        "file_type": Path(path).suffix.lower().lstrip("."),
        "loader": loader_name,
    }
    if page is not None:
        metadata["page"] = page
    return Document(page_content=text, metadata=metadata)
