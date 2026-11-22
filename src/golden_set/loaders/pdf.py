"""pdf 로더: 기본 PyMuPDF."""

from langchain_core.documents import Document

from golden_set.loaders.base import LoadError, make_doc


class PyMuPDFLoader:
    """PyMuPDF로 페이지마다 Document 하나를 만든다. 빈 페이지도 버리지 않는다."""

    name = "pymupdf"
    extensions = (".pdf",)

    def load(self, path: str) -> list[Document]:
        """pdf 파일을 페이지별 Document 리스트로 읽는다."""
        try:
            import pymupdf

            with pymupdf.open(path) as pdf:
                if pdf.needs_pass:
                    raise LoadError("password-protected pdf")
                return [
                    make_doc(page.get_text(), path, self.name, page=i)
                    for i, page in enumerate(pdf, start=1)
                ]
        except LoadError:
            raise
        except Exception as e:
            raise LoadError(f"{self.name}: {type(e).__name__}: {e}") from e


class PdfplumberLoader:
    """비교용 대안. pdfplumber로 페이지마다 Document 하나를 만든다."""

    name = "pdfplumber"
    extensions = (".pdf",)

    def load(self, path: str) -> list[Document]:
        """pdf 파일을 페이지별 Document 리스트로 읽는다."""
        try:
            import pdfplumber

            with pdfplumber.open(path) as pdf:
                return [
                    make_doc(page.extract_text() or "", path, self.name, page=i)
                    for i, page in enumerate(pdf.pages, start=1)
                ]
        except Exception as e:
            raise LoadError(f"{self.name}: {type(e).__name__}: {e}") from e
