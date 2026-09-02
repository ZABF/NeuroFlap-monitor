"""Geometry and coordinate transforms for the live flight visualization."""

from dataclasses import dataclass
import math

import numpy as np


EULER_ORDERS = ("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX")


def interpolate_sample(
    previous,
    following,
    timestamp_ms,
    *,
    angular=False,
    max_gap_ms=250.0,
):
    """Interpolate two timestamped scalar samples without crossing long gaps."""
    if previous is None:
        return None
    previous_time, previous_value = previous
    if following is None or following[0] <= previous_time:
        return float(previous_value)
    following_time, following_value = following
    gap_ms = following_time - previous_time
    if timestamp_ms <= previous_time or gap_ms > float(max_gap_ms):
        return float(previous_value)
    ratio = min(1.0, max(0.0, (timestamp_ms - previous_time) / gap_ms))
    delta = float(following_value) - float(previous_value)
    if angular:
        delta = (delta + 180.0) % 360.0 - 180.0
    return float(previous_value) + delta * ratio


def axis_rotation(axis, angle_deg):
    angle = math.radians(float(angle_deg))
    sine = math.sin(angle)
    cosine = math.cos(angle)
    if axis == "X":
        return np.array(
            ((1.0, 0.0, 0.0), (0.0, cosine, -sine), (0.0, sine, cosine))
        )
    if axis == "Y":
        return np.array(
            ((cosine, 0.0, sine), (0.0, 1.0, 0.0), (-sine, 0.0, cosine))
        )
    if axis == "Z":
        return np.array(
            ((cosine, -sine, 0.0), (sine, cosine, 0.0), (0.0, 0.0, 1.0))
        )
    raise ValueError(f"unsupported rotation axis: {axis}")


def euler_rotation(roll_deg, pitch_deg, yaw_deg, order="YXZ"):
    """Apply intrinsic Body X/Y/Z rotations in the selected application order."""
    order = str(order).upper()
    if order not in EULER_ORDERS:
        raise ValueError(f"unsupported Euler order: {order}")
    angles = {
        "X": float(roll_deg),
        "Y": float(pitch_deg),
        "Z": float(yaw_deg),
    }
    result = np.identity(3)
    for axis in order:
        result = axis_rotation(axis, angles[axis]) @ result
    return result


def aligned_pose(position, roll_deg, pitch_deg, yaw_deg, yaw_reference_deg, order):
    """Align world position and body attitude to the configured yaw reference."""
    alignment = axis_rotation("Z", -float(yaw_reference_deg))
    aligned_position = alignment @ np.asarray(position, dtype=float)
    body_to_display = alignment @ euler_rotation(
        roll_deg,
        pitch_deg,
        yaw_deg,
        order,
    )
    return aligned_position, body_to_display


def rotate_about_axis(points, origin, axis, angle_deg):
    points = np.asarray(points, dtype=float)
    origin = np.asarray(origin, dtype=float)
    axis = np.asarray(axis, dtype=float)
    norm = np.linalg.norm(axis)
    if norm <= 1.0e-12:
        return points.copy()
    axis = axis / norm
    angle = math.radians(float(angle_deg))
    cosine = math.cos(angle)
    sine = math.sin(angle)
    relative = points - origin
    cross = np.cross(axis, relative)
    along = np.outer(relative @ axis, axis)
    return origin + relative * cosine + cross * sine + along * (1.0 - cosine)


def wing_vertices(side, angle_deg, servo_included_angle_deg):
    """Return a wing polygon; positive servo angles move either wing upward."""
    side = 1 if int(side) >= 0 else -1
    half_angle = math.radians(float(servo_included_angle_deg) * 0.5)
    hinge_axis = np.array(
        (math.cos(half_angle), side * math.sin(half_angle), 0.0)
    )
    outward = np.array((-math.sin(half_angle), side * math.cos(half_angle), 0.0))
    root = np.array((0.0, side * 0.16, 0.0))
    points = np.array(
        (
            root + hinge_axis * 0.22,
            root + outward * 0.92 + hinge_axis * 0.10,
            root + outward * 0.82 - hinge_axis * 0.30,
            root - hinge_axis * 0.22,
        )
    )
    return rotate_about_axis(
        points,
        root,
        hinge_axis,
        side * float(angle_deg),
    )


def box_faces(center, size):
    center = np.asarray(center, dtype=float)
    half = np.asarray(size, dtype=float) * 0.5
    vertices = np.array(
        [
            center + half * (x, y, z)
            for x, y, z in (
                (-1, -1, -1),
                (1, -1, -1),
                (1, 1, -1),
                (-1, 1, -1),
                (-1, -1, 1),
                (1, -1, 1),
                (1, 1, 1),
                (-1, 1, 1),
            )
        ]
    )
    return tuple(
        vertices[list(indexes)]
        for indexes in (
            (0, 1, 2, 3),
            (4, 7, 6, 5),
            (0, 4, 5, 1),
            (1, 5, 6, 2),
            (2, 6, 7, 3),
            (3, 7, 4, 0),
        )
    )


@dataclass(frozen=True)
class FlightSample:
    timestamp_ms: float
    position: tuple
    roll_deg: float
    pitch_deg: float
    yaw_deg: float
    left_command_deg: float
    left_actual_deg: float
    right_command_deg: float
    right_actual_deg: float
