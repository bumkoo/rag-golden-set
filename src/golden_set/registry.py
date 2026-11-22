"""확장자 → 로더 레지스트리."""

from pathlib import Path

from langchain_core.documents import Document

from golden_set.loaders.base import Loader, UnsupportedError
from golden_set.loaders.txt import TxtLoader

# 확장자마다 로더 목록. 맨 앞이 기본 로더, 나머지는 비교용 대안이다.
_LOADERS: dict[str, list[Loader]] = {
    ".txt": [TxtLoader()],
}


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
