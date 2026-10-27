from __future__ import annotations

from typing import Any

from .constants import CLASSES, SLOTS
from .database import DatabaseError, GameDatabase

# Database stat name -> stat_weights stat name.
WEIGHT_NAMES = {
    "strength": "strength",
    "agility": "agility",
    "intellect": "intellect",
    "spirit": "spirit",
    "spell_damage": "spell_power",
    "attack_power": "attack_power",
    "ranged_attack_power": "attack_power",
    "melee_hit_rating": "hit_rating",
    "spell_hit_rating": "hit_rating",
    "melee_crit_rating": "crit_rating",
    "spell_crit_rating": "crit_rating",
    "melee_haste_rating": "haste_rating",
    "spell_haste_rating": "haste_rating",
    "armor_penetration": "armor_penetration",
    "expertise_rating": "expertise_rating",
}
# Equipment index -> item slot type. Weapons are not scored: damage is not a stat.
SLOT_TYPES = {
    0: "head",
    1: "neck",
    2: "shoulder",
    3: "back",
    4: "chest",
    5: "wrist",
    6: "hands",
    7: "waist",
    8: "legs",
    9: "feet",
    10: "finger",
    11: "finger",
    12: "trinket",
    13: "trinket",
}
# Highest armor type each class wears (1 cloth, 2 leather, 3 mail, 4 plate).
MAX_ARMOR = {
    "mage": 1,
    "priest": 1,
    "warlock": 1,
    "rogue": 2,
    "druid": 2,
    "hunter": 3,
    "shaman": 3,
    "paladin": 4,
    "warrior": 4,
}
ARMOR_SLOTS = {"head", "shoulder", "chest", "wrist", "hands", "waist", "legs", "feet"}


def score(stats: dict[str, float], weights: dict[str, float]) -> float:
    return sum(
        weights.get(WEIGHT_NAMES.get(name, ""), 0) * value
        for name, value in stats.items()
    )


def rank_slot(
    db: GameDatabase,
    weights: dict[str, float],
    character_class: str,
    slot_index: int,
    equipped: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    if slot_index not in SLOT_TYPES:
        raise DatabaseError(
            "Weapons and ranged slots cannot be ranked by stat weights; "
            "use wowsims_compare with gear overrides instead."
        )
    group = SLOT_TYPES[slot_index]
    class_id = next(key for key, name in CLASSES.items() if name == character_class)
    current = db.by_id.get(equipped.get("id", 0))
    suffix = equipped.get("randomSuffix")
    current_card = db.item_card(current, suffix) if current else None
    current_score = score(current_card["stats"], weights) if current_card else 0.0
    armor_cap = MAX_ARMOR.get(character_class, 4)
    ranked, skipped = [], 0
    for item in db.items:
        if SLOTS.get(item.get("type", 0)) != group:
            continue
        allowed = item.get("classAllowlist", [])
        if allowed and class_id not in allowed:
            continue
        if group in ARMOR_SLOTS and item.get("armorType", 0) > armor_cap:
            continue
        if item.get("randomSuffixOptions"):
            skipped += 1
            continue
        card = db.item_card(item)
        value = score(card["stats"], weights)
        ranked.append(
            {
                "id": item["id"],
                "name": item["name"],
                "ilvl": card["ilvl"],
                "score": round(value, 1),
                "delta_vs_equipped": round(value - current_score, 1)
                if current
                else None,
                "has_effects": bool(card.get("effects")),
                "sources": card.get("sources", [])[:2],
                "wowhead_url": card["wowhead_url"],
            }
        )
    ranked.sort(key=lambda row: row["score"], reverse=True)
    return {
        "equipped": (
            {
                "id": current["id"],
                "name": current_card["name"],
                "score": round(current_score, 1),
            }
            if current_card
            else {
                "id": equipped.get("id"),
                "score": None,
                "note": "Empty slot, or an item missing from the item database; "
                "deltas are unavailable.",
            }
        ),
        "ranked": ranked[:limit],
        "candidates": len(ranked),
        "excluded_random_suffix_items": skipped,
    }
