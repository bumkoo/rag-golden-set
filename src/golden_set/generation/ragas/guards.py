"""실패 보호: 변환이나 샘플 하나가 실패해도 전체를 멈추지 않고 리포트에 적는다."""

from ragas.dataset_schema import SingleTurnSample
from ragas.testset.graph import KnowledgeGraph
from ragas.testset.transforms.base import BaseGraphTransformation

from golden_set.generation.generator import GenerateReport

FAILED_SAMPLE_STYLE = "FAILED"  # 생성에 실패한 자리에 넣는 빈 샘플의 표시


class GuardedTransform(BaseGraphTransformation):
    """변환 하나를 감싼다. 노드 하나의 추출이 실패해도 전체를 멈추지 않고 리포트에 적는다.

    실패한 노드는 그 속성이 비어 다음 단계에서 자연히 빠진다 (관계 빌더의 filter_nodes 참고).
    """

    def __init__(self, inner, report: GenerateReport):
        self.inner = inner
        self.report = report
        self.name = f"Guarded[{inner.__class__.__name__}]"
        self.filter_nodes = getattr(inner, "filter_nodes", lambda node: True)

    async def transform(self, kg: KnowledgeGraph):
        return await self.inner.transform(kg)

    def generate_execution_plan(self, kg: KnowledgeGraph):
        return [self._guard(coro) for coro in self.inner.generate_execution_plan(kg)]

    async def _guard(self, coro):
        try:
            return await coro
        except Exception as e:
            self.report.skip(f"transform {self.inner.__class__.__name__}: {type(e).__name__}: {e}")
            return None


class GuardedSynthesizer:
    """질문 합성기를 감싼다. 샘플 하나가 실패하면 빈 샘플을 돌려주고 사유를 리포트에 적는다."""

    def __init__(self, inner, report: GenerateReport):
        self.inner = inner
        self.report = report

    @property
    def name(self) -> str:
        return self.inner.name

    async def generate_scenarios(self, n: int, knowledge_graph, persona_list, callbacks=None):
        try:
            return await self.inner.generate_scenarios(n=n, knowledge_graph=knowledge_graph, persona_list=persona_list, callbacks=callbacks)
        except Exception as e:
            self.report.skip(f"{self.inner.name} scenarios (n={n}): {type(e).__name__}: {e}")
            return []

    async def generate_sample(self, scenario, callbacks=None) -> SingleTurnSample:
        try:
            return await self.inner.generate_sample(scenario=scenario, callbacks=callbacks)
        except Exception as e:
            self.report.skip(f"{self.inner.name} sample: {type(e).__name__}: {e}")
            return SingleTurnSample(user_input="", reference="", reference_contexts=[], query_style=FAILED_SAMPLE_STYLE)
