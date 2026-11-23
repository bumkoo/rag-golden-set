"""chunks.jsonl과 candidates.jsonl 읽기·쓰기. 컨텍스트 사이의 전달은 이 두 파일로 한다."""

import json

from langchain_core.documents import Document

from golden_set.domain.candidate import CandidateError, GoldenCandidate


def write_chunks(chunks: list[Document], path: str) -> None:
    """청크를 JSONL로 저장한다. 한 줄에 {"chunk_id", "text", "metadata"} 하나다."""
    with open(path, "w", encoding="utf-8") as f:
        for doc in chunks:
            row = {"chunk_id": doc.metadata["chunk_id"], "text": doc.page_content, "metadata": doc.metadata}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_chunks(path: str) -> list[Document]:
    """chunks.jsonl을 다시 Document 리스트로 읽는다. 빈 줄은 건너뛴다."""
    chunks: list[Document] = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            try:
                metadata = dict(row["metadata"])
                metadata.setdefault("chunk_id", row["chunk_id"])
                chunks.append(Document(page_content=row["text"], metadata=metadata))
            except (KeyError, TypeError) as e:
                raise ValueError(f"{path}:{n}: bad chunk row: {e}") from e
    return chunks


def write_candidates(candidates: list[GoldenCandidate], path: str, append: bool = False) -> None:
    """후보를 JSONL로 저장한다. 한글은 그대로 쓴다(ensure_ascii=False)."""
    with open(path, "a" if append else "w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")


def read_candidates(path: str) -> list[GoldenCandidate]:
    """candidates.jsonl을 읽는다. 깨진 줄은 줄 번호와 함께 CandidateError를 낸다."""
    out: list[GoldenCandidate] = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise CandidateError(f"{path}:{n}: not json: {e}") from e
            try:
                out.append(GoldenCandidate.from_dict(row))
            except CandidateError as e:
                raise CandidateError(f"{path}:{n}: {e}") from e
    return out
