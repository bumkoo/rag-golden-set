"""실제 LLM·임베딩 서버 호출. GOLDEN_LLM_BASE_URL이 있을 때만 돈다 (ragas는 GOLDEN_EMBED_BASE_URL도 필요).

    GOLDEN_LLM_BASE_URL=... GOLDEN_LLM_MODEL=... GOLDEN_EMBED_BASE_URL=... GOLDEN_EMBED_MODEL=... pytest tests/test_real_calls.py -v -s

픽스처 문서로 생성기마다 후보 5개를 요청하고, 후보가 1개 이상 나오며 check를 통과하는 후보가 있는지 본다.
"""

import os
from pathlib import Path

import pytest
from conftest import build_fixture_dir

from golden_set.cli import main

pytestmark = pytest.mark.skipif(not os.environ.get("GOLDEN_LLM_BASE_URL"), reason="GOLDEN_LLM_BASE_URL 이 지정되지 않음")


@pytest.fixture(scope="module")
def chunks_file(tmp_path_factory) -> Path:
    root = build_fixture_dir(tmp_path_factory.mktemp("docs") / "fx")
    out = tmp_path_factory.mktemp("out") / "chunks.jsonl"
    assert main(["prepare", str(root), "--out", str(out)]) in (0, 1)  # broken.pdf 때문에 1
    return out


def test_ping() -> None:
    assert main(["ping"]) == 0


def _generate_and_check(generator: str, chunks_file: Path, size: int = 5) -> None:
    from golden_set.domain.store import read_candidates, read_chunks
    from golden_set.check import check_candidates

    out = chunks_file.parent / f"{generator}.candidates.jsonl"
    assert main(["generate", str(chunks_file), "--generator", generator, "--size", str(size), "--out", str(out)]) == 0
    cands = read_candidates(str(out))
    assert len(cands) >= 1
    assert all(c.generator == generator and c.question and c.reference_answer for c in cands)
    chunk_ids = {c.metadata["chunk_id"] for c in read_chunks(str(chunks_file))}
    results = check_candidates(cands, chunk_ids)
    assert any(r.passed for r in results), [r.reasons for r in results]


def test_generate_ragas(chunks_file: Path) -> None:
    if not os.environ.get("GOLDEN_EMBED_BASE_URL"):
        pytest.skip("GOLDEN_EMBED_BASE_URL 이 지정되지 않음")
    _generate_and_check("ragas", chunks_file)


def test_generate_deepeval(chunks_file: Path) -> None:
    _generate_and_check("deepeval", chunks_file)
