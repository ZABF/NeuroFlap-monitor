from dataclasses import dataclass
from enum import Enum
import math


class ClockEstimatorStrategy(str, Enum):
    V3 = "v3"
    V4 = "v4"
    V4_V3 = "v4+v3"

    @classmethod
    def parse(cls, value):
        if isinstance(value, cls):
            return value
        normalized = str(value or "").strip().lower()
        aliases = {
            "v3": cls.V3,
            "v4": cls.V4,
            "v4+v3": cls.V4_V3,
            "hybrid": cls.V4_V3,
        }
        return aliases.get(normalized, cls.V4_V3)

    @property
    def display_name(self):
        return {
            self.V3: "V3",
            self.V4: "V4",
            self.V4_V3: "V4+V3",
        }[self]


class ClockAlignmentState(str, Enum):
    ACQUIRING = "Acquiring"
    PROVISIONAL = "Provisional"
    LOCKED = "Locked"
    DEGRADED = "Degraded"
    STALE = "Stale"


class OffsetAlignmentState(str, Enum):
    ACQUIRING = "Acquiring"
    PROVISIONAL = "Provisional"
    USABLE = "Usable"
    HOLDOVER = "Holdover"


class DriftAlignmentState(str, Enum):
    UNKNOWN = "Unknown"
    CANDIDATE = "Candidate"
    STABLE = "Stable"
    LOCKED = "Locked"
    HOLDOVER = "Holdover"


@dataclass(frozen=True)
class ClockTransform:
    source_anchor_us: float = 0.0
    target_anchor_us: float = 0.0
    drift_ppb: float = 0.0
    uncertainty_us: float = math.inf
    usable: bool = False
    locked: bool = False
    epoch: int = 1
    revision: int = 0
    updated_monotonic: float = 0.0

    def map_us(self, source_us):
        scale = 1.0 + self.drift_ppb * 1.0e-9
        return self.target_anchor_us + (
            float(source_us) - self.source_anchor_us
        ) * scale

    def map_ms(self, source_ms):
        return self.map_us(float(source_ms) * 1000.0) / 1000.0


@dataclass(frozen=True)
class ClockAlignmentSnapshot:
    strategy: ClockEstimatorStrategy = ClockEstimatorStrategy.V4
    model_name: str = "robust_affine_set_membership_v4"
    window_s: int = 300
    state: ClockAlignmentState = ClockAlignmentState.ACQUIRING
    offset_state: OffsetAlignmentState = OffsetAlignmentState.ACQUIRING
    drift_state: DriftAlignmentState = DriftAlignmentState.UNKNOWN
    source_anchor_us: float = 0.0
    target_anchor_us: float = 0.0
    offset_us: float = 0.0
    offset_lower_us: float = 0.0
    offset_upper_us: float = 0.0
    uncertainty_us: float = math.inf
    drift_ppb: float = 0.0
    candidate_drift_ppb: float = 0.0
    physical_candidate_drift_ppb: float = math.nan
    statistical_candidate_drift_ppb: float = math.nan
    statistical_drift_uncertainty_ppb: float = math.inf
    drift_lower_ppb: float = -math.inf
    drift_upper_ppb: float = math.inf
    drift_uncertainty_ppb: float = math.inf
    sample_count: int = 0
    candidate_count: int = 0
    representative_count: int = 0
    sample_span_us: float = 0.0
    representative_span_us: float = 0.0
    rejected_count: int = 0
    minimum_rtt_us: float = math.inf
    latest_rtt_us: float = math.inf
    rtt_p50_us: float = math.inf
    rtt_p95_us: float = math.inf
    delay_floor_us: float = math.inf
    strict_intersection: bool = False
    consensus_accepted: bool = False
    compatible_count: int = 0
    consensus_required_count: int = 0
    drift_fit_valid: bool = False
    drift_fit_pending: bool = False
    drift_fit_runtime_ms: float = 0.0
    drift_fit_error: str = ""
    healthy_fit_streak: int = 0
    lock_confirm_updates: int = 0
    model_age_s: float = math.inf
    holdover_age_s: float = 0.0
    reset_count: int = 0
    last_reset_reason: str = ""
    epoch: int = 1
    revision: int = 0
    updated_monotonic: float = 0.0

    @property
    def usable(self):
        return self.state in (
            ClockAlignmentState.PROVISIONAL,
            ClockAlignmentState.LOCKED,
            ClockAlignmentState.DEGRADED,
        )

    def to_metadata(self, target_epoch_offset_us=0.0, updated_unix_us=""):
        finite = lambda value: "" if not math.isfinite(value) else value
        has_samples = self.sample_count > 0
        return {
            "clock_model": self.model_name,
            "clock_estimator_strategy": self.strategy.value,
            "clock_state": self.state.value,
            "clock_offset_state": self.offset_state.value,
            "clock_drift_state": self.drift_state.value,
            "clock_epoch": self.epoch,
            "clock_source_anchor_us": (
                int(self.source_anchor_us) if has_samples else ""
            ),
            "clock_target_anchor_unix_us": (
                int(self.target_anchor_us + target_epoch_offset_us)
                if has_samples
                else ""
            ),
            "clock_offset_us": (
                finite(self.offset_us + target_epoch_offset_us) if has_samples else ""
            ),
            "clock_offset_lower_us": (
                finite(self.offset_lower_us + target_epoch_offset_us)
                if has_samples
                else ""
            ),
            "clock_offset_upper_us": (
                finite(self.offset_upper_us + target_epoch_offset_us)
                if has_samples
                else ""
            ),
            "clock_uncertainty_us": finite(self.uncertainty_us),
            "clock_drift_ppb": finite(self.drift_ppb),
            "clock_candidate_drift_ppb": finite(self.candidate_drift_ppb),
            "clock_physical_candidate_drift_ppb": finite(
                self.physical_candidate_drift_ppb
            ),
            "clock_statistical_candidate_drift_ppb": finite(
                self.statistical_candidate_drift_ppb
            ),
            "clock_statistical_drift_uncertainty_ppb": finite(
                self.statistical_drift_uncertainty_ppb
            ),
            "clock_drift_lower_ppb": finite(self.drift_lower_ppb),
            "clock_drift_upper_ppb": finite(self.drift_upper_ppb),
            "clock_drift_uncertainty_ppb": finite(self.drift_uncertainty_ppb),
            "clock_window_s": self.window_s,
            "clock_sample_count": self.sample_count,
            "clock_candidate_count": self.candidate_count,
            "clock_representative_count": self.representative_count,
            "clock_rejected_count": self.rejected_count,
            "clock_drift_fit_pending": int(self.drift_fit_pending),
            "clock_drift_fit_runtime_ms": finite(self.drift_fit_runtime_ms),
            "clock_drift_fit_error": self.drift_fit_error,
            "clock_model_age_s": finite(self.model_age_s),
            "clock_updated_unix_us": updated_unix_us,
        }
