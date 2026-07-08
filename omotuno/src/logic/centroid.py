from __future__ import annotations

import math

from src.pipeline.types import Vector


def normalize(vector: Vector) -> Vector:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return [0.0 for _ in vector]
    return [v / norm for v in vector]


def update_centroid_incremental(previous_centroid: Vector, incoming: Vector, new_count: int, renormalize: bool = False) -> Vector:
    """
    ADR-004: C_n = C_{n-1} + (V_n - C_{n-1}) / n
    """
    updated = [c + ((v - c) / new_count) for c, v in zip(previous_centroid, incoming)]
    if renormalize:
        return normalize(updated)
    return updated
