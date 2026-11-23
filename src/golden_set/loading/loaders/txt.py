"""txt 로더: 표준 라이브러리로 직접 읽는다."""

from langchain_core.documents import Document

from golden_set.loading.loaders.base import LoadError, make_doc

UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
ENCODINGS = ("utf-8-sig", "cp949")  # utf-8-sig는 BOM이 있으면 떼고, 없으면 utf-8과 같다


class TxtLoader:
    """utf-8(BOM 허용)로 먼저 읽고, 실패하면 cp949로 다시 읽는다. 파일 전체가 Document 하나."""

    name = "stdlib"
    extensions = (".txt",)

    def load(self, path: str) -> list[Document]:
        """txt 파일을 Document 하나로 읽는다."""
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as e:
            raise LoadError(f"cannot read file: {e}") from e
        if raw.startswith(UTF16_BOMS):  # Windows 메모장의 "유니코드". BOM이 없는 UTF-16은 추측하지 않는다
            try:
                return [make_doc(raw.decode("utf-16"), path, self.name)]
            except UnicodeDecodeError as e:
                raise LoadError(f"has UTF-16 BOM but cannot decode as utf-16: {e}") from e
        for encoding in ENCODINGS:
            try:
                text = raw.decode(encoding)
            except UnicodeDecodeError:
                continue
            return [make_doc(text, path, self.name)]
        raise LoadError(f"cannot decode as any of {ENCODINGS}")
