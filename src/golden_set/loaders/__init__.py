"""형식별 로더."""

from golden_set.loaders.base import LoadError, Loader, UnsupportedError
from golden_set.loaders.docx import Docx2txtLoader
from golden_set.loaders.pdf import PyMuPDFLoader
from golden_set.loaders.pptx import PythonPptxLoader
from golden_set.loaders.txt import TxtLoader

__all__ = [
    "Docx2txtLoader",
    "LoadError",
    "Loader",
    "PyMuPDFLoader",
    "PythonPptxLoader",
    "TxtLoader",
    "UnsupportedError",
]
