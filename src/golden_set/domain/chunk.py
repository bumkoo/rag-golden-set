"""청크의 표현과 chunk_id 규칙."""

import hashlib
from pathlib import Path


def make_chunk_id(source: str, page: int | None, index: int) -> str:
    """파일 경로, 쪽, 순번으로 만든 고정 값. 같은 입력이면 언제 돌려도 같다."""
    digest = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:8]
    return f"{Path(str(source)).name}:p{page or 0}:{index}:{digest}"
