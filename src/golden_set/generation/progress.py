"""진행 보고: 생성기가 지금 어느 단계인지와 단계별 결과를 알리는 약속과 그 구현.

생성기는 단계가 시작할 때, 한 칸 나아갈 때, 끝날 때 ProgressReporter를 부른다. 화면에 어떻게 보일지는
reporter가 정한다. 단계 번호, 걸린 시간, 단계별 요청 수 같은 공통 계산은 Stages가 맡는다.
"""

import sys
import threading
import time
import unicodedata
from typing import Protocol, TextIO, runtime_checkable

from golden_set.generation.llm.client import CallLog

# 단계 이름. 순서가 곧 단계 번호다.
RAGAS_STAGES = ("요약", "임베딩·주제·개체명", "관계", "질문자", "시나리오", "질문·정답")
DEEPEVAL_STAGES = ("context 구성", "질문 생성")

NAME_WIDTH = 20  # 요약 줄에서 단계 이름이 차지하는 화면 폭
ABORTED = "중단"  # 단계가 끝나기 전에 예외로 멈췄을 때의 요약


@runtime_checkable
class ProgressReporter(Protocol):
    """진행 보고의 약속. total이 None이면 셀 단위가 없는 단계다."""

    def stage_started(self, index: int, total_stages: int, name: str, total: int | None) -> None: ...

    def advanced(self, n: int = 1) -> None: ...

    def stage_finished(self, summary: str) -> None: ...


# ---- 글자 다루기 ----


def format_duration(seconds: float) -> str:
    """걸린 시간을 "3분 39초"처럼 쓴다. 1분 미만은 "39초"."""
    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}시간 {minutes}분 {secs:02d}초"
    if minutes:
        return f"{minutes}분 {secs:02d}초"
    return f"{secs}초"


