"""확장자 → 로더 레지스트리."""

from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document

from golden_set.loaders.base import LoadError, Loader, UnsupportedError
from golden_set.loaders.docx import Docx2txtLoader
from golden_set.loaders.pdf import PyMuPDFLoader
from golden_set.loaders.pptx import PythonPptxLoader
from golden_set.loaders.txt import TxtLoader

# 확장자마다 로더 목록. 맨 앞이 기본 로더, 나머지는 비교용 대안이다.
_LOADERS: dict[str, list[Loader]] = {
    ".txt": [TxtLoader()],
    ".docx": [Docx2txtLoader()],
    ".pdf": [PyMuPDFLoader()],
    ".pptx": [PythonPptxLoader()],
}


@dataclass(frozen=True)
class Failure:
    """읽지 못한 파일 하나. reason은 지원하지 않는 확장자면 "unsupported"다."""

    path: str
    reason: str


def loaders_for(path: str) -> list[Loader]:
    """그 확장자에 등록된 모든 로더를 기본 로더부터 돌려준다. 없으면 빈 리스트."""
    return list(_LOADERS.get(Path(path).suffix.lower(), []))


def get_loader(path: str, name: str | None = None) -> Loader:
    """확장자로 기본 로더를 돌려준다. name을 주면 그 이름의 로더를 돌려준다."""
    candidates = loaders_for(path)
    if not candidates:
        raise UnsupportedError("unsupported")
    if name is None:
        return candidates[0]
    for loader in candidates:
        if loader.name == name:
            return loader
    known = ", ".join(c.name for c in candidates)
    raise UnsupportedError(f"unknown loader {name!r} for {Path(path).suffix.lower()} (available: {known})")


def load_path(path: str, loader_name: str | None = None) -> list[Document]:
    """파일 하나를 읽어 Document 리스트로 돌려준다. 실패하면 LoadError."""
    return get_loader(path, loader_name).load(str(path))


def list_files(root: str) -> list[str]:
    """root 아래 모든 파일 경로를 하위 폴더까지 정렬해서 돌려준다. 점으로 시작하는 파일과 폴더는 건너뛴다."""
    base = Path(root)
    if not base.is_dir():
        raise LoadError(f"not a directory: {root}")
    return [
        str(p)
        for p in sorted(base.rglob("*"))
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(base).parts)
    ]


def load_dir(root: str) -> tuple[list[Document], list[Failure]]:
    """하위 폴더까지 돌며 읽는다. 실패한 파일은 멈추지 않고 Failure로 모은다."""
    docs: list[Document] = []
    failures: list[Failure] = []
    for path in list_files(root):
        try:
            docs.extend(load_path(path))
        except LoadError as e:
            failures.append(Failure(path, str(e)))
    return docs, failures
