""".doc 로더: 내용이 RTF인 파일만 읽는다. 바이너리(OLE) .doc는 지원하지 않는다."""

import re

from langchain_core.documents import Document

from golden_set.loaders.base import LoadError, UnsupportedError, make_doc

# 본문이 아닌 그룹. 글꼴표, 색상표, 스타일, 문서 정보, 그림, 머리글과 바닥글이다.
_SKIP_DESTINATIONS = frozenset(
    {"fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "themedata", "datastore"}
    | {"header", "headerl", "headerr", "headerf", "footer", "footerl", "footerr", "footerf"}
)
_BREAKS = {"par": "\n", "line": "\n", "sect": "\n", "page": "\n", "row": "\n", "tab": "\t", "cell": "\t"}
_TOKEN = re.compile(
    rb"\\([a-zA-Z]+)(-?\d+)? ?"  # 제어어: \par, \u48152, \bin8852
    rb"|\\'([0-9a-fA-F]{2})"  # 코드페이지 바이트: \'b0
    rb"|\\([^a-zA-Z'])"  # 제어 기호: \{ \} \\ \~ \*
    rb"|([{}])"
    rb"|([^\\{}]+)"  # 일반 글자
)


def rtf_to_text(data: bytes) -> str:
    """RTF 바이트에서 본문 글자만 뽑는다. 머리글, 바닥글, 그림은 버린다."""
    out: list[str] = []
    pending = bytearray()  # \'hh로 온 코드페이지 바이트. 한글은 두 바이트라 모아서 푼다
    codepage = "cp1252"
    stack: list[tuple[bool, int, bool]] = []  # (건너뛰는 중인가, \uc 값, 각주 그룹인가)
    skip, uc, footnote = False, 1, False
    to_skip = 0  # \u 뒤에 따라오는 대체 글자 수
    group_start = False
    star = False

    def flush() -> None:
        if pending:
            out.append(pending.decode(codepage, errors="replace"))
            pending.clear()

    pos, n = 0, len(data)
    while pos < n:
        m = _TOKEN.match(data, pos)
        if m is None:  # 짝이 없는 역슬래시 등
            pos += 1
            continue
        pos = m.end()
        word, param, hexbyte, symbol, brace, text = m.groups()
        at_group_start, group_start = group_start, False

        if brace == b"{":
            stack.append((skip, uc, footnote))
            footnote = False
            group_start, star = True, False
        elif brace == b"}":
            flush()
            if footnote and not skip:
                out.append("\n")
            if stack:
                skip, uc, footnote = stack.pop()
        elif word is not None:
            name = word.decode("ascii")
            value = int(param) if param else None
            if name == "bin":  # 뒤따르는 N바이트는 날것의 이진 데이터다
                pos += value or 0
            elif at_group_start and (name in _SKIP_DESTINATIONS or star):
                skip = True
            elif at_group_start and name == "footnote":  # 각주는 남기되 본문과 줄바꿈으로 나눈다
                footnote = True
                if not skip:
                    flush()
                    out.append("\n")
            elif name == "ansicpg" and value:
                codepage = f"cp{value}"
            elif name == "uc" and value is not None:
                uc = value
            elif skip:
                pass
            elif name == "u" and value is not None:
                flush()
                out.append(chr(value % 65536))
                to_skip = uc
            elif name in _BREAKS:
                flush()
                out.append(_BREAKS[name])
            if at_group_start and star and name not in _SKIP_DESTINATIONS:
                skip = True
            star = False
        elif symbol is not None:
            if symbol == b"*" and at_group_start:
                star, group_start = True, True
            elif skip or symbol in b"\r\n":
                pass
            elif symbol in b"{}\\":
                flush()
                out.append(symbol.decode("ascii"))
            elif symbol == b"~":
                flush()
                out.append("\u00a0")
        elif hexbyte is not None:
            if to_skip:
                to_skip -= 1
            elif not skip:
                pending.append(int(hexbyte, 16))
        elif text is not None and not skip:
            chunk = text.replace(b"\r", b"").replace(b"\n", b"")
            if to_skip:
                chunk, to_skip = chunk[to_skip:], max(0, to_skip - len(chunk))
            if chunk:
                flush()
                out.append(chunk.decode(codepage, errors="replace"))
    flush()
    return _fix_surrogates("".join(out))


_SURROGATE_PAIR = re.compile("[\ud800-\udbff][\udc00-\udfff]")
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _fix_surrogates(text: str) -> str:
    """\\u로 따로 온 서로게이트 쌍을 한 글자로 합치고, 짝이 없는 것은 U+FFFD로 바꾼다."""
    text = _SURROGATE_PAIR.sub(
        lambda m: m.group().encode("utf-16", "surrogatepass").decode("utf-16"), text
    )
    return _LONE_SURROGATE.sub("\ufffd", text)


class RtfDocLoader:
    """.doc 확장자지만 내용이 RTF인 파일을 Document 하나로 읽는다 (법제처 내려받기 파일 등)."""

    name = "rtf"
    extensions = (".doc", ".rtf")

    def load(self, path: str) -> list[Document]:
        """RTF 내용을 Document 하나로 읽는다. RTF가 아니면 UnsupportedError("unsupported")."""
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            raise LoadError(f"cannot read file: {e}") from e
        if not data.lstrip().startswith(b"{\\rtf"):
            raise UnsupportedError("unsupported")
        try:
            text = rtf_to_text(data)
        except Exception as e:
            raise LoadError(f"{self.name}: {type(e).__name__}: {e}") from e
        return [make_doc(text, path, self.name)]
