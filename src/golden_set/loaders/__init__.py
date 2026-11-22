"""형식별 로더."""

from golden_set.loaders.base import LoadError, Loader, UnsupportedError
from golden_set.loaders.doc import RtfDocLoader
from golden_set.loaders.docx import Docx2txtLoader, PythonDocxLoader
from golden_set.loaders.pdf import PdfplumberLoader, PyMuPDFLoader
from golden_set.loaders.pptx import PythonPptxLoader, UnstructuredPptxLoader
from golden_set.loaders.txt import TxtLoader

__all__ = [
    "Docx2txtLoader",
    "LoadError",
    "Loader",
    "PdfplumberLoader",
    "PyMuPDFLoader",
    "PythonDocxLoader",
    "PythonPptxLoader",
    "RtfDocLoader",
    "TxtLoader",
    "UnstructuredPptxLoader",
    "UnsupportedError",
]
