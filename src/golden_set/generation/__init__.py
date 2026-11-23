"""③ 생성: 청크 → 골든 후보. 생성기는 모두 Generator 프로토콜을 지키고 list[GoldenCandidate]를 낸다.

구체 생성기(generation.ragas, generation.deepeval)는 해당 패키지가 있을 때만 import한다 (generate extra).
"""

from golden_set.generation.generator import GenerateError, GenerateReport, Generator, get_generator

__all__ = ["GenerateError", "GenerateReport", "Generator", "get_generator"]
