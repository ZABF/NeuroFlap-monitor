from dataclasses import replace

from clock_estimator import AffineClockEstimator
from clock_types import ClockEstimatorStrategy
from clock_v3_fit import fit_v3_statistical_drift


class HybridAffineClockEstimator(AffineClockEstimator):
    """V4 physical bounds with a V3 statistical point estimate."""

    STRATEGY = ClockEstimatorStrategy.V4_V3
    MODEL_NAME = "constrained_affine_hybrid_v4_v3"

    def _fit_joint_snapshot(self, representatives, delay_floor_us):
        physical_fit = super()._fit_joint_snapshot(
            representatives, delay_floor_us
        )
        if physical_fit is None:
            return None

        statistical_fit = fit_v3_statistical_drift(
            representatives,
            delay_floor_us,
            max_drift_ppb=self.MAX_DRIFT_PPB,
        )
        if not statistical_fit.valid:
            return replace(
                physical_fit,
                physical_drift_ppb=physical_fit.drift_ppb,
                statistical_drift_ppb=statistical_fit.drift_ppb,
                statistical_uncertainty_ppb=statistical_fit.uncertainty_ppb,
            )

        selected_drift_ppb = max(
            physical_fit.drift_lower_ppb,
            min(physical_fit.drift_upper_ppb, statistical_fit.drift_ppb),
        )
        selected_support = self._support_at_drift_locked(
            representatives,
            physical_fit.source_anchor_us,
            selected_drift_ppb,
            delay_floor_us,
        )
        return replace(
            physical_fit,
            drift_ppb=selected_drift_ppb,
            compatible_count=selected_support.compatible_count,
            strict=selected_support.strict,
            accepted=(
                selected_support.compatible_count
                >= physical_fit.required_count
            ),
            physical_drift_ppb=physical_fit.drift_ppb,
            statistical_drift_ppb=statistical_fit.drift_ppb,
            statistical_uncertainty_ppb=statistical_fit.uncertainty_ppb,
        )
