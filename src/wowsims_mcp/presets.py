from __future__ import annotations

import json
from copy import deepcopy
from importlib.resources import files
from typing import Any

from .constants import CLASSES, SIM_COMMIT, SLOTS
from .database import DatabaseError, GameDatabase
from .matching import normalize

RACES = {
    "blood_elf": "RaceBloodElf",
    "draenei": "RaceDraenei",
    "dwarf": "RaceDwarf",
    "gnome": "RaceGnome",
    "human": "RaceHuman",
    "night_elf": "RaceNightElf",
    "orc": "RaceOrc",
    "tauren": "RaceTauren",
    "troll": "RaceTroll",
    "undead": "RaceUndead",
    "high_order_skyborne": "RaceHighOrderSkyborne",
    "windshaper_skyborne": "RaceWindshaperSkyborne",
}
SLOT_ALIASES = {
    "head": 0,
    "neck": 1,
    "shoulder": 2,
    "shoulders": 2,
    "back": 3,
    "cloak": 3,
    "chest": 4,
    "wrist": 5,
    "bracers": 5,
    "hands": 6,
    "gloves": 6,
    "waist": 7,
    "belt": 7,
    "legs": 8,
    "feet": 9,
    "boots": 9,
    "finger": 10,
    "finger1": 10,
    "ring": 10,
    "ring1": 10,
    "finger2": 11,
    "ring2": 11,
    "trinket": 12,
    "trinket1": 12,
    "trinket2": 13,
    "main_hand": 14,
    "mainhand": 14,
    "weapon": 14,
    "off_hand": 15,
    "offhand": 15,
    "ranged": 16,
}


def load_presets() -> dict[str, Any]:
    resource = files("wowsims_mcp").joinpath("presets.json")
    data = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DatabaseError("Preset manifest is not a JSON object.")
    if data.get("sim_commit") != SIM_COMMIT:
        raise DatabaseError("Preset manifest does not match the pinned simulator.")
    return data


def list_specs(presets: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": key,
            "class": preset["class"],
            "spec": preset["spec"],
            "races": preset["races"],
            "has_default_preset": True,
        }
        for key, preset in presets["specs"].items()
    ]


def _race(value: str) -> str:
    normalized = normalize(value).replace(" ", "_")
    if normalized not in RACES:
        raise DatabaseError(f"Unknown race {value!r}. Valid races: {', '.join(RACES)}.")
    return normalized


def _slot(value: str) -> int:
    normalized = normalize(value).replace(" ", "_").replace("-", "_")
    compact = normalized.replace("_", "")
    if normalized in SLOT_ALIASES:
        return SLOT_ALIASES[normalized]
    if compact in SLOT_ALIASES:
        return SLOT_ALIASES[compact]
    raise DatabaseError(f"Unknown gear slot {value!r}.")


def _validate_gear_slot(
    item: dict[str, Any], slot: int, character_class: str, db: GameDatabase
) -> None:
    expected = SLOTS.get(item.get("type", 0))
    valid = {
        0: {"head"},
        1: {"neck"},
        2: {"shoulder"},
        3: {"back"},
        4: {"chest"},
        5: {"wrist"},
        6: {"hands"},
        7: {"waist"},
        8: {"legs"},
        9: {"feet"},
        10: {"finger"},
        11: {"finger"},
        12: {"trinket"},
        13: {"trinket"},
        14: {"weapon"},
        15: {"weapon"},
        16: {"ranged"},
    }[slot]
    if expected not in valid:
        slot_name = next(
            (name for name, number in SLOT_ALIASES.items() if number == slot), str(slot)
        )
        raise DatabaseError(
            f"{item['name']} is a {expected} item and cannot be equipped in "
            f"{slot_name}. Choose an item matching that slot."
        )
    allowed = item.get("classAllowlist", [])
    class_id = next(key for key, name in CLASSES.items() if name == character_class)
    if allowed and class_id not in allowed:
        raise DatabaseError(f"{item['name']} is not usable by {character_class}.")


