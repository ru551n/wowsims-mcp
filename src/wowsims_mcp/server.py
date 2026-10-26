from __future__ import annotations

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
    return {
        "ok": False,
        "code": "ITEM_NOT_FOUND",
        "message": str(exc),
        "next_step": "Call wowsims_search_items and ask the user to choose "
        "if several candidates remain.",
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
) -> dict[str, Any]:
    """Get an item's stats, effects, restrictions, set, and known sources."""
    try:
        result = get_database().item_card(get_database().resolve(item))
        result["ok"] = True
        result["sim_version"] = SIM_COMMIT
        return result
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
