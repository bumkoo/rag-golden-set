"""docx 로더: 기본 docx2txt."""

from langchain_core.documents import Document

from golden_set.loaders.base import LoadError, make_doc


class Docx2txtLoader:
    """docx2txt로 파일 전체를 Document 하나로 읽는다."""

    name = "docx2txt"
    extensions = (".docx",)

    def load(self, path: str) -> list[Document]:
        """docx 파일을 Document 하나로 읽는다."""
        try:
            import docx2txt

            text = docx2txt.process(path)
        except Exception as e:
            raise LoadError(f"{self.name}: {type(e).__name__}: {e}") from e
        return [make_doc(text or "", path, self.name)]


class PythonDocxLoader:
    """비교용 대안. python-docx로 본문의 문단과 표를 문서 순서대로 읽는다 (머리글, 바닥글 제외)."""

    name = "python-docx"
    extensions = (".docx",)

    def load(self, path: str) -> list[Document]:
        """docx 파일을 Document 하나로 읽는다."""
        try:
            import docx
            from docx.table import Table

            parts: list[str] = []
            for block in docx.Document(path).iter_inner_content():
                if isinstance(block, Table):
                    parts.extend("\t".join(cell.text for cell in row.cells) for row in block.rows)
                else:
                    parts.append(block.text)
        except Exception as e:
            raise LoadError(f"{self.name}: {type(e).__name__}: {e}") from e
        return [make_doc("\n\n".join(p for p in parts if p.strip()), path, self.name)]
