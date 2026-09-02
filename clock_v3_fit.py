from dataclasses import dataclass
import math
import statistics


@dataclass(frozen=True)
class StatisticalDriftFit:
    drift_ppb: float
    uncertainty_ppb: float
    valid: bool


def _weighted_group_fit(observations, weights):
    group_stats = {}
    for (x_value, y_value, group), weight in zip(observations, weights):
        sum_w, sum_x, sum_y = group_stats.get(group, (0.0, 0.0, 0.0))
        group_stats[group] = (
            sum_w + weight,
            sum_x + weight * x_value,
            sum_y + weight * y_value,
        )
    means = {}
    for group, (sum_w, sum_x, sum_y) in group_stats.items():
        if sum_w <= 0.0:
            return 0.0, {}
        means[group] = (sum_x / sum_w, sum_y / sum_w)
    numerator = 0.0
    denominator = 0.0
    for (x_value, y_value, group), weight in zip(observations, weights):
        mean_x, mean_y = means[group]
        dx = x_value - mean_x
        numerator += weight * dx * (y_value - mean_y)
        denominator += weight * dx * dx
    slope = 0.0 if denominator <= 0.0 else numerator / denominator
    intercepts = {
        group: mean_y - slope * mean_x
        for group, (mean_x, mean_y) in means.items()
    }
    return slope, intercepts


def fit_v3_statistical_drift(
    representatives,
    delay_floor_us,
    *,
    max_drift_ppb=500_000.0,
    minimum_uncertainty_ppb=50.0,
):
    """Fit the V3 robust shared-slope model to immutable representatives."""
    representatives = tuple(representatives)
    if len(representatives) < 2:
        return StatisticalDriftFit(0.0, math.inf, False)

    delay_floor_us = max(1.0, float(delay_floor_us))
    anchor_us = representatives[0].source_mid_us
    observations = []
    base_weights = []
    for sample in representatives:
        x_seconds = (sample.source_mid_us - anchor_us) / 1_000_000.0
        observations.append((x_seconds, sample.upper_offset_us, 0))
        observations.append((x_seconds, sample.lower_offset_us, 1))
        delay_weight = (
            delay_floor_us / max(delay_floor_us, float(sample.rtt_us))
        ) ** 2
        base_weights.extend((delay_weight, delay_weight))

    weights = list(base_weights)
    slope_us_per_s = 0.0
    robust_sigma_us = 1.0
    for _iteration in range(8):
        slope_us_per_s, intercepts = _weighted_group_fit(observations, weights)
        if not intercepts:
            return StatisticalDriftFit(0.0, math.inf, False)
        residuals = [
            y_value - (intercepts[group] + slope_us_per_s * x_value)
            for x_value, y_value, group in observations
        ]
        residual_median = statistics.median(residuals)
        robust_sigma_us = max(
            1.0,
            1.4826
            * statistics.median(
                abs(value - residual_median) for value in residuals
            ),
        )
        threshold_us = 1.5 * robust_sigma_us
        new_weights = []
        for residual, base_weight in zip(residuals, base_weights):
            huber_weight = (
                1.0
                if abs(residual) <= threshold_us
                else threshold_us / abs(residual)
            )
            new_weights.append(base_weight * huber_weight)
        if max(
            abs(new - old) for new, old in zip(new_weights, weights)
        ) < 1.0e-3:
            weights = new_weights
            break
        weights = new_weights

    raw_drift_ppb = slope_us_per_s * 1000.0
    valid = math.isfinite(raw_drift_ppb) and abs(raw_drift_ppb) < max_drift_ppb
    drift_ppb = max(-max_drift_ppb, min(max_drift_ppb, raw_drift_ppb))
    group_means = {}
    for group in (0, 1):
        values = [
            (x_value, weight)
            for (x_value, _y_value, item_group), weight in zip(
                observations, weights
            )
            if item_group == group
        ]
        sum_w = sum(weight for _x_value, weight in values)
        group_means[group] = (
            0.0
            if sum_w <= 0.0
            else sum(x_value * weight for x_value, weight in values) / sum_w
        )
    slope_information = sum(
        weight * (x_value - group_means[group]) ** 2
        for (x_value, _y_value, group), weight in zip(observations, weights)
    )
    standard_error_us_per_s = (
        max_drift_ppb / 1000.0
        if slope_information <= 0.0
        else robust_sigma_us / math.sqrt(slope_information)
    )
    uncertainty_ppb = min(
        max_drift_ppb,
        max(minimum_uncertainty_ppb, 1.96 * standard_error_us_per_s * 1000.0),
    )
    return StatisticalDriftFit(drift_ppb, uncertainty_ppb, valid)
