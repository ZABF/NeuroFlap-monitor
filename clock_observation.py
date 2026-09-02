from dataclasses import dataclass
import time


@dataclass(frozen=True)
class FourTimestampSample:
    source_lower_us: int
    target_lower_us: int
    source_upper_us: int
    target_upper_us: int
    received_monotonic: float = 0.0

    @classmethod
    def source_initiated(cls, t1_us, t2_us, t3_us, t4_us):
        # source t1 -> target t2/t3 -> source t4
        return cls(
            source_lower_us=int(t4_us),
            target_lower_us=int(t3_us),
            source_upper_us=int(t1_us),
            target_upper_us=int(t2_us),
            received_monotonic=time.monotonic(),
        )

    @classmethod
    def target_initiated(cls, t1_us, t2_us, t3_us, t4_us):
        # target t1 -> source t2/t3 -> target t4
        return cls(
            source_lower_us=int(t2_us),
            target_lower_us=int(t1_us),
            source_upper_us=int(t3_us),
            target_upper_us=int(t4_us),
            received_monotonic=time.monotonic(),
        )

    @property
    def rtt_us(self):
        return (self.target_upper_us - self.target_lower_us) - (
            self.source_upper_us - self.source_lower_us
        )

    @property
    def source_mid_us(self):
        return (self.source_lower_us + self.source_upper_us) * 0.5

    @property
    def target_mid_us(self):
        return (self.target_lower_us + self.target_upper_us) * 0.5

    @property
    def upper_offset_us(self):
        return float(self.target_upper_us - self.source_upper_us)

    @property
    def lower_offset_us(self):
        return float(self.target_lower_us - self.source_lower_us)

    def offset_interval_at(self, source_anchor_us, drift_ppb):
        """Return the physically valid target-minus-source offset interval."""
        scale = 1.0 + float(drift_ppb) * 1.0e-9
        anchor = float(source_anchor_us)
        lower = (
            self.target_lower_us
            + (anchor - self.source_lower_us) * scale
            - anchor
        )
        upper = (
            self.target_upper_us
            + (anchor - self.source_upper_us) * scale
            - anchor
        )
        return float(lower), float(upper)
