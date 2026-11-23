"""reports/generate_stages.txt를 만든다: 가짜 LLM으로 돌린 generate의 화면 출력과 로그 파일.

    python tests/make_stage_report.py > reports/generate_stages.txt

서버는 필요 없다. 실제 ragas가 돌고 LLM·임베딩 응답만 tests/ragas_fake.py의 가짜가 낸다.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

CHUNKS = 40
SIZE = 30


def main() -> int:
    from ragas_fake import fake_ragas_factory, law_chunks

    import golden_set.generation as generation
    from golden_set.cli import main as cli_main
    from golden_set.domain.store import write_chunks

    os.environ.update(
        GOLDEN_LLM_BASE_URL="http://llm.test/v1",
        GOLDEN_LLM_MODEL="qwen-test",
        GOLDEN_EMBED_BASE_URL="http://emb.test/v1",
        GOLDEN_EMBED_MODEL="bge-test",
    )
    generation.get_generator = fake_ragas_factory()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        write_chunks(law_chunks(CHUNKS), "chunks.jsonl")
        args = ["generate", "chunks.jsonl", "--generator", "ragas", "--size", str(SIZE), "--out", "ragas.candidates.jsonl", "--no-adapt-prompts", "--log-file", "generate.log"]
        print(f"가짜 LLM으로 돌린 예시다 (청크 {CHUNKS}개, 후보 {SIZE}개). 걸린 시간과 요청 수는 실제 서버와 다르다.")
        print("출력이 터미널이 아니라서(파일로 돌렸다) 진행은 10%마다 한 줄씩만 찍힌다.")
        print("터미널에서는 진행 줄 하나를 제자리에서 다시 그리고, 단계가 끝나면 요약 줄만 남는다.\n")
        print("$ python -m golden_set.cli " + " ".join(args))
        sys.stdout.flush()
        code = cli_main(args)
        print(f"\n(종료 코드 {code})\n")
        print("$ cat generate.log")
        print(Path("generate.log").read_text(encoding="utf-8"), end="")
    return code


if __name__ == "__main__":
    sys.exit(main())
