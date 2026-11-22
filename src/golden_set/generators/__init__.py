"""골든 후보 생성기. 모두 Generator 프로토콜을 지키고 list[GoldenCandidate]를 낸다.

구체 생성기(ragas_gen, deepeval_gen)는 해당 패키지가 있을 때만 import한다 (generate extra).
"""

from golden_set.generators.base import GenerateError, GenerateReport, Generator, get_generator

__all__ = ["GenerateError", "GenerateReport", "Generator", "get_generator"]