def apply_overrides(
    request: dict[str, Any],
    db: GameDatabase,
    race: str | None = None,
    gear: dict[str, str | int] | None = None,
    talents: str | None = None,
) -> list[dict[str, Any]]:
    player = request["raid"]["parties"][0]["players"][0]
    character_class = normalize(player["class"].removeprefix("Class"))
    applied = []
    if race is not None:
        selected_race = _race(race)
        class_id = next(key for key, name in CLASSES.items() if name == character_class)
        valid_races = {
            1: {
                "human",
                "dwarf",
                "night_elf",
                "gnome",
                "draenei",
                "orc",
                "undead",
                "tauren",
                "troll",
            },
            2: {"human", "dwarf", "draenei", "blood_elf"},
            3: {"dwarf", "night_elf", "draenei", "orc", "tauren", "troll", "blood_elf"},
            4: {
                "human",
                "dwarf",
                "night_elf",
                "gnome",
                "orc",
                "undead",
                "troll",
                "blood_elf",
            },
            5: {
                "human",
                "dwarf",
                "night_elf",
                "draenei",
                "undead",
                "troll",
                "blood_elf",
            },
            7: {"draenei", "orc", "tauren", "troll"},
            8: {"human", "gnome", "draenei", "undead", "troll", "blood_elf"},
            9: {"human", "gnome", "orc", "undead", "blood_elf"},
            11: {"night_elf", "tauren"},
        }[class_id]
        if selected_race not in valid_races:
            raise DatabaseError(
                f"{selected_race} is not available for {character_class}. "
                f"Valid races: {', '.join(sorted(valid_races))}."
            )
        player["race"] = RACES[selected_race]
        applied.append({"type": "race", "value": selected_race})
    for slot_name, reference in (gear or {}).items():
        slot = _slot(slot_name)
        item = db.resolve(reference)
        _validate_gear_slot(item, slot, character_class, db)
        player["equipment"]["items"][slot] = {"id": item["id"]}
        applied.append(
            {
                "type": "gear",
                "slot": slot_name,
                "id": item["id"],
                "name": item["name"],
            }
        )
    if talents is not None:
        if not talents.strip():
            raise DatabaseError(
                "Talents must not be empty; omit them to use the preset."
            )
        player["talentsString"] = talents
        applied.append({"type": "talents", "value": talents})
    return applied


def build_request(
    presets: dict[str, Any],
    db: GameDatabase,
    spec_id: str,
    character_class: str,
    race: str,
    gear: dict[str, str | int] | None = None,
    talents: str | None = None,
    duration_s: float = 300,
    targets: int = 1,
    iterations: int = 10000,
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected_class = normalize(character_class).replace(" ", "_")
    class_specs = [
        (spec_key, preset)
        for spec_key, preset in presets["specs"].items()
        if preset["class"] == selected_class
    ]
    if not class_specs:
        valid = sorted({preset["class"] for preset in presets["specs"].values()})
        raise DatabaseError(
            f"Unsupported class {character_class!r}. Valid classes: {', '.join(valid)}."
        )
    key = normalize(spec_id).replace(" ", "_").replace("-", "_")
    aliases = {
        f"{preset['spec']}_{preset['class']}": spec_key
        for spec_key, preset in presets["specs"].items()
    }
    aliases.update(
        {preset["spec"]: spec_key for spec_key, preset in presets["specs"].items()}
    )
    key = aliases.get(key, key)
    if key not in presets["specs"] or presets["specs"][key]["class"] != selected_class:
        valid = [
            f"{preset['spec']} (ID: {spec_key})" for spec_key, preset in class_specs
        ]
        raise DatabaseError(
            f"Spec {spec_id!r} is not supported for {selected_class}. "
            f"Valid choices: {', '.join(valid)}."
        )
    preset = presets["specs"][key]
    selected_race = _race(race)
    if selected_race not in preset["races"]:
        raise DatabaseError(
            f"{selected_race} is not available for {preset['class']}. "
            f"Valid races: {', '.join(preset['races'])}."
        )
    equipment = deepcopy(preset["equipment"])
    equipment.setdefault("items", [{} for _ in range(17)])
    while len(equipment["items"]) < 17:
        equipment["items"].append({})
    player = {
        "name": f"{preset['spec'].replace('_', ' ').title()} {preset['class'].title()}",
        "race": RACES[selected_race],
        "class": preset["class_enum"],
        "equipment": equipment,
        "consumables": deepcopy(preset.get("consumables", {})),
        "buffs": {},
        preset["field"]: {"options": deepcopy(preset.get("options", {}))},
        "talentsString": preset["talents"],
        "rotation": deepcopy(preset["rotation"]),
        "distanceFromTarget": preset.get("distance", 5),
    }
    if preset.get("reaction_time_ms") is not None:
        player["reactionTimeMs"] = preset["reaction_time_ms"]
    if preset.get("channel_clip_delay_ms") is not None:
        player["channelClipDelayMs"] = preset["channel_clip_delay_ms"]
    request = {
        "raid": {
            "parties": [{"players": [player], "buffs": {}}],
            "buffs": {},
            "debuffs": {},
        },
        "encounter": {
            "duration": duration_s,
            "targets": [
                {"stats": [0] * 31 + [7685] + [0] * 10} for _ in range(targets)
            ],
        },
        "simOptions": {
            "iterations": iterations,
            "randomSeed": 1,
            "debug": False,
            "useLabeledRands": True,
        },
    }
    resolved_gear = apply_overrides(request, db, gear=gear, talents=talents)
    metadata = {
        "spec_id": key,
        "class": preset["class"],
        "spec": preset["spec"],
        "race": selected_race,
        "gear_overrides": resolved_gear,
        "buffs": "none",
        "preset": "pinned default gear, talents, and rotation",
    }
    return request, metadata
