from dataclasses import dataclass
import queue
import threading
import time


@dataclass(frozen=True)
class DriftFitRequest:
    epoch: int
    source_watermark_us: float
    representatives: tuple
    delay_floor_us: float


@dataclass(frozen=True)
class DriftFitResult:
    epoch: int
    source_watermark_us: float
    representatives: tuple
    fit: object
    runtime_ms: float
    error: str = ""


class InlineDriftFitWorker:
    """Deterministic drift fitting for tests and offline analysis."""

    def __init__(self, solver):
        self._solver = solver
        self._results = []

    @property
    def pending(self):
        return False

    def submit(self, request):
        started = time.perf_counter()
        error = ""
        try:
            fit = self._solver(request.representatives, request.delay_floor_us)
        except Exception as exc:
            fit = None
            error = f"{type(exc).__name__}: {exc}"
        self._results.append(
            DriftFitResult(
                epoch=request.epoch,
                source_watermark_us=request.source_watermark_us,
                representatives=request.representatives,
                fit=fit,
                runtime_ms=(time.perf_counter() - started) * 1000.0,
                error=error,
            )
        )

    def poll_results(self):
        results = tuple(self._results)
        self._results.clear()
        return results

    def close(self):
        pass


class BackgroundDriftFitWorker:
    """Runs long-window fitting away from the UDP receive thread."""

    def __init__(self, solver):
        self._solver = solver
        self._requests = queue.Queue(maxsize=1)
        self._results = queue.SimpleQueue()
        self._state_lock = threading.Lock()
        self._submitted_generation = 0
        self._completed_generation = 0
        self._closed = False
        self._thread = threading.Thread(
            target=self._run,
            name="NFv4ClockDriftFit",
            daemon=True,
        )
        self._thread.start()

    @property
    def pending(self):
        with self._state_lock:
            return self._completed_generation < self._submitted_generation

    def submit(self, request):
        with self._state_lock:
            if self._closed:
                return False
            self._submitted_generation += 1
            generation = self._submitted_generation
        queued = (generation, request)
        try:
            self._requests.put_nowait(queued)
        except queue.Full:
            try:
                self._requests.get_nowait()
            except queue.Empty:
                pass
            self._requests.put_nowait(queued)
        return True

    def poll_results(self):
        results = []
        while True:
            try:
                _generation, result = self._results.get_nowait()
            except queue.Empty:
                break
            results.append(result)
        return tuple(results)

    def close(self):
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._requests.put_nowait(None)
        except queue.Full:
            try:
                self._requests.get_nowait()
            except queue.Empty:
                pass
            self._requests.put_nowait(None)
        self._thread.join(timeout=1.0)

    def _run(self):
        while True:
            queued = self._requests.get()
            if queued is None:
                return
            generation, request = queued
            started = time.perf_counter()
            error = ""
            try:
                fit = self._solver(request.representatives, request.delay_floor_us)
            except Exception as exc:
                fit = None
                error = f"{type(exc).__name__}: {exc}"
            result = DriftFitResult(
                epoch=request.epoch,
                source_watermark_us=request.source_watermark_us,
                representatives=request.representatives,
                fit=fit,
                runtime_ms=(time.perf_counter() - started) * 1000.0,
                error=error,
            )
            self._results.put((generation, result))
            with self._state_lock:
                self._completed_generation = max(
                    self._completed_generation, generation
                )
