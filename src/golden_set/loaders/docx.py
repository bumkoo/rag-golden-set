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
