"""언어 판별. 한글 음절 비율로 ko와 en을 가른다."""

KO_HANGUL_RATIO = 0.3  # 글자(한글 음절 + 로마자) 중 한글 음절 비율이 이 이상이면 ko


def detect_language(text: str, ko_ratio: float = KO_HANGUL_RATIO) -> str:
    """한글 음절 비율로 ko 또는 en을 정한다. 글자가 하나도 없으면 en."""
    hangul = sum(1 for c in text if "가" <= c <= "힣")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    letters = hangul + latin
    if letters == 0:
        return "en"
    return "ko" if hangul / letters >= ko_ratio else "en"
