from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
import urllib.request
from typing import Any

from .database import DatabaseError
from .matching import normalize
from .presets import RACES

HOST = "worldofwarcraft.blizzard.com"
MAX_BYTES = 4 * 1024 * 1024
PATH = re.compile(
    r"^/(?:[a-z]{2}-[a-z]{2}/)?forever/(eu|us|kr|tw)/armory/character/([^/]+)/?$"
)
# Armory gear key -> sim equipment index.
SLOTS = {
    "head": 0, "neck": 1, "shoulder": 2, "back": 3, "chest": 4, "wrist": 5,
    "hand": 6, "waist": 7, "leg": 8, "foot": 9, "leftFinger": 10,
    "rightFinger": 11, "leftTrinket": 12, "rightTrinket": 13, "weapon": 14,
    "offhand": 15, "offHand": 15, "ranged": 16,
}  # fmt: skip
IGNORED = {"shirt", "tabard"}


class ArmoryError(DatabaseError):
    code = "ARMORY_UNAVAILABLE"


def parse_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    match = PATH.match(parts.path)
    if parts.scheme != "https" or parts.hostname != HOST or not match:
        raise DatabaseError(
            "Not a Forever armory character link. Expected "
            f"https://{HOST}/en-us/forever/eu/armory/character/<name>."
        )
    return f"https://{HOST}{parts.path}"


def _fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "wowsims-mcp"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if urllib.parse.urlsplit(response.geturl()).hostname != HOST:
                raise ArmoryError("The armory redirected to another site.")
            body = response.read(MAX_BYTES + 1)
    except OSError as exc:
        raise ArmoryError(f"Could not reach the armory page: {exc}") from exc
    if len(body) > MAX_BYTES:
        raise ArmoryError("The armory page is unexpectedly large.")
    return body.decode("utf-8", errors="replace")


def extract_character(html: str) -> dict[str, Any]:
    """Pull the character profile JSON the armory page embeds for its own UI."""
    for script in re.findall(r"<script[^>]*>(.*?)</script>", html, re.S):
        if '"gear"' not in script or '"character"' not in script:
            continue
        start = script.find("{", script.find("=") if "=" in script[:100] else 0)
        try:
            data, _ = json.JSONDecoder().raw_decode(script[start:])
        except ValueError:
            continue
        if isinstance(data.get("character"), dict) and "gear" in data["character"]:
            return data["character"]
    raise ArmoryError(
        "No character data found on the armory page. Check the link, and that "
        "the character exists and its profile is public."
    )


async def fetch_character(url: str) -> dict[str, Any]:
    return extract_character(await asyncio.to_thread(_fetch, parse_url(url)))


def talents_string(
    character: dict[str, Any], trees: list[dict[str, Any]]
) -> tuple[str, str, list[str]]:
    """Return the sim talent string, the tree with most points, and warnings."""
    ranks = {
        talent["id"]: talent["rank"]
        for spec in character.get("specs") or []
        for talent in spec.get("talents") or []
    }
    digits, spent, warnings = [], [], []
    for tree in trees:
        row = [
            ranks.pop(next((i for i in talent["ids"] if i in ranks), None), 0)
            for talent in tree["talents"]
        ]
        digits.append("".join(str(rank) for rank in row).rstrip("0"))
        spent.append(sum(row))
    if ranks:
        warnings.append(f"Armory talents not found in the sim trees: {sorted(ranks)}.")
    main = trees[spent.index(max(spent))]["name"] if any(spent) else ""
    return "-".join(digits).rstrip("-"), main, warnings


def to_sim(
    character: dict[str, Any], presets: dict[str, Any]
) -> tuple[str, str, str, list[dict[str, Any]], str, list[str]]:
    """Return class, preset spec id, race, 17 sim items, talents and warnings."""
    character_class = normalize(character["class"]["name"]).replace(" ", "_")
    race = normalize(character["race"]["name"]).replace(" ", "_")
    if race not in RACES:
        raise DatabaseError(f"Race {character['race']['name']!r} is not supported.")
    specs = [
        (key, preset)
        for key, preset in presets["specs"].items()
        if preset["class"] == character_class
    ]
    if not specs:
        raise DatabaseError(f"Class {character_class} has no supported sim preset.")
    talents, main_tree, warnings = talents_string(
        character, presets["trees"][character_class]
    )
    chosen = next(
        (
            (key, preset)
            for key, preset in specs
            if preset["spec"].split("_")[0] in normalize(main_tree)
        ),
        None,
    )
    if chosen is None:
        chosen = specs[0]
        warnings.append(
            f"Main talent tree {main_tree or 'none'!r} has no sim rotation; "
            f"using the {chosen[1]['spec']} rotation with the armory talents."
        )
    items: list[dict[str, Any]] = [{} for _ in range(17)]
    for key, gear in (character.get("gear") or {}).items():
        if key in IGNORED:
            continue
        if key not in SLOTS:
            warnings.append(f"Unknown gear slot {key!r} ignored.")
            continue
        item: dict[str, Any] = {"id": gear["id"]}
        enchants = gear.get("enchantments") or []
        if enchants:
            item["enchant"] = enchants[0]["enchantment_id"]
        bonuses = gear.get("bonus_list") or []
        if bonuses:
            item["randomSuffix"] = bonuses[0]
        items[SLOTS[key]] = item
    return character_class, chosen[0], race, items, talents, warnings
