from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO = "wowsims/gamedata"
TREE_URL = f"https://api.github.com/repos/{REPO}/git/trees/main?recursive=1"
RAW_URL = f"https://raw.githubusercontent.com/{REPO}/main/"
CACHE_TTL_S = 3600
DEFAULT_BUILDS = 3
LINE = re.compile(r"^- (added|removed|changed) (\d+) (.+?)(?: · .+)?$")


class SourceUnavailable(RuntimeError):
    code = "SOURCE_UNAVAILABLE"


def _cache_dir() -> Path:
    import os

    return Path(os.environ.get("WOWSIMS_CACHE_DIR", "data/patch-cache"))


def _fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "wowsims-mcp"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except OSError as exc:
        raise SourceUnavailable(f"Could not fetch {url}: {exc}") from exc


async def _cached(url: str, name: str) -> str:
    path = _cache_dir() / name
    if path.is_file() and time.time() - path.stat().st_mtime < CACHE_TTL_S:
        return path.read_text(encoding="utf-8")
    try:
        text = await asyncio.to_thread(_fetch, url)
    except SourceUnavailable:
        if path.is_file():  # stale beats nothing
            return path.read_text(encoding="utf-8")
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


async def _directories() -> list[str]:
    tree = json.loads(await _cached(TREE_URL, "tree.json"))
    dirs = set()
    for entry in tree.get("tree", []):
        parts = entry["path"].split("/")
        if parts[0] == "patches" and len(parts) == 4 and parts[3] == "CHANGES.md":
            dirs.add(f"{parts[1]}/{parts[2]}")

    def key(directory: str) -> tuple[tuple[int, ...], str]:
        build, sub = directory.split("/")
        return tuple(int(p) for p in build.split(".") if p.isdigit()), sub

    return sorted(dirs, key=key, reverse=True)


def parse_changes(text: str) -> list[dict[str, Any]]:
    kind = None
    changes = []
    for line in text.splitlines():
        if line.startswith("## "):
            kind = {"## Items": "item", "## Spells": "spell"}.get(line.strip())
            continue
        match = LINE.match(line)
        if kind and match:
            action, ident, name = match.groups()
            changes.append(
                {"kind": kind, "change": action, "id": int(ident), "name": name}
            )
    return changes


def parse_diff(text: str) -> dict[int, dict[str, list[str]]]:
    """Map id -> before/after lines of a unified diff of item or spell cards."""
    result: dict[int, dict[str, list[str]]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("--- "):
            ident = line[4:].split(" ", 1)[0]
            current = result.setdefault(
                int(ident) if ident.isdigit() else -1, {"before": [], "after": []}
            )
        elif (
            current is not None
            and line[:1] in "+-"
            and not line.startswith(("+++", "---"))
        ):
            current["before" if line[0] == "-" else "after"].append(line[1:].strip())
    return result


def _matches(change: dict[str, Any], query: str) -> bool:
    return str(change["id"]) == query or query.casefold() in change["name"].casefold()


async def get_patch_changes(
    item_or_spell: str | None = None,
    since_patch: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    directories = await _directories()
    if since_patch:
        wanted = [d for d in directories if d.split("/")[0] >= since_patch]
        if not wanted:
            raise ValueError(f"No patch build at or after {since_patch!r}.")
    else:
        builds = list(dict.fromkeys(d.split("/")[0] for d in directories))
        wanted = [d for d in directories if d.split("/")[0] in builds[:DEFAULT_BUILDS]]
    texts = await asyncio.gather(
        *(
            _cached(f"{RAW_URL}patches/{d}/CHANGES.md", f"{d}/CHANGES.md")
            for d in wanted
        )
    )
    found = []
    for directory, text in zip(wanted, texts, strict=True):
        for change in parse_changes(text):
            if item_or_spell is None or _matches(change, item_or_spell.strip()):
                found.append({"patch": directory.replace("/patch", ""), **change})
    diffs: dict[tuple[str, str], dict[int, dict[str, list[str]]]] = {}
    for change in found:
        if change["change"] != "changed":
            continue
        directory = (
            change["patch"] if "/" in change["patch"] else change["patch"] + "/patch"
        )
        file = "items-changed.diff" if change["kind"] == "item" else "spells.diff"
        if (directory, file) not in diffs:
            try:
                text = await _cached(
                    f"{RAW_URL}patches/{directory}/{file}", f"{directory}/{file}"
                )
            except SourceUnavailable:
                text = ""
            diffs[directory, file] = parse_diff(text)
        detail = diffs[directory, file].get(change["id"])
        if detail:
            change["before"] = detail["before"][:12]
            change["after"] = detail["after"][:12]
    return {
        "changes": found[:limit],
        "has_more": len(found) > limit,
        "searched_builds": sorted({d.split("/")[0] for d in wanted}),
    }
