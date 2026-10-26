from __future__ import annotations

import json
import os
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .constants import SIM_COMMIT, SIM_REF
from .database import DatabaseError, GameDatabase, make_filters

mcp = FastMCP(
    "wowsims_mcp",
    instructions=(
        "Look up World of Warcraft items in the pinned wowsims database. "
        "Search accepts misspellings and returns probabilities; ask the user "
        "when the result is ambiguous. Not found means absent from this database, "
        "not that the item does not exist. Simulation is not implemented yet."
    ),
    host=os.environ.get("WOWSIMS_MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("WOWSIMS_MCP_PORT", "8000")),
    stateless_http=True,
    json_response=True,
)
_database: GameDatabase | None = None
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
        "code": "INVALID_INPUT",
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
