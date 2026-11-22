"""법제처(국가법령정보센터) 법령 파일의 파싱 결과를 대조할 때 쓰는 도우미. 테스트 전용이다."""

import re

from langchain_core.documents import Document

# 줄 맨 앞의 조문 머리: 제1조(…), 제50조[…], 제52조의2(…), 제293조 삭제
ARTICLE_HEAD = re.compile(r"^\s*제(\d+)조(?:의\d+)?(?=\s*삭제|\s*[(\[])", re.M)


def squash(text: str) -> str:
    """공백을 모두 뺀다. 줄바꿈 위치는 형식과 도구마다 다르기 때문이다."""
    return re.sub(r"\s+", "", text)


def law_title(docs: list[Document]) -> str:
    """법령 이름. pdf는 머리글 다음 줄, doc은 첫 줄이다."""
    lines = [l.strip() for l in docs[0].page_content.split("\n") if l.strip()]
    return lines[1] if "법제처" in lines[0] else lines[0]


def law_body(docs: list[Document]) -> str:
    """쪽마다 반복되는 머리글("법제처 N 국가법령정보센터", 법령 이름)을 지우고 이어 붙인다."""
    title = law_title(docs)
    kept = [
        line
        for doc in docs
        for line in doc.page_content.split("\n")
        if not ("법제처" in line and "국가법령정보센터" in line) and line.strip() != title
    ]
    return "\n".join(kept)


def missing_articles(body: str) -> tuple[int, list[int]]:
    """본칙(부칙 앞)의 마지막 조 번호와, 1부터 거기까지 중 머리가 안 보이는 조 번호."""
    main = re.split(r"^\s*부칙", body, maxsplit=1, flags=re.M)[0]
    numbers = {int(m.group(1)) for m in ARTICLE_HEAD.finditer(main)}
    last = max(numbers, default=0)
    return last, [n for n in range(1, last + 1) if n not in numbers]
