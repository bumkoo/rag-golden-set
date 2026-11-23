"""실패 보호: 변환이나 샘플 하나가 실패해도 전체를 멈추지 않고 리포트에 적는다.

감싼 것이 얼마나 진행됐는지도 여기서 센다. 진행 보고는 on_plan, on_step, events로 밖에 알린다.
"""

from collections import Counter
from typing import Callable, Protocol

from ragas.dataset_schema import SingleTurnSample
from ragas.testset.graph import KnowledgeGraph
from ragas.testset.transforms.base import BaseGraphTransformation

from golden_set.generation.generator import GenerateReport

FAILED_SAMPLE_STYLE = "FAILED"  # 생성에 실패한 자리에 넣는 빈 샘플의 표시


class GuardedTransform(BaseGraphTransformation):
    """변환 하나를 감싼다. 노드 하나의 추출이 실패해도 전체를 멈추지 않고 리포트에 적는다.

    실패한 노드는 그 속성이 비어 다음 단계에서 자연히 빠진다 (관계 빌더의 filter_nodes 참고).
    done과 failed에는 작업 종류(감싼 변환의 클래스 이름)별로 끝난 수와 실패한 수가 쌓인다.
    """

    def __init__(self, inner, report: GenerateReport, on_plan: Callable[[int], None] | None = None, on_step: Callable[[], None] | None = None):
        self.inner = inner
        self.report = report
        self.name = f"Guarded[{inner.__class__.__name__}]"
        self.filter_nodes = getattr(inner, "filter_nodes", lambda node: True)
        self.on_plan = on_plan  # 실행할 작업 수가 정해졌을 때
        self.on_step = on_step  # 작업 하나가 끝났을 때 (성공이든 실패든)
        self.done: Counter = Counter()
        self.failed: Counter = Counter()

    @property
    def parts(self) -> list:
        """감싼 변환들. Parallel이면 그 안의 변환 각각이다."""
        return list(getattr(self.inner, "transformations", None) or [self.inner])

    async def transform(self, kg: KnowledgeGraph):
        return await self.inner.transform(kg)

    def generate_execution_plan(self, kg: KnowledgeGraph):
        plan = [self._guard(coro, part.__class__.__name__) for part in self.parts for coro in part.generate_execution_plan(kg)]
        if self.on_plan is not None:
            self.on_plan(len(plan))
        return plan

    async def _guard(self, coro, kind: str):
        try:
            result = await coro
        except Exception as e:
            self.failed[kind] += 1
            self.report.skip(f"transform {self.inner.__class__.__name__}: {type(e).__name__}: {e}")
            return None
        else:
            self.done[kind] += 1
            return result
        finally:
            if self.on_step is not None:
                self.on_step()


class SynthesisEvents(Protocol):
    """합성기가 어디까지 왔는지 받는 쪽."""

    def scenarios_done(self, synthesizer_name: str, count: int) -> None: ...

    def sample_started(self) -> None: ...

    def sample_finished(self) -> None: ...


class GuardedSynthesizer:
    """질문 합성기를 감싼다. 샘플 하나가 실패하면 빈 샘플을 돌려주고 사유를 리포트에 적는다."""

    def __init__(self, inner, report: GenerateReport, events: SynthesisEvents | None = None):
        self.inner = inner
        self.report = report
        self.events = events

    @property
    def name(self) -> str:
        return self.inner.name

    async def generate_scenarios(self, n: int, knowledge_graph, persona_list, callbacks=None):
        try:
            scenarios = await self.inner.generate_scenarios(n=n, knowledge_graph=knowledge_graph, persona_list=persona_list, callbacks=callbacks)
        except Exception as e:
            self.report.skip(f"{self.inner.name} scenarios (n={n}): {type(e).__name__}: {e}")
            scenarios = []
        if self.events is not None:
            self.events.scenarios_done(self.inner.name, len(scenarios))
        return scenarios

    async def generate_sample(self, scenario, callbacks=None) -> SingleTurnSample:
        if self.events is not None:
            self.events.sample_started()
        try:
            return await self.inner.generate_sample(scenario=scenario, callbacks=callbacks)
        except Exception as e:
            self.report.skip(f"{self.inner.name} sample: {type(e).__name__}: {e}")
            return SingleTurnSample(user_input="", reference="", reference_contexts=[], query_style=FAILED_SAMPLE_STYLE)
        finally:
            if self.events is not None:
                self.events.sample_finished()
