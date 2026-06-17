"""Background workers so the UI stays responsive."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

from market_watch.data.ingest import DataIngestor
from market_watch.scoring.engine import ScoringEngine


class WorkerSignals(QObject):
    progress = Signal(str)
    finished = Signal(object)
    error = Signal(str)


class _TaskRunner(QThread):
    def __init__(
        self,
        fn: Callable[[Callable[[str], None]], object],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._fn = fn
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self._fn(self.signals.progress.emit)
            self.signals.finished.emit(result)
        except Exception as exc:
            self.signals.error.emit(str(exc))


def run_refresh_all(ingestor: DataIngestor, universe_limit: int) -> _TaskRunner:
    def task(progress: Callable[[str], None]) -> str:
        ingestor.refresh_all(progress=progress, universe_limit=universe_limit)
        return "Data refresh complete."

    return _TaskRunner(task)


def run_screen(engine: ScoringEngine, min_market_cap: float) -> _TaskRunner:
    def task(progress: Callable[[str], None]) -> object:
        progress("Computing factor scores…")
        return engine.run_and_save(min_market_cap=min_market_cap)

    return _TaskRunner(task)

