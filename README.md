# golden_set

pdf, pptx, docx, txt 문서를 같은 형태의 `list[Document]`로 읽고, 로더의 추출 품질을 숫자로 검증하는 패키지다.
출력은 다음 단계인 Ragas 골든셋 생성의 입력이 된다.

## 설치

```bash
uv venv && uv pip install -e ".[dev,compare]"
```

`compare` extra는 비교용 대안 로더(python-docx, pdfplumber, unstructured)를 설치한다. 기본 로더만 쓸 때는 빼도 된다.

## 사용

```python
from golden_set import load_path, load_dir

docs = load_path("문서.pdf")                 # 기본 로더(pymupdf)
docs = load_path("문서.pdf", "pdfplumber")   # 이름으로 로더 지정
docs, failures = load_dir("문서폴더")         # 하위 폴더까지, 실패는 Failure(path, reason)로 수집
```

```bash
python -m golden_set.cli validate <폴더> [--out report.csv] [--samples N]
python -m golden_set.cli compare <파일> [--samples N]
```

종료 코드: 불합격(`fail`)이나 읽기 실패(`error`)가 하나라도 있으면 1, 폴더나 파일이 없으면 2, 그 외 0.
지원하지 않는 확장자(`unsupported`)는 표에 보고만 하고 종료 코드에는 넣지 않는다.

## 테스트

```bash
pytest
```

픽스처 파일은 테스트가 직접 만든다. 같은 파일을 디스크에 깔아 보려면 `python tests/make_fixtures.py`를 실행한다 (`tests/fixtures/`, git에는 넣지 않는다).

## 출력 예시: validate

`python tests/make_fixtures.py && python -m golden_set.cli validate tests/fixtures` (종료 코드 1)

```text
loader       status       doc_count  empty_ratio  avg_chars  broken_ratio  hangul_ratio  meta_ok  elapsed_sec  path  (reasons)
pymupdf      error                                                                                             tests/fixtures/broken.pdf  (pymupdf: EmptyFileError: Cannot open empty file: filename='tests/fixtures/broken.pdf'.)
stdlib       pass         1          0.000        96.0       0.0000        0.526         True     0.000        tests/fixtures/ko_cp949.txt
stdlib       pass         1          0.000        96.0       0.0000        0.526         True     0.000        tests/fixtures/ko_utf8.txt
-            unsupported                                                                                       tests/fixtures/old.doc  (unsupported)
-            unsupported                                                                                       tests/fixtures/sheet.xlsx  (unsupported)
python-pptx  pass         2          0.000        93.5       0.0000        0.630         True     0.075        tests/fixtures/sub/two_slides.pptx
pymupdf      fail         4          0.500        33.8       0.0000        0.396         True     0.009        tests/fixtures/sub/with_blank.pdf  (empty_ratio 50.0% > 30.0%; avg_chars 33.8 < 50)
pymupdf      pass         3          0.000        67.7       0.0000        0.406         True     0.001        tests/fixtures/three_pages.pdf
docx2txt     pass         1          0.000        73.0       0.0000        0.373         True     0.002        tests/fixtures/two_paragraphs.docx

pass=5  fail=1  error=1  unsupported=2
```
