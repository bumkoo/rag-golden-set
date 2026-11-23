"""awx1 형식 어댑터: AgenticWorks 평가 데이터셋으로 올리는 JSON 배열.

    [{"id": 1, "query": "질문", "expected_response": "기대 정답"}, ...]

id는 1부터 매기는 정수다. 우리 후보 id(예: ragas-0001)와 출처는 이 형식에 자리가 없어 빠진다.
순서는 candidates.jsonl의 순서 그대로라, n번째 항목이 n번째 후보다.
"""

import json

from golden_set.domain.candidate import GoldenCandidate


def to_awx1(candidates: list[GoldenCandidate]) -> list[dict]:
    """후보 목록을 awx1 항목 목록으로 옮긴다. 질문과 정답의 앞뒤 공백은 뗀다."""
    return [{"id": n, "query": c.question.strip(), "expected_response": c.reference_answer.strip()} for n, c in enumerate(candidates, start=1)]


def write_awx1(candidates: list[GoldenCandidate], path: str) -> int:
    """awx1 JSON 파일로 저장하고 쓴 항목 수를 돌려준다. 한글은 그대로 쓴다."""
    rows = to_awx1(candidates)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return len(rows)
