from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import (
    ARMOR_TYPES,
    CLASSES,
    DATABASE_URL,
    FACTIONS,
    HAND_TYPES,
    PROFESSIONS,
    QUALITIES,
    RANGED_WEAPON_TYPES,
    SIM_COMMIT,
    SLOTS,
    STATS,
    WEAPON_TYPES,
)
from .matching import Match, NameMatcher, normalize, probabilities


class DatabaseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SearchFilters:
    slot: str | None = None
    min_quality: str | None = None
    armor_type: str | None = None
    weapon_type: str | None = None
    character_class: str | None = None
    faction: str | None = None
    profession: str | None = None
    item_set: str | None = None
    ilvl_min: int | None = None
    ilvl_max: int | None = None
    has_proc: bool | None = None
    has_on_use: bool | None = None


def wowhead_url(kind: str, identifier: int) -> str:
    base = os.environ.get("WOWHEAD_BASE", "https://www.wowhead.com/forever")
    return f"{base.rstrip('/')}/{kind}={identifier}"


def _choice(value: str | None, choices: dict[int, str], label: str) -> str | None:
    if value is None:
        return None
    normalized = normalize(value).replace(" ", "-")
    valid = set(choices.values()) - {"unknown"}
    if normalized not in valid:
        raise DatabaseError(
            f"Unknown {label} {value!r}. Valid values: {', '.join(sorted(valid))}."
        )
    return normalized


def _stats(values: dict[str, float] | list[float] | None) -> dict[str, float]:
    if values is None:
        return {}
    pairs = values.items() if isinstance(values, dict) else enumerate(values)
    return {
        STATS.get(int(key), f"stat_{key}"): value
        for key, value in pairs
        if value and int(key) in STATS
    }