def display_width(text: str) -> int:
    """터미널에서 차지하는 칸 수. 한글처럼 넓은 글자는 두 칸이다."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def stage_line(index: int, total_stages: int, name: str, text: str) -> str:
    return f"[{index}/{total_stages}] {pad(name, NAME_WIDTH)}  {text}".rstrip()


# ---- 구현 ----


class ConsoleReporter:
    """화면용. 터미널이면 진행 줄을 제자리에서 다시 그리고, 아니면 10%마다 한 줄씩만 찍는다.

    단계가 끝나면 한 줄 요약을 찍는다. log를 주면 요약 줄과 line()으로 찍은 줄을 그 파일에도 쓴다.
    진행 줄은 파일에 쓰지 않는다.
    """

    def __init__(self, stream: TextIO | None = None, log: TextIO | None = None, tty: bool | None = None, step_percent: int = 10):
        self._stream = stream
        self.log = log
        self._tty = tty
        self.step_percent = step_percent
        self._lock = threading.Lock()
        self._index = self._total_stages = 0
        self._name = ""
        self._total: int | None = None
        self._done = 0
        self._last_step = 0
        self._started_at = 0.0
        self._drawn = False

    @property
    def stream(self) -> TextIO:
        return self._stream if self._stream is not None else sys.stdout  # 부를 때의 stdout (테스트의 capsys 포함)

    @property
    def tty(self) -> bool:
        if self._tty is not None:
            return self._tty
        isatty = getattr(self.stream, "isatty", None)
        return bool(isatty and isatty())

    def _write(self, text: str) -> None:
        self.stream.write(text)
        self.stream.flush()

    def _erase(self) -> None:
        if self._drawn:
            self._write("\r\033[K")
            self._drawn = False

    def stage_started(self, index: int, total_stages: int, name: str, total: int | None) -> None:
        with self._lock:
            self._index, self._total_stages, self._name, self._total = index, total_stages, name, total
            self._done = self._last_step = 0
            self._started_at = time.monotonic()
            if self.tty:
                self._draw()

    def _draw(self) -> None:
        elapsed = format_duration(time.monotonic() - self._started_at)
        if self._total:
            text = f"{self._done}/{self._total}  {100 * self._done // self._total}%  {elapsed}"
        else:
            text = f"진행 중  {elapsed}"
        self._write("\r\033[K" + stage_line(self._index, self._total_stages, self._name, text))
        self._drawn = True

    def advanced(self, n: int = 1) -> None:
        with self._lock:
            self._done += n
            if self.tty:
                self._draw()
                return
            if not self._total:
                return
            percent = 100 * self._done // self._total
            step = percent // self.step_percent
            if step > self._last_step and self._done < self._total:  # 100%는 요약 줄이 대신한다
                self._last_step = step
                self._write(stage_line(self._index, self._total_stages, self._name, f"{self._done}/{self._total}  {percent}%") + "\n")

    def stage_finished(self, summary: str) -> None:
        with self._lock:
            self._erase()
            self._emit(stage_line(self._index, self._total_stages, self._name, summary))

    def line(self, text: str) -> None:
        """단계 밖의 줄(마지막 리포트 등)을 화면과 로그 파일에 같이 쓴다."""
        with self._lock:
            self._erase()
            self._emit(text)

    def _emit(self, text: str) -> None:
        self._write(text + "\n")
        if self.log is not None:
            self.log.write(text + "\n")
            self.log.flush()


class ListReporter:
    """테스트용. 받은 호출을 순서대로 events에 모은다."""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def stage_started(self, index: int, total_stages: int, name: str, total: int | None) -> None:
        self.events.append(("started", index, total_stages, name, total))

    def advanced(self, n: int = 1) -> None:
        self.events.append(("advanced", n))

    def stage_finished(self, summary: str) -> None:
        self.events.append(("finished", summary))

    @property
    def stages(self) -> list[tuple[int, int, str, int | None]]:
        return [e[1:] for e in self.events if e[0] == "started"]

    @property
    def summaries(self) -> list[str]:
        return [e[1] for e in self.events if e[0] == "finished"]

    def advanced_in(self, name: str) -> int:
        """그 단계 안에서 나아간 칸 수의 합."""
        total, inside = 0, False
        for e in self.events:
            if e[0] == "started":
                inside = e[3] == name
            elif e[0] == "advanced" and inside:
                total += e[1]
        return total


# ---- 단계 진행 ----


class Stages:
    """정해진 순서의 단계를 하나씩 연다. 단계 번호, 걸린 시간, 그 단계의 요청 수와 실패 수를 대신 챙긴다.

    요청 수는 CallLog를 단계 시작과 끝에 읽어 그 차이로 구한다. 항목 실패 수는 skipped 목록의 길이 차이다.
    """

    def __init__(self, reporter: ProgressReporter, names: tuple[str, ...], llm: CallLog | None = None, embed: CallLog | None = None, skipped: list | None = None):
        self.reporter = reporter
        self.names = names
        self.llm = llm
        self.embed = embed
        self.skipped = skipped if skipped is not None else []
        self.index = 0  # 지금까지 연 단계 수
        self.open = False
        self._t0 = 0.0
        self._llm0 = self._llm_failed0 = self._embed0 = self._skipped0 = 0

    def start(self, name: str, total: int | None = None) -> None:
        if self.open:
            raise RuntimeError(f"stage {self.names[self.index - 1]!r} is still open")
        if self.index >= len(self.names) or self.names[self.index] != name:
            raise RuntimeError(f"stage {name!r} out of order (expected {self.names[self.index] if self.index < len(self.names) else 'no more stages'!r})")
        self.index += 1
        self.open = True
        self._t0 = time.monotonic()
        self._llm0 = self.llm.requests if self.llm else 0
        self._llm_failed0 = len(self.llm.failures) if self.llm else 0
        self._embed0 = self.embed.requests if self.embed else 0
        self._skipped0 = len(self.skipped)
        self.reporter.stage_started(self.index, len(self.names), name, total)

    def advance(self, n: int = 1) -> None:
        if self.open:
            self.reporter.advanced(n)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    @property
    def llm_requests(self) -> int:
        return (self.llm.requests if self.llm else 0) - self._llm0

    @property
    def embed_requests(self) -> int:
        return (self.embed.requests if self.embed else 0) - self._embed0

    @property
    def new_skips(self) -> list:
        """이 단계에서 건너뛴 항목의 사유들."""
        return self.skipped[self._skipped0 :]

    @property
    def failed_items(self) -> int:
        return len(self.new_skips)

    def calls_text(self) -> str:
        """이 단계에서 보낸 요청 수. 요청이 없으면 빈 문자열."""
        parts: list[str] = []
        if self.llm_requests:
            failed = (len(self.llm.failures) if self.llm else 0) - self._llm_failed0
            parts.append(f"LLM {self.llm_requests}회" + (f"(요청 실패 {failed})" if failed else ""))
        if self.embed_requests:
            parts.append(f"임베딩 {self.embed_requests}회")
        return "  ".join(parts)

    def finish(self, head: str, *, timed: bool = True, failed: int | None = None, tail: str = "") -> None:
        """단계를 닫고 요약 한 줄을 보낸다: head, 걸린 시간, 요청 수, 실패 수, tail 순서다."""
        if not self.open:
            return
        parts = [head]
        if timed:
            parts.append(format_duration(self.elapsed))
        parts.append(self.calls_text())
        if failed is not None:
            parts.append(f"실패 {failed}")
        parts.append(tail)
        self.open = False
        self.reporter.stage_finished("  ".join(p for p in parts if p))

    def abort(self) -> None:
        """예외로 멈췄을 때 열려 있는 단계를 닫는다."""
        if self.open:
            self.open = False
            self.reporter.stage_finished(ABORTED)
