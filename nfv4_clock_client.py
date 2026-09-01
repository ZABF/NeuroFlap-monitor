from collections import OrderedDict
import threading
import time

from network_clock import AffineClockEstimator
from nfv4_codec import NFv4Codec


class NFv4ClockClient:
    """Monitor-initiated NFv4 four-timestamp synchronization client."""

    BASELINE_INTERVAL_US = 100_000
    LOADED_INTERVAL_US = 50_000
    RESPONSE_TIMEOUT_US = 6_000_000
    OUTSTANDING_LIMIT = 64

    def __init__(self, estimator=None, codec=None):
        self.estimator = estimator or AffineClockEstimator()
        self.codec = codec or NFv4Codec()
        self._lock = threading.RLock()
        self._session_id = 0
        self._sequence = 0
        self._next_baseline_send_us = 0
        self._next_loaded_send_us = 0
        self._last_response_us = 0
        self._last_baseline_response_us = 0
        self._outstanding = OrderedDict()
        self._last_measurement = None
        self._reset_diagnostics_locked()

    def _reset_diagnostics_locked(self):
        self._requests_due = 0
        self._requests_sent = 0
        self._request_send_failures = 0
        self._responses_seen = 0
        self._responses_matched = 0
        self._response_parse_failures = 0
        self._response_session_mismatches = 0
        self._response_unknown_sequences = 0
        self._response_context_mismatches = 0
        self._requests_expired = 0
        self._samples_accepted = 0
        self._samples_rejected = 0
        self._loaded_responses = 0
        self._last_send_us = 0
        self._last_failure = ""

    def start_session(self, session_id):
        with self._lock:
            self.estimator.reset("NFv4 session started")
            self._session_id = int(session_id) & 0xFFFFFFFF
            self._sequence = 0
            self._next_baseline_send_us = 0
            self._next_loaded_send_us = 0
            self._last_response_us = 0
            self._last_baseline_response_us = 0
            self._outstanding.clear()
            self._last_measurement = None
            self._reset_diagnostics_locked()

    def stop_session(self):
        with self._lock:
            self.estimator.reset("NFv4 session stopped")
            self._session_id = 0
            self._next_baseline_send_us = 0
            self._next_loaded_send_us = 0
            self._last_response_us = 0
            self._last_baseline_response_us = 0
            self._outstanding.clear()
            self._last_measurement = None
            self._reset_diagnostics_locked()

    @property
    def active(self):
        with self._lock:
            return self._session_id != 0

    @property
    def last_response_us(self):
        with self._lock:
            return self._last_response_us

    def response_timed_out(self, now_us=None):
        now_us = int(now_us or time.monotonic_ns() // 1000)
        with self._lock:
            reference_us = self._last_baseline_response_us or self._last_send_us
            return (
                self._session_id != 0
                and reference_us > 0
                and now_us - reference_us >= self.RESPONSE_TIMEOUT_US
            )

    def _prune_expired_locked(self, now_us):
        cutoff_us = int(now_us) - self.RESPONSE_TIMEOUT_US
        expired = [
            sequence
            for sequence, pending in self._outstanding.items()
            if pending[0] <= cutoff_us
        ]
        for sequence in expired:
            self._outstanding.pop(sequence, None)
        self._requests_expired += len(expired)

    def take_measurement(self):
        with self._lock:
            measurement = self._last_measurement
            self._last_measurement = None
            return measurement

    def diagnostics(self, now_us=None):
        now_us = int(now_us or time.monotonic_ns() // 1000)
        with self._lock:
            age_ms = lambda timestamp: (
                None
                if timestamp <= 0
                else max(0.0, (now_us - timestamp) / 1000.0)
            )
            return {
                "active": self._session_id != 0,
                "session_id": self._session_id,
                "requests_due": self._requests_due,
                "requests_sent": self._requests_sent,
                "request_send_failures": self._request_send_failures,
                "responses_seen": self._responses_seen,
                "responses_matched": self._responses_matched,
                "response_parse_failures": self._response_parse_failures,
                "response_session_mismatches": self._response_session_mismatches,
                "response_unknown_sequences": self._response_unknown_sequences,
                "response_context_mismatches": self._response_context_mismatches,
                "requests_expired": self._requests_expired,
                "samples_accepted": self._samples_accepted,
                "samples_rejected": self._samples_rejected,
                "loaded_responses": self._loaded_responses,
                "outstanding": len(self._outstanding),
                "last_send_age_ms": age_ms(self._last_send_us),
                "last_response_age_ms": age_ms(self._last_response_us),
                "last_baseline_response_age_ms": age_ms(
                    self._last_baseline_response_us
                ),
                "last_failure": self._last_failure,
            }

    def tick(self, send_packet, now_us=None, context=0, stage=0, flags=0):
        now_us = int(now_us or time.monotonic_ns() // 1000)
        context = int(context) & 0xFFFFFFFF
        baseline = context == 0
        with self._lock:
            self._prune_expired_locked(now_us)
            next_send_us = (
                self._next_baseline_send_us
                if baseline
                else self._next_loaded_send_us
            )
            if self._session_id == 0 or now_us < next_send_us:
                return False
            interval_us = (
                self.BASELINE_INTERVAL_US if baseline else self.LOADED_INTERVAL_US
            )
            self._sequence = (self._sequence + 1) & 0xFFFFFFFF
            sequence = self._sequence
            session_id = self._session_id
            if baseline:
                self._next_baseline_send_us = now_us + interval_us
            else:
                self._next_loaded_send_us = now_us + interval_us
            self._requests_due += 1

        packet = self.codec.build_sync_request(
            session_id,
            sequence,
            context=context,
            stage=stage,
            flags=flags,
        )
        t1_us = send_packet(packet)
        if not t1_us:
            with self._lock:
                self._request_send_failures += 1
                self._last_failure = "sync request send failed"
            return False

        with self._lock:
            if session_id != self._session_id:
                self._request_send_failures += 1
                self._last_failure = "session changed while sending request"
                return False
            self._requests_sent += 1
            self._last_send_us = int(t1_us)
            self._outstanding[sequence] = (
                int(t1_us),
                context,
                int(stage) & 0xFF,
            )
            while len(self._outstanding) > self.OUTSTANDING_LIMIT:
                self._outstanding.popitem(last=False)
        return True

    def handle_response(self, data, t4_us=None):
        t4_us = int(t4_us or time.monotonic_ns() // 1000)
        with self._lock:
            self._responses_seen += 1
        packet = self.codec.parse_sync_response(data)
        if packet is None:
            with self._lock:
                self._response_parse_failures += 1
                self._last_failure = "invalid sync response"
            return False
        with self._lock:
            self._prune_expired_locked(t4_us)
            if packet["session_id"] != self._session_id:
                self._response_session_mismatches += 1
                self._last_failure = "sync response session mismatch"
                return False
            pending = self._outstanding.pop(packet["sequence"], None)
            if pending is None:
                self._response_unknown_sequences += 1
                self._last_failure = "sync response sequence not outstanding"
                return False
            t1_us, context, stage = pending
            if (
                packet["context"] != context
                or packet["stage"] != stage
            ):
                self._response_context_mismatches += 1
                self._last_failure = "sync response context mismatch"
                return False
            self._last_response_us = t4_us
            if context == 0:
                self._last_baseline_response_us = t4_us
            self._responses_matched += 1
            self._last_failure = ""

        rtt_us = max(
            0,
            (t4_us - t1_us) - (packet["t3_us"] - packet["t2_us"]),
        )
        # Loaded diagnostic samples are valid path measurements but must not
        # move the baseline clock model.
        if context == 0:
            accepted = self.estimator.add_monitor_initiated(
                t1_us,
                packet["t2_us"],
                packet["t3_us"],
                t4_us,
            )
        else:
            accepted = True
        sample_result = (
            self.estimator.last_sample_result if context == 0 else "rtt_only"
        )
        with self._lock:
            if context != 0:
                self._loaded_responses += 1
            elif accepted:
                self._samples_accepted += 1
            else:
                self._samples_rejected += 1

        transform = self.estimator.transform
        download_value = transform.map_us(packet["t2_us"]) - t1_us
        upload_value = t4_us - transform.map_us(packet["t3_us"])
        one_way_valid = (
            transform.usable
            and transform.epoch == self.estimator.epoch
            and transform.uncertainty_us
            <= self.estimator.MAX_MODEL_UNCERTAINTY_US
            and download_value >= -2.0
            and upload_value >= -2.0
            and abs((download_value + upload_value) - rtt_us) <= 2.0
        )
        download_us = max(0, int(download_value)) if one_way_valid else None
        upload_us = max(0, int(upload_value)) if one_way_valid else None
        with self._lock:
            self._last_measurement = {
                "context": context,
                "stage": stage,
                "t1_us": t1_us,
                "t2_us": packet["t2_us"],
                "t3_us": packet["t3_us"],
                "t4_us": t4_us,
                "upload_us": upload_us,
                "download_us": download_us,
                "rtt_us": rtt_us,
                "accepted": bool(accepted),
                "result": sample_result,
                "one_way_valid": one_way_valid,
            }
        # A matching response proves session liveness even when the clock
        # estimator rejects the sample as physically inconsistent.
        return True
