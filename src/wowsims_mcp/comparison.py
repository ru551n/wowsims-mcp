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


# Stat enum indexes in the pinned proto (common.proto); stats array has 39 slots.
WEIGHT_STATS = {
    "strength": (0, 50),
    "agility": (1, 50),
    "intellect": (3, 50),
    "spell_power": (5, 50),
    "spirit": (13, 50),
    "attack_power": (14, 100),
    "hit_rating": (17, 50),
    "crit_rating": (18, 50),
    "haste_rating": (19, 50),
    "armor_penetration": (20, 50),
    "expertise_rating": (21, 50),
}
STAT_SLOTS = 39


async def stat_weights(
    runner: SimulationRunner, request: dict[str, Any]
) -> dict[str, Any]:
    """Finite-difference DPS per point of each stat, shared RNG, vs. the baseline."""
    base = deepcopy(request)
    base["simOptions"]["useLabeledRands"] = True
    baseline = _player_dps(await runner.run(base))
    rows = []
    for name, (index, step) in WEIGHT_STATS.items():
        variant = deepcopy(base)
        player = variant["raid"]["parties"][0]["players"][0]
        stats = list(player.get("bonusStats", {}).get("stats") or [])
        stats += [0] * (STAT_SLOTS - len(stats))
        stats[index] += step
        player["bonusStats"] = {"stats": stats}
        dps = _player_dps(await runner.run(variant))
        rows.append({"stat": name, "value": (dps["mean"] - baseline["mean"]) / step})
    top = max((row["value"] for row in rows), default=0)
    for row in rows:
        row["relative"] = round(row["value"] / top, 3) if top > 0 else 0
    rows.sort(key=lambda row: row["value"], reverse=True)
    return {"weights": rows, "baseline_dps": baseline["mean"]}
