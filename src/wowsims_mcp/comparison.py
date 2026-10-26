from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from .database import GameDatabase
from .presets import apply_overrides
from .simulation import SimulationRunner


def _player_dps(result: dict[str, Any]) -> dict[str, float]:
    player = result["raidMetrics"]["parties"][0]["players"][0]
    dps = player["dps"]
    iterations = max(1, int(result.get("iterationsDone", 1)))
    return {
        "mean": float(dps.get("avg", 0)),
        "stdev": float(dps.get("stdev", 0)),
        "standard_error": float(dps.get("stdev", 0)) / math.sqrt(iterations),
    }


async def compare_requests(
    runner: SimulationRunner,
    baseline_request: dict[str, Any],
    variants: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_result = await runner.run(baseline_request)
    baseline = _player_dps(baseline_result)
    results = []
    for variant in variants:
        result = await runner.run(variant["request"])
        dps = _player_dps(result)
        delta = dps["mean"] - baseline["mean"]
        standard_error = math.sqrt(
            dps["standard_error"] ** 2 + baseline["standard_error"] ** 2
        )
        results.append(
            {
                "label": variant["label"],
                "applied_overrides": variant["applied_overrides"],
                "dps": dps,
                "delta": delta,
                "delta_pct": 100 * delta / baseline["mean"] if baseline["mean"] else 0,
                "standard_error": standard_error,
                "within_noise": abs(delta) < 2 * standard_error,
            }
        )
    results.sort(key=lambda result: result["dps"]["mean"], reverse=True)
    return {
        "baseline": baseline,
        "results": results,
        "best": results[0]["label"] if results else None,
        "iterations": baseline_result.get("iterationsDone", 0),
    }


def build_variant_request(
    baseline: dict[str, Any],
    db: GameDatabase,
    label: str,
    race: str | None = None,
    gear: dict[str, str | int] | None = None,
    talents: str | None = None,
) -> dict[str, Any]:
    request = deepcopy(baseline)
    applied = apply_overrides(request, db, race=race, gear=gear, talents=talents)
    if not applied:
        raise ValueError(
            f"Variant {label!r} has no overrides; add race, gear, or talents."
        )
    request["simOptions"]["useLabeledRands"] = True
    return {"label": label, "request": request, "applied_overrides": applied}
