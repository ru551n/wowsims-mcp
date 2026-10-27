from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .database import DatabaseError, GameDatabase
from .matching import normalize
from .presets import RACES

CLASS_FIELDS = {
    "balanceDruid": ("druid", "balance"),
    "feralCatDruid": ("druid", "feral_cat"),
    "hunter": ("hunter", "beast_mastery"),
    "mage": ("mage", "arcane"),
    "retributionPaladin": ("paladin", "retribution"),
    "priest": ("priest", "shadow"),
    "rogue": ("rogue", "combat"),
    "elementalShaman": ("shaman", "elemental"),
    "enhancementShaman": ("shaman", "enhancement"),
    "warlock": ("warlock", "destruction"),
    "dpsWarrior": ("warrior", "fury"),
}


def import_sim_json(
    data: str | dict[str, Any],
    presets: dict[str, Any],
    db: GameDatabase,
    spec: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    if isinstance(data, str):
        if len(data.encode()) > 256 * 1024:
            raise DatabaseError("Import data exceeds the 256 KB limit.")
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            raise DatabaseError(
                "Import is not valid JSON. Paste the wowsims UI settings JSON export."
            ) from exc
    else:
        parsed = data
    if len(json.dumps(parsed, separators=(",", ":")).encode()) > 256 * 1024:
        raise DatabaseError("Import data exceeds the 256 KB limit.")
    if not isinstance(parsed, dict) or not isinstance(parsed.get("player"), dict):
        raise DatabaseError(
            "Import must contain a player object from a wowsims UI settings export."
        )
    player = deepcopy(parsed["player"])
    fields = [key for key in CLASS_FIELDS if key in player]
    if len(fields) != 1:
        raise DatabaseError(
            "Import must contain exactly one supported player spec. "
            "Healing, tank, and unsupported DPS specs cannot be imported yet."
        )
    field = fields[0]
    character_class, default_spec = CLASS_FIELDS[field]
    selected_spec = default_spec
    if spec:
        selected_spec = normalize(spec).replace(" ", "_").replace("-", "_")
    preset = next(
        (
            preset
            for preset in presets["specs"].values()
            if preset["class"] == character_class and preset["spec"] == selected_spec
        ),
        None,
    )
    if preset is None:
        valid = [
            preset["spec"]
            for preset in presets["specs"].values()
            if preset["class"] == character_class
        ]
        raise DatabaseError(
            f"Spec {selected_spec!r} is not supported for {character_class}. "
            f"Valid choices: {', '.join(valid)}."
        )
    race = str(player.get("race", "")).removeprefix("Race")
    race = normalize(race).replace(" ", "_")
    if race not in RACES or race not in preset["races"]:
        raise DatabaseError(
            f"Imported race {race or 'unknown'} is not valid for {character_class}."
        )
    equipment = player.get("equipment", {})
    items = equipment.get("items", [])
    if not isinstance(items, list) or len(items) != 17:
        raise DatabaseError("Imported equipment must contain all 17 gear slots.")
    warnings = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise DatabaseError(f"Gear slot {index} is not an item object.")
        item_id = item.get("id", 0)
        if item_id and item_id not in db.by_id:
            warnings.append(
                f"Unknown item ID {item_id} in gear slot {index}; slot cleared."
            )
            items[index] = {}
    player["equipment"] = equipment
    for stats_key in ("bonusStats",):
        stats = player.get(stats_key)
        if isinstance(stats, dict):
            for array_key, size in (("stats", 42), ("pseudoStats", 27)):
                values = stats.get(array_key)
                if isinstance(values, list) and len(values) < size:
                    values.extend([0] * (size - len(values)))
                    warnings.append(
                        f"Expanded imported {stats_key}.{array_key} to {size} entries "
                        "for the pinned simulator."
                    )
    player["class"] = preset["class_enum"]
    player["race"] = RACES[race]
    player["name"] = player.get("name") or "Imported character"
    if not player.get("rotation"):
        player["rotation"] = deepcopy(preset["rotation"])
    player["talentsString"] = player.get("talentsString") or preset["talents"]
    player["distanceFromTarget"] = preset.get("distance", 5)
    request = {
        "raid": {
            "parties": [{"players": [player], "buffs": {}}],
            "buffs": {},
            "debuffs": {},
        },
        "encounter": {
            "duration": 300,
            "targets": [{"stats": [0] * 31 + [7685] + [0] * 10}],
        },
        "simOptions": {
            "iterations": 10000,
            "randomSeed": 1,
            "debug": False,
            "useLabeledRands": True,
        },
    }
    metadata = {
        "class": character_class,
        "spec": selected_spec,
        "race": race,
        "preset": "imported gear, talents, options, and rotation",
    }
    return request, metadata, warnings
