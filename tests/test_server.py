from __future__ import annotations

import pytest

from wowsims_mcp import server
from wowsims_mcp.database import GameDatabase


@pytest.fixture(autouse=True)
def use_fixture_database(
    database: GameDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "_database", database)


@pytest.mark.asyncio
async def test_mcp_lists_annotated_tools() -> None:
    tools = await server.mcp.list_tools()
    assert {tool.name for tool in tools} == {
        "wowsims_search_items",
        "wowsims_get_item",
        "wowsims_get_loot",
        "wowsims_get_set",
        "wowsims_compare_items",
        "wowsims_search_enchants",
        "wowsims_search_consumables",
        "wowsims_get_wowhead_link",
        "wowsims_list_specs",
        "wowsims_simulate",
        "wowsims_compare",
        "wowsims_list_characters",
        "wowsims_get_character",
        "wowsims_save_character",
        "wowsims_set_default_character",
        "wowsims_delete_character",
        "wowsims_update_character",
        "wowsims_stat_weights",
        "wowsims_get_patch_changes",
        "wowsims_help",
    }
    writes = {
        "wowsims_save_character",
        "wowsims_set_default_character",
        "wowsims_delete_character",
        "wowsims_update_character",
    }
    assert all(
        tool.annotations and tool.annotations.readOnlyHint == (tool.name not in writes)
        for tool in tools
    )
    search = next(tool for tool in tools if tool.name == "wowsims_search_items")
    assert search.inputSchema["properties"]["limit"]["maximum"] == 25
    assert "class" in search.inputSchema["properties"]


@pytest.mark.asyncio
async def test_mcp_search_and_get_item() -> None:
    _, result = await server.mcp.call_tool(
        "wowsims_search_items", {"query": "thunderfuri"}
    )
    assert result["candidates"][0]["id"] == 19019
    _, result = await server.mcp.call_tool("wowsims_get_item", {"item": 19019})
    assert result["ok"] is True
    assert result["name"].startswith("Thunderfury")


@pytest.mark.asyncio
async def test_mcp_input_validation() -> None:
    with pytest.raises(Exception, match="limit"):
        await server.mcp.call_tool("wowsims_search_items", {"limit": 100})