class GameDatabase:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.items: list[dict[str, Any]] = data.get("items", [])
        self.by_id: dict[int, dict[str, Any]] = {
            item["id"]: item for item in self.items
        }
        if len(self.by_id) != len(self.items):
            raise DatabaseError("The database contains duplicate item IDs.")
        self.npcs: dict[int, dict[str, Any]] = {
            npc["id"]: npc for npc in data.get("npcs", [])
        }
        self.zones: dict[int, dict[str, Any]] = {
            zone["id"]: zone for zone in data.get("zones", [])
        }
        self.suffixes = {
            suffix["id"]: suffix for suffix in data.get("randomSuffixes", [])
        }
        self.matcher = NameMatcher([item["name"] for item in self.items])

    @classmethod
    def load(cls, path: str | Path | None = None) -> GameDatabase:
        database_path = Path(path or os.environ.get("WOWSIMS_DB_PATH", "data/db.json"))
        try:
            with database_path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError as exc:
            raise DatabaseError(
                f"Game database not found at {database_path}. Download {DATABASE_URL} "
                "or set WOWSIMS_DB_PATH."
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise DatabaseError(
                f"Cannot load game database {database_path}: {exc}"
            ) from exc
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise DatabaseError(
                "Invalid game database: expected an object with an items list."
            )
        return cls(data)

    def summary(self, item: dict[str, Any]) -> dict[str, Any]:
        scaling = item.get("scalingOptions", {}).get("0", {})
        return {
            "id": item["id"],
            "name": item["name"],
            "slot": SLOTS.get(item.get("type", 0), "unknown"),
            "ilvl": scaling.get("ilvl", 0),
            "quality": QUALITIES.get(item.get("quality", 0), "unknown"),
            "wowhead_url": wowhead_url("item", item["id"]),
        }

    def sources(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        sources = []
        seen = set()
        for wrapper in item.get("sources", []):
            kind, source = next(iter(wrapper.items()))
            if kind == "drop":
                npc = self.npcs.get(source["npcId"]) if "npcId" in source else None
                zone = self.zones.get(source["zoneId"]) if "zoneId" in source else None
                value = {
                    "type": "drop",
                    "boss": npc["name"] if npc else source.get("otherName", "unknown"),
                    "zone": zone["name"] if zone else "unknown",
                }
                if npc:
                    value["npc_id"] = npc["id"]
                    value["wowhead_url"] = wowhead_url("npc", npc["id"])
                if source.get("difficulty"):
                    value["difficulty"] = source["difficulty"]
            elif kind == "crafted":
                value = {
                    "type": "crafted",
                    "profession": PROFESSIONS.get(
                        source.get("profession", 0), "unknown"
                    ),
                }
            elif kind == "rep":
                value = {
                    "type": "reputation",
                    "faction_id": source.get("repFactionId"),
                    "standing": source.get("repLevel"),
                }
            else:
                value = {"type": "unknown"}
            key = json.dumps(value, sort_keys=True)
            if key not in seen:
                sources.append(value)
                seen.add(key)
        return sources or [{"type": "unknown"}]

    def effects(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        result = []
        for effect in item.get("itemEffects", []):
            value: dict[str, Any] = {
                "name": effect.get("buffName")
                or f"Spell {effect.get('buffId', 'unknown')}"
            }
            if effect.get("buffId"):
                value["spell_id"] = effect["buffId"]
                value["wowhead_url"] = wowhead_url("spell", effect["buffId"])
            if "onUse" in effect:
                value["on_use"] = {
                    "cooldown_s": effect["onUse"].get("cooldownMs", 0) / 1000
                }
            if "proc" in effect:
                proc = effect["proc"]
                value["proc"] = {
                    key: proc[key]
                    for key in ("ppm", "procChance", "icdMs")
                    if key in proc
                }
            if effect.get("effectDurationMs", -1) >= 0:
                value["duration_s"] = effect["effectDurationMs"] / 1000
            result.append(value)
        return result

    def item_card(self, item: dict[str, Any]) -> dict[str, Any]:
        scaling = item.get("scalingOptions", {}).get("0", {})
        card = self.summary(item)
        card.update(
            {
                "armor_type": ARMOR_TYPES.get(item.get("armorType", 0)),
                "weapon_type": WEAPON_TYPES.get(item.get("weaponType", 0))
                or RANGED_WEAPON_TYPES.get(item.get("rangedWeaponType", 0)),
                "hand_type": HAND_TYPES.get(item.get("handType", 0)),
                "weapon_speed": item.get("weaponSpeed"),
                "phase": item.get("phase"),
                "stats": _stats(scaling.get("stats")),
                "effects": self.effects(item),
                "unique": item.get("unique", False),
                "restrictions": {
                    "classes": [
                        CLASSES.get(value, f"class_{value}")
                        for value in item.get("classAllowlist", [])
                    ],
                    "faction": FACTIONS.get(item["factionRestriction"])
                    if "factionRestriction" in item
                    else None,
                    "profession": PROFESSIONS.get(item["requiredProfession"])
                    if "requiredProfession" in item
                    else None,
                },
                "sources": self.sources(item),
            }
        )
        if item.get("setId"):
            card["set"] = {
                "id": item["setId"],
                "name": item.get("setName"),
                "wowhead_url": wowhead_url("item-set", item["setId"]),
            }
        if item.get("weaponDamageMin") or scaling.get("weaponDamageMin"):
            card["weapon_damage"] = {
                "min": scaling.get("weaponDamageMin", item.get("weaponDamageMin")),
                "max": scaling.get("weaponDamageMax", item.get("weaponDamageMax")),
            }
        if item.get("randomSuffixOptions"):
            card["suffix_options"] = [
                {"id": suffix_id, "name": self.suffixes[suffix_id]["name"]}
                for suffix_id in item["randomSuffixOptions"]
                if suffix_id in self.suffixes
            ]
        return {key: value for key, value in card.items() if value is not None}

    def _matches_filters(self, item: dict[str, Any], filters: SearchFilters) -> bool:
        scaling = item.get("scalingOptions", {}).get("0", {})
        classes = {CLASSES.get(value) for value in item.get("classAllowlist", [])}
        professions = {
            PROFESSIONS.get(source.get("crafted", {}).get("profession"))
            for source in item.get("sources", [])
            if "crafted" in source
        }
        if item.get("requiredProfession"):
            professions.add(PROFESSIONS.get(item["requiredProfession"]))
        effects = item.get("itemEffects", [])
        checks = (
            filters.slot is None or SLOTS.get(item.get("type", 0)) == filters.slot,
            filters.min_quality is None
            or item.get("quality", 0) >= _quality_number(filters.min_quality),
            filters.armor_type is None
            or ARMOR_TYPES.get(item.get("armorType", 0)) == filters.armor_type,
            filters.weapon_type is None
            or filters.weapon_type
            in {
                WEAPON_TYPES.get(item.get("weaponType", 0)),
                RANGED_WEAPON_TYPES.get(item.get("rangedWeaponType", 0)),
            },
            filters.character_class is None
            or not classes
            or filters.character_class in classes,
            filters.faction is None
            or not item.get("factionRestriction")
            or FACTIONS.get(item["factionRestriction"]) == filters.faction,
            filters.profession is None or filters.profession in professions,
            filters.item_set is None
            or normalize(item.get("setName", "")) == normalize(filters.item_set),
            filters.ilvl_min is None or scaling.get("ilvl", 0) >= filters.ilvl_min,
            filters.ilvl_max is None or scaling.get("ilvl", 0) <= filters.ilvl_max,
            filters.has_proc is None
            or any("proc" in effect for effect in effects) == filters.has_proc,
            filters.has_on_use is None
            or any("onUse" in effect for effect in effects) == filters.has_on_use,
        )
        return all(checks)

    def search(
        self,
        query: str | None = None,
        filters: SearchFilters | None = None,
        limit: int = 5,
        offset: int = 0,
    ) -> dict[str, Any]:
        filters = filters or SearchFilters()
        if not 1 <= limit <= 25:
            raise DatabaseError("limit must be between 1 and 25.")
        if offset < 0:
            raise DatabaseError("offset must not be negative.")
        if query is None or not query.strip():
            matches = [
                item for item in self.items if self._matches_filters(item, filters)
            ]
            matches.sort(
                key=lambda item: (self.summary(item)["ilvl"], item["id"]), reverse=True
            )
            total = len(matches)
            return {
                "ok": True,
                "status": "browse",
                "items": [
                    self.summary(item) for item in matches[offset : offset + limit]
                ],
                "total": total,
                "has_more": offset + limit < total,
                "next_offset": offset + limit if offset + limit < total else None,
                "summary": f"{total} items match the filters.",
            }
        eligible = {
            index
            for index, item in enumerate(self.items)
            if self._matches_filters(item, filters)
        }
        name_matches: list[Match] = [
            match
            for match in self.matcher.match(query, limit=100)
            if match.index in eligible
        ]
        exact = [match for match in name_matches if match.exact]
        name_matches = exact or name_matches[:limit]
        probabilities_list, none = probabilities(match.score for match in name_matches)
        candidates = []
        for match, probability in zip(name_matches, probabilities_list, strict=True):
            item = self.items[match.index]
            candidate = self.summary(item)
            candidate["probability"] = round(probability, 4)
            candidate["same_name_count"] = sum(
                other["name"] == item["name"] for other in self.items
            )
            candidates.append(candidate)
        if exact and len(exact) == 1:
            status = "exact"
        elif none >= 0.8 or not candidates:
            status = "not_found"
        elif candidates and candidates[0]["probability"] >= 0.85 and len(exact) != 1:
            status = "confident"
        elif candidates and candidates[0]["probability"] >= 0.5:
            status = "ambiguous"
        else:
            status = "suggestions"
        top = candidates[0] if candidates else None
        summary = (
            f"{top['name']}: {top['probability']:.0%} likely; "
            f"{none:.0%} it is not in the database."
            if top
            else "No matching item in the sim database; "
            "the item may still exist in the game."
        )
        return {
            "ok": True,
            "status": status,
            "query": query,
            "candidates": candidates,
            "none_of_these": round(none, 4),
            "summary": summary,
        }

    def resolve(self, reference: str | int) -> dict[str, Any]:
        if isinstance(reference, int) or reference.isdigit():
            try:
                return self.by_id[int(reference)]
            except KeyError as exc:
                raise DatabaseError(
                    f"Item ID {reference} is not in the sim database."
                ) from exc
        result = self.search(reference, limit=5)
        if (
            result["status"] in {"exact", "confident"}
            and result["candidates"][0]["same_name_count"] == 1
        ):
            return self.by_id[result["candidates"][0]["id"]]
        raise DatabaseError(json.dumps(result))


def _quality_number(quality: str) -> int:
    return next(number for number, name in QUALITIES.items() if name == quality)


def make_filters(
    slot: str | None = None,
    min_quality: str | None = None,
    armor_type: str | None = None,
    weapon_type: str | None = None,
    character_class: str | None = None,
    faction: str | None = None,
    profession: str | None = None,
    item_set: str | None = None,
    ilvl_min: int | None = None,
    ilvl_max: int | None = None,
    has_proc: bool | None = None,
    has_on_use: bool | None = None,
) -> SearchFilters:
    return SearchFilters(
        slot=_choice(slot, SLOTS, "slot"),
        min_quality=_choice(min_quality, QUALITIES, "quality"),
        armor_type=_choice(armor_type, ARMOR_TYPES, "armor type"),
        weapon_type=_choice(
            weapon_type,
            {
                **WEAPON_TYPES,
                **{key + 100: value for key, value in RANGED_WEAPON_TYPES.items()},
            },
            "weapon type",
        ),
        character_class=_choice(character_class, CLASSES, "class"),
        faction=_choice(faction, FACTIONS, "faction"),
        profession=_choice(profession, PROFESSIONS, "profession"),
        item_set=item_set,
        ilvl_min=ilvl_min,
        ilvl_max=ilvl_max,
        has_proc=has_proc,
        has_on_use=has_on_use,
    )


__all__ = ["SIM_COMMIT", "DatabaseError", "GameDatabase", "make_filters"]
