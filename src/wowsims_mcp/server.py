from __future__ import annotations

import json
import os
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .armory import SLOTS, fetch_character, to_sim
from .comparison import build_variant_request, compare_requests, stat_weights
from .constants import SIM_COMMIT, SIM_REF
from .database import DatabaseError, GameDatabase, make_filters
from .patches import SourceUnavailable, get_patch_changes
from .presets import _slot, apply_overrides, build_request, list_specs, load_presets
from .simulation import (
    SimulationError,
    SimulationRunner,
    SimulationTimeout,
    SimulationUnavailable,
    simulation_summary,
)
from .upgrades import rank_slot

mcp = FastMCP(
    "wowsims_mcp",
    instructions=(
        "Look up World of Warcraft items in the pinned wowsims database. "
        "Search accepts misspellings and returns probabilities; ask the user "
        "when the result is ambiguous. Not found means absent from this database, "
        "not that the item does not exist. Use wowsims_list_specs and "
        "wowsims_simulate for single-player DPS simulations with no raid buffs."
    ),
    host=os.environ.get("WOWSIMS_MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("WOWSIMS_MCP_PORT", "8000")),
    stateless_http=True,
    json_response=True,
)
_database: GameDatabase | None = None
_presets: dict[str, Any] | None = None
_runner: SimulationRunner | None = None
ARMORY_URL = Annotated[
    str | None,
    Field(
        description="Forever armory character link; uses that character's gear, "
        "race and talents with the preset rotation of its main talent tree.",
    ),
]
READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def get_database() -> GameDatabase:
    global _database
    if _database is None:
        _database = GameDatabase.load()
    return _database


def get_presets() -> dict[str, Any]:
    global _presets
    if _presets is None:
        _presets = load_presets()
    return _presets


def get_runner() -> SimulationRunner:
    global _runner
    if _runner is None:
        _runner = SimulationRunner()
    return _runner


async def _player_request(
    armory_url: str | None,
    character_class: str | None,
    spec: str | None,
    race: str | None,
    gear: dict[str, str | int] | None,
    talents: str | None,
    duration_s: float,
    targets: int,
    iterations: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if armory_url is not None:
        profile = await fetch_character(armory_url)
        sim_class, spec_id, sim_race, items, armory_talents, warnings = to_sim(
            profile, get_presets()
        )
        request, metadata = build_request(
            get_presets(),
            get_database(),
            spec_id,
            sim_class,
            sim_race,
            None,
            None,
            duration_s,
            targets,
            iterations,
        )
        player = request["raid"]["parties"][0]["players"][0]
        player["equipment"]["items"] = items
        player["talentsString"] = talents or armory_talents
        player["name"] = f"{profile['name']} {profile.get('surname', '')}".strip()
        metadata.update(
            {
                "armory_character": player["name"],
                "level": profile.get("level"),
                "preset": "armory gear, race and talents; preset rotation",
                "talents": talents or armory_talents,
                "warnings": warnings,
            }
        )
        metadata["gear_overrides"] = apply_overrides(
            request, get_database(), race=race, gear=gear
        )
    else:
        if character_class is None or spec is None or race is None:
            raise DatabaseError(
                "Provide an armory_url, or class, spec and race for a preset."
            )
        request, metadata = build_request(
            get_presets(),
            get_database(),
            spec,
            character_class,
            race,
            gear,
            talents,
            duration_s,
            targets,
            iterations,
        )
    request["encounter"]["duration"] = duration_s
    request["encounter"]["targets"] = [
        request["encounter"]["targets"][0] for _ in range(targets)
    ]
    request["simOptions"]["iterations"] = iterations
    return request, metadata


def _error(exc: DatabaseError) -> dict[str, Any]:
    try:
        details = json.loads(str(exc))
    except json.JSONDecodeError:
        details = None
    if isinstance(details, dict) and "candidates" in details:
        return {
            **details,
            "ok": False,
            "code": "ITEM_NOT_FOUND"
            if details["status"] == "not_found"
            else "AMBIGUOUS_ITEM",
            "message": details["summary"],
            "next_step": "Ask the user to choose a candidate or provide an item ID.",
        }
    return {
        "ok": False,
        "code": getattr(exc, "code", "INVALID_INPUT"),
        "message": str(exc),
        "next_step": "Check the arguments or call wowsims_search_items for candidates.",
    }


@mcp.tool(annotations=READ_ONLY)
def wowsims_search_items(
    query: Annotated[
        str | None,
        Field(
            default=None,
            max_length=200,
            description="Item name, including misspellings; omit to browse.",
        ),
    ] = None,
    slot: str | None = None,
    min_quality: str | None = None,
    armor_type: str | None = None,
    weapon_type: str | None = None,
    character_class: Annotated[
        str | None,
        Field(
            default=None,
            validation_alias="class",
            description="Include items usable by this class.",
        ),
    ] = None,
    faction: str | None = None,
    profession: str | None = None,
    item_set: Annotated[
        str | None,
        Field(default=None, validation_alias="set", description="Exact item set name."),
    ] = None,
    ilvl_min: Annotated[int | None, Field(default=None, ge=0)] = None,
    ilvl_max: Annotated[int | None, Field(default=None, ge=0)] = None,
    has_proc: bool | None = None,
    has_on_use: bool | None = None,
    limit: Annotated[int, Field(default=5, ge=1, le=25)] = 5,
    offset: Annotated[int, Field(default=0, ge=0)] = 0,
) -> dict[str, Any]:
    """Find items by fuzzy name, or browse items using filters."""
    try:
        filters = make_filters(
            slot=slot,
            min_quality=min_quality,
            armor_type=armor_type,
            weapon_type=weapon_type,
            character_class=character_class,
            faction=faction,
            profession=profession,
            item_set=item_set,
            ilvl_min=ilvl_min,
            ilvl_max=ilvl_max,
            has_proc=has_proc,
            has_on_use=has_on_use,
        )
        return get_database().search(query, filters, limit, offset)
    except DatabaseError as exc:
        return _error(exc)


@mcp.tool(annotations=READ_ONLY)
def wowsims_get_item(
    item: Annotated[
        str | int, Field(description="Exact item ID or an item name to resolve.")
    ],
    suffix: Annotated[
        str | int | None,
        Field(
            default=None, description="Random suffix ID or name, such as of the Eagle."
        ),
    ] = None,
) -> dict[str, Any]:
    """Get an item's stats, effects, restrictions, set, and known sources."""
    try:
        result = get_database().item_card(get_database().resolve(item), suffix)
        result["ok"] = True
        result["sim_version"] = SIM_COMMIT
        return result
    except DatabaseError as exc:
        return _error(exc)


@mcp.tool(annotations=READ_ONLY)
def wowsims_get_loot(
    boss_or_zone: Annotated[str, Field(max_length=200)],
    slot: str | None = None,
    character_class: Annotated[
        str | None, Field(default=None, validation_alias="class")
    ] = None,
    limit: Annotated[int, Field(default=25, ge=1, le=100)] = 25,
    offset: Annotated[int, Field(default=0, ge=0)] = 0,
) -> dict[str, Any]:
    """List items dropped by a boss or in a zone, with optional filters."""
    try:
        return get_database().get_loot(
            boss_or_zone, slot, character_class, limit, offset
        )
    except DatabaseError as exc:
        return _error(exc)


@mcp.tool(annotations=READ_ONLY)
def wowsims_get_set(
    name: Annotated[str | int, Field(description="Item set name or ID.")],
) -> dict[str, Any]:
    """List an item set's pieces, classes, sources, and Wowhead link."""
    try:
        return get_database().get_set(name)
    except DatabaseError as exc:
        return _error(exc)


@mcp.tool(annotations=READ_ONLY)
def wowsims_compare_items(
    items: Annotated[list[str | int], Field(min_length=2, max_length=4)],
    suffixes: list[str | int] | None = None,
) -> dict[str, Any]:
    """Compare 2-4 items' stats, effects, and restrictions without simulating."""
    try:
        return get_database().compare_items(items, suffixes)
    except DatabaseError as exc:
        return _error(exc)


@mcp.tool(annotations=READ_ONLY)
def wowsims_search_enchants(
    query: Annotated[str | None, Field(default=None, max_length=200)] = None,
    slot: str | None = None,
    limit: Annotated[int, Field(default=5, ge=1, le=25)] = 5,
) -> dict[str, Any]:
    """Search enchants by fuzzy name and equipment slot."""
    try:
        return get_database().search_enchants(query, slot, limit)
    except DatabaseError as exc:
        return _error(exc)


@mcp.tool(annotations=READ_ONLY)
def wowsims_search_consumables(
    query: Annotated[str | None, Field(default=None, max_length=200)] = None,
    consumable_type: Annotated[
        str | None, Field(default=None, validation_alias="type")
    ] = None,
    limit: Annotated[int, Field(default=5, ge=1, le=25)] = 5,
) -> dict[str, Any]:
    """Search potions, flasks, food, and other consumables by fuzzy name."""
    try:
        return get_database().search_consumables(query, consumable_type, limit)
    except DatabaseError as exc:
        return _error(exc)


@mcp.tool(annotations=READ_ONLY)
def wowsims_get_wowhead_link(
    kind: Annotated[str, Field(description="item, spell, npc, zone, or item-set")],
    id_or_name: str | int,
) -> dict[str, Any]:
    """Generate an unverified Wowhead link; never fetches Wowhead."""
    try:
        return get_database().get_wowhead_link(kind, id_or_name)
    except DatabaseError as exc:
        return _error(exc)


@mcp.tool(annotations=READ_ONLY)
def wowsims_list_specs() -> dict[str, Any]:
    """List supported DPS class/spec presets and their allowed races."""
    return {
        "ok": True,
        "specs": list_specs(get_presets()),
        "sim_version": SIM_COMMIT,
        "ruleset_note": "TBC rules; single-player DPS presets without raid buffs.",
    }


@mcp.tool(annotations=READ_ONLY)
async def wowsims_simulate(
    character_class: Annotated[
        str | None,
        Field(
            default=None,
            validation_alias="class",
            description="Player class; omit when using armory_url.",
        ),
    ] = None,
    spec: Annotated[
        str | None,
        Field(description="Spec or preset ID from wowsims_list_specs."),
    ] = None,
    race: Annotated[
        str | None, Field(default=None, description="Race or race override.")
    ] = None,
    armory_url: ARMORY_URL = None,
    gear: Annotated[
        dict[str, str | int] | None,
        Field(
            default=None,
            description="Optional gear overrides by slot; item names or IDs. "
            "Unspecified slots use the preset.",
        ),
    ] = None,
    talents: Annotated[
        str | None,
        Field(default=None, description="Optional wowsims/Wowhead talent string."),
    ] = None,
    duration_s: Annotated[float, Field(default=300, gt=0, le=3600)] = 300,
    targets: Annotated[int, Field(default=1, ge=1, le=20)] = 1,
    iterations: Annotated[int, Field(default=10000, ge=1, le=20000)] = 10000,
) -> dict[str, Any]:
    """Simulate a player using a preset plus optional gear and talent overrides."""
    try:
        request, metadata = await _player_request(
            armory_url,
            character_class,
            spec,
            race,
            gear,
            talents,
            duration_s,
            targets,
            iterations,
        )
        result = await get_runner().run(request)
        summary = simulation_summary(result)
        return {
            "ok": True,
            **metadata,
            **summary,
            "duration_s": duration_s,
            "targets": targets,
            "ruleset_note": "TBC sim result, not combat logs; no raid/party buffs.",
            "summary": (
                f"{metadata['race'].replace('_', ' ').title()} "
                f"{metadata['spec'].replace('_', ' ').title()} "
                f"{metadata['class'].title()}: ~{summary['dps']['mean']:.1f} DPS "
                f"(±{summary['dps']['stdev']:.1f}) over {duration_s:g}s, "
                f"{targets} target(s), no raid buffs."
            ),
        }
    except DatabaseError as exc:
        return _error(exc)
    except SimulationUnavailable as exc:
        return {
            "ok": False,
            "code": "SIM_UNAVAILABLE",
            "message": str(exc),
            "next_step": "Configure the simulator before requesting a simulation.",
        }
    except SimulationTimeout as exc:
        return {
            "ok": False,
            "code": "SIM_TIMEOUT",
            "message": str(exc),
            "next_step": "Retry with fewer iterations or a shorter encounter.",
        }
    except SimulationError as exc:
        return {
            "ok": False,
            "code": "SIM_FAILED",
            "message": str(exc),
            "next_step": "Check gear, talents, and spec compatibility.",
        }


@mcp.tool(annotations=READ_ONLY)
async def wowsims_lookup_character(armory_url: str) -> dict[str, Any]:
    """Read a character's class, race, spec and gear from a Forever armory link."""
    try:
        profile = await fetch_character(armory_url)
        sim_class, spec_id, sim_race, items, talents, warnings = to_sim(
            profile, get_presets()
        )
    except DatabaseError as exc:
        return _error(exc)
    gear = {
        key: {"name": profile["gear"][key].get("name"), **items[SLOTS[key]]}
        for key in profile["gear"]
        if key in SLOTS
    }
    return {
        "ok": True,
        "name": f"{profile['name']} {profile.get('surname', '')}".strip(),
        "level": profile.get("level"),
        "class": sim_class,
        "race": sim_race,
        "spec_id": spec_id,
        "gear": gear,
        "talents": talents,
        "warnings": warnings,
        "summary": (
            f"{profile['name']} {profile.get('surname', '')}: level "
            f"{profile.get('level')} {sim_race.replace('_', ' ')} {sim_class}, "
            f"{len(gear)} gear slots."
        ),
    }


@mcp.tool(annotations=READ_ONLY)
async def wowsims_get_patch_changes(
    item_or_spell: Annotated[
        str | None,
        Field(default=None, description="Item or spell name fragment, or numeric ID."),
    ] = None,
    since_patch: Annotated[
        str | None,
        Field(
            default=None, description="Build such as 1.60.1.70334; default: newest 3."
        ),
    ] = None,
    limit: Annotated[int, Field(default=20, ge=1, le=50)] = 20,
) -> dict[str, Any]:
    """What changed for items and spells in recent patches and hotfixes."""
    try:
        result = await get_patch_changes(item_or_spell, since_patch, limit)
    except SourceUnavailable as exc:
        return {
            "ok": False,
            "code": "SOURCE_UNAVAILABLE",
            "message": str(exc),
            "next_step": "Fall back to a web search for the patch notes.",
        }
    except ValueError as exc:
        return {
            "ok": False,
            "code": "INVALID_INPUT",
            "message": str(exc),
            "next_step": "Omit since_patch or use a build such as 1.60.1.70334.",
        }
    n = len(result["changes"])
    return {
        "ok": True,
        **result,
        "source": "wowsims/gamedata (live, cached up to 1 hour)",
        "summary": f"{n} change(s) found"
        + (" (more available)." if result["has_more"] else "."),
    }


@mcp.tool(annotations=READ_ONLY)
async def wowsims_best_items_for_slot(
    slot: Annotated[str, Field(description="Gear slot, e.g. head, ring1, trinket2.")],
    character_class: Annotated[
        str | None, Field(default=None, validation_alias="class")
    ] = None,
    spec: str | None = None,
    race: str | None = None,
    armory_url: ARMORY_URL = None,
    gear: dict[str, str | int] | None = None,
    talents: str | None = None,
    limit: Annotated[int, Field(default=10, ge=1, le=25)] = 10,
    iterations: Annotated[int, Field(default=5000, ge=1, le=20000)] = 5000,
) -> dict[str, Any]:
    """Rank items for a slot by sim stat weights, against what is equipped."""
    try:
        request, metadata = await _player_request(
            armory_url,
            character_class,
            spec,
            race,
            gear,
            talents,
            300,
            1,
            iterations,
        )
        slot_index = _slot(slot)
        weighted = await stat_weights(get_runner(), request)
        weights = {row["stat"]: row["value"] for row in weighted["weights"]}
        player = request["raid"]["parties"][0]["players"][0]
        result = rank_slot(
            get_database(),
            weights,
            metadata["class"],
            slot_index,
            player["equipment"]["items"][slot_index],
            limit,
        )
        best = result["ranked"][0] if result["ranked"] else None
        return {
            "ok": True,
            **metadata,
            "slot": slot,
            "weights": weighted["weights"],
            **result,
            "ruleset_note": (
                "Scored by sim stat weights only: item effects, set bonuses, "
                "sockets and stat caps are not modelled; verify with wowsims_compare."
            ),
            "summary": (
                f"Top for {slot}: {best['name']} "
                + (
                    f"({best['delta_vs_equipped']:+.1f} DPS vs equipped by weights)."
                    if best["delta_vs_equipped"] is not None
                    else "(slot is empty in this setup)."
                )
                if best
                else f"No candidate items found for {slot}."
            ),
        }
    except DatabaseError as exc:
        return _error(exc)
    except SimulationError as exc:
        return {
            "ok": False,
            "code": getattr(exc, "code", "SIM_FAILED"),
            "message": str(exc),
            "next_step": "Check the configuration and simulator availability.",
        }


@mcp.tool(annotations=READ_ONLY)
async def wowsims_stat_weights(
    character_class: Annotated[
        str | None, Field(default=None, validation_alias="class")
    ] = None,
    spec: str | None = None,
    race: str | None = None,
    armory_url: ARMORY_URL = None,
    gear: dict[str, str | int] | None = None,
    talents: str | None = None,
    duration_s: Annotated[float, Field(default=300, gt=0, le=3600)] = 300,
    targets: Annotated[int, Field(default=1, ge=1, le=20)] = 1,
    iterations: Annotated[int, Field(default=5000, ge=1, le=20000)] = 5000,
) -> dict[str, Any]:
    """Estimate DPS gained per point of each stat (finite differences, sim-based)."""
    try:
        request, metadata = await _player_request(
            armory_url,
            character_class,
            spec,
            race,
            gear,
            talents,
            duration_s,
            targets,
            iterations,
        )
        result = await stat_weights(get_runner(), request)
        top = result["weights"][0]
        return {
            "ok": True,
            **metadata,
            **result,
            "duration_s": duration_s,
            "targets": targets,
            "ruleset_note": "TBC sim estimate; no raid buffs, no stat caps modelled.",
            "summary": (
                f"Best stat: {top['stat']} ({top['value']:.2f} DPS/point); "
                + ", ".join(
                    f"{w['stat']} {w['relative']:.2f}" for w in result["weights"][:5]
                )
            ),
        }
    except DatabaseError as exc:
        return _error(exc)
    except SimulationError as exc:
        return {
            "ok": False,
            "code": getattr(exc, "code", "SIM_FAILED"),
            "message": str(exc),
            "next_step": "Check the configuration and simulator availability.",
        }


@mcp.tool(annotations=READ_ONLY)
async def wowsims_compare(
    variants: Annotated[
        list[dict[str, Any]],
        Field(
            min_length=1,
            max_length=8,
            description="Each variant needs a label and race, gear, "
            "or talents override.",
        ),
    ],
    character_class: Annotated[
        str | None, Field(default=None, validation_alias="class")
    ] = None,
    spec: str | None = None,
    race: Annotated[
        str | None, Field(default=None, description="Baseline race or override.")
    ] = None,
    armory_url: ARMORY_URL = None,
    gear: Annotated[
        dict[str, str | int] | None,
        Field(default=None, description="Optional baseline gear overrides by slot."),
    ] = None,
    talents: str | None = None,
    duration_s: Annotated[float, Field(default=300, gt=0, le=3600)] = 300,
    targets: Annotated[int, Field(default=1, ge=1, le=20)] = 1,
    iterations: Annotated[int, Field(default=10000, ge=1, le=20000)] = 10000,
) -> dict[str, Any]:
    """Compare race, gear, or talent variants against one baseline using shared RNG."""
    try:
        baseline, metadata = await _player_request(
            armory_url,
            character_class,
            spec,
            race,
            gear,
            talents,
            duration_s,
            targets,
            iterations,
        )
        variant_requests = []
        labels = set()
        for variant in variants:
            label = str(variant.get("label", "")).strip()
            if not label or label in labels:
                raise DatabaseError("Each variant needs a unique, non-empty label.")
            labels.add(label)
            variant_requests.append(
                build_variant_request(
                    baseline,
                    get_database(),
                    label,
                    variant.get("race"),
                    variant.get("gear"),
                    variant.get("talents"),
                )
            )
        comparison = await compare_requests(get_runner(), baseline, variant_requests)
        best = comparison["results"][0]
        return {
            "ok": True,
            **metadata,
            **comparison,
            "duration_s": duration_s,
            "targets": targets,
            "ruleset_note": "TBC sim comparison, not combat logs; no raid buffs.",
            "summary": (
                f"Best variant: {best['label']} at {best['dps']['mean']:.1f} DPS "
                f"({best['delta']:+.1f}, {best['delta_pct']:+.2f}%). "
                + ("Difference is within noise." if best["within_noise"] else "")
            ),
        }
    except DatabaseError as exc:
        return _error(exc)
    except ValueError as exc:
        return {
            "ok": False,
            "code": "INVALID_OVERRIDE",
            "message": str(exc),
            "next_step": "Give every variant a race, gear, or talents override.",
        }
    except SimulationUnavailable as exc:
        return {
            "ok": False,
            "code": "SIM_UNAVAILABLE",
            "message": str(exc),
            "next_step": "Configure the simulator before requesting a comparison.",
        }
    except SimulationTimeout as exc:
        return {
            "ok": False,
            "code": "SIM_TIMEOUT",
            "message": str(exc),
            "next_step": "Retry with fewer variants or iterations.",
        }
    except SimulationError as exc:
        return {
            "ok": False,
            "code": "SIM_FAILED",
            "message": str(exc),
            "next_step": "Check each variant's gear, talents, and spec compatibility.",
        }


@mcp.tool(annotations=READ_ONLY)
def wowsims_help(
    task: Annotated[str | None, Field(default=None, max_length=200)] = None,
) -> dict[str, Any]:
    """Show available wowsims tools or find one for a task."""
    tools: list[dict[str, Any]] = [
        {
            "tool": "wowsims_search_items",
            "one_line": "Search or browse items, with misspelling tolerance "
            "and filters.",
            "example_call": {"query": "thunderfuri"},
            "keywords": "find search item gear name typo filter slot class weapon",
        },
        {
            "tool": "wowsims_get_item",
            "one_line": "Show an item's stats, effects, restrictions, and sources.",
            "example_call": {"item": 19019},
            "keywords": "item details stats proc use drop source boss where",
        },
        {
            "tool": "wowsims_get_loot",
            "one_line": "Find loot dropped by a boss or in a zone.",
            "example_call": {"boss_or_zone": "Edwin VanCleef"},
            "keywords": "loot drop boss zone where source",
        },
        {
            "tool": "wowsims_get_set",
            "one_line": "List pieces and sources for an item set.",
            "example_call": {"name": "Imperial Plate"},
            "keywords": "set pieces armor",
        },
        {
            "tool": "wowsims_compare_items",
            "one_line": "Compare item stats without running a simulation.",
            "example_call": {"items": [19019, 17182]},
            "keywords": "compare items stats difference",
        },
        {
            "tool": "wowsims_search_enchants",
            "one_line": "Search enchants by name and slot.",
            "example_call": {"query": "greater agility"},
            "keywords": "enchant search gear",
        },
        {
            "tool": "wowsims_search_consumables",
            "one_line": "Search potions, flasks, food, and other consumables.",
            "example_call": {"query": "thistle tea"},
            "keywords": "consumable potion flask food search",
        },
        {
            "tool": "wowsims_get_wowhead_link",
            "one_line": "Generate an unverified Wowhead link.",
            "example_call": {"kind": "item", "id_or_name": 19019},
            "keywords": "wowhead link url item spell npc zone set",
        },
        {
            "tool": "wowsims_list_specs",
            "one_line": "List supported DPS class/spec presets and valid races.",
            "example_call": {},
            "keywords": "class spec race list supported simulate",
        },
        {
            "tool": "wowsims_simulate",
            "one_line": "Simulate a class, spec, race, and optional gear overrides.",
            "example_call": {
                "class": "rogue",
                "spec": "combat",
                "race": "troll",
                "gear": {"main_hand": "Thunderfury"},
            },
            "keywords": "simulate dps damage gear race class spec result",
        },
        {
            "tool": "wowsims_compare",
            "one_line": "Compare race, gear, or talent variants with noise flags.",
            "example_call": {
                "class": "rogue",
                "spec": "combat",
                "race": "human",
                "variants": [{"label": "Troll", "race": "troll"}],
            },
            "keywords": "compare simulation racial gear talent better dps",
        },
        {
            "tool": "wowsims_get_patch_changes",
            "one_line": "What changed for an item or spell in recent patches.",
            "example_call": {"item_or_spell": "Faerie Fire"},
            "keywords": "patch hotfix nerf buff changed notes",
        },
        {
            "tool": "wowsims_best_items_for_slot",
            "one_line": "Rank items for a gear slot by sim stat weights.",
            "example_call": {
                "class": "rogue",
                "spec": "combat",
                "race": "human",
                "slot": "head",
            },
            "keywords": "upgrade best slot gear bis improve item",
        },
        {
            "tool": "wowsims_lookup_character",
            "one_line": "Read a character's gear from a Forever armory link.",
            "example_call": {
                "armory_url": "https://worldofwarcraft.blizzard.com/en-us/forever/eu/armory/character/name-surname"
            },
            "keywords": "armory character link gear import my char lookup",
        },
        {
            "tool": "wowsims_stat_weights",
            "one_line": "Sim-based DPS per point of each stat for a spec or character.",
            "example_call": {"class": "rogue", "spec": "combat", "race": "human"},
            "keywords": "stat weights best stat priority agility crit haste hit",
        },
    ]
    if task:
        words = set(task.lower().split())
        matches = sorted(
            tools,
            key=lambda tool: len(words & set(tool["keywords"].split())),
            reverse=True,
        )
        return {
            "ok": True,
            "matches": [
                {k: v for k, v in tool.items() if k != "keywords"} for tool in matches
            ],
        }
    return {
        "ok": True,
        "index": [
            {k: v for k, v in tool.items() if k not in {"keywords", "example_call"}}
            for tool in tools
        ],
        "sim_version": f"{SIM_REF} ({SIM_COMMIT})",
    }


def main() -> None:
    mcp.run(transport=os.environ.get("WOWSIMS_MCP_TRANSPORT", "streamable-http"))  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
