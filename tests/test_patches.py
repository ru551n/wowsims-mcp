from __future__ import annotations

import json

import pytest

from wowsims_mcp import patches

CHANGES = """# Patch: 1.60.1.70245

## Spells

### Druid: 0 added, 0 removed, 1 changed
- changed 770 Faerie Fire (Rank 1) · balance

## Items

1 added, 0 removed, 1 changed.

- added 9415 Grimlok's Tribal Vestments
- changed 872 Rockslicer
"""
DIFF = """--- 872 Rockslicer
+++ 872 Rockslicer
@@ -1,9 +1,9 @@
 872 Rockslicer
-stats     +10 strength
+stats     +7 strength, +7 nature resistance
"""


def test_parse_changes_tracks_kind() -> None:
    changes = patches.parse_changes(CHANGES)
    assert [(c["kind"], c["change"], c["id"]) for c in changes] == [
        ("spell", "changed", 770),
        ("item", "added", 9415),
        ("item", "changed", 872),
    ]


def test_parse_diff_before_after() -> None:
    assert patches.parse_diff(DIFF)[872] == {
        "before": ["stats     +10 strength"],
        "after": ["stats     +7 strength, +7 nature resistance"],
    }


@pytest.mark.asyncio
async def test_get_patch_changes_enriches_with_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(url: str, name: str) -> str:
        if name == "tree.json":
            return json.dumps(
                {"tree": [{"path": "patches/1.60.1.70245/patch/CHANGES.md"}]}
            )
        return DIFF if name.endswith(".diff") else CHANGES

    monkeypatch.setattr(patches, "_cached", fake)
    result = await patches.get_patch_changes("rockslicer")
    assert result["has_more"] is False
    [change] = result["changes"]
    assert change["patch"] == "1.60.1.70245"
    assert change["after"] == ["stats     +7 strength, +7 nature resistance"]
    assert len((await patches.get_patch_changes("9415"))["changes"]) == 1
    with pytest.raises(ValueError):
        await patches.get_patch_changes(since_patch="9.9.9.9")
