# wowsims-mcp: plan

Status: planning only. Nothing is built yet.

## Goal

Give the openclaw Discord bot (Lockbot) a local MCP server that runs
[wowsims/forever](https://github.com/wowsims/forever) simulations, so it can
answer "which racial / which gear is better" with a sim result instead of a
guess. Users link their characters once; the bot sims them on request.

## What we know (checked 2026-10-26)

- `wowsims/forever` exists ("World of Warcraft Forever simulations"), Go, MIT,
  updated 2026-10-26. The README does not say which expansion ruleset it is
  based on or which classes/specs are supported.
- Headless CLI: `go run ./cmd/wowsimcli sim --infile input.json`. Input is a
  `RaidSimRequest` in protojson, output is the `RaidSimResult` on stdout. Old
  input files are not migrated after proto changes.
- Local server: `make host` serves the UI on :8080. `make rundevserver` runs the
  `wowsimforever` server on :3333.
- The README mentions prebuilt zips, but the repo has no GitHub releases. It has
  a `Dockerfile` and `docker-compose.yml`.
- `wowsims/exporter` addon: `/wse export` opens a copyable window with gear,
  enchants, talents (and glyphs/runes). Output format and Forever support are
  not confirmed.
- armorywowforever.com: lookup by region, game mode and name; character pages at
  `/c/<flavor>/<region>/<server>/<name>`. Covers TBC Anniversary only for now;
  the Forever armory opens at launch (4 Nov 2026) once Blizzard grants API
  access. Forever has no realms, characters have two-part names.
  `robots.txt` has `Disallow: /api/`, so we do not call its JSON endpoints.

## How we get wowsims (decision)

- `wowsims/forever` has **no GitHub releases** (checked 2026-10-26, web and API),
  even though the README mentions prebuilt zips. It does have git tags
  (`v0.0.138` to `v0.0.140`, auto-incrementing).
- So: **build `wowsimcli` from source at a pinned ref** in a Docker build stage.
  Clone `wowsims/forever`, check out the pinned tag, pin the exact commit SHA
  behind it (tags are auto-generated), build `./cmd/wowsimcli`. The final image
  contains only the binary. Upgrading means deliberately changing the SHA.
- Not a git submodule. Only reconsider if we need the `.proto` files or item
  data in our tree (e.g. to generate Python types); even then prefer fetching
  them at build time at the same pinned ref.
- Pinning matters: old sim input files are not migrated after proto changes.
- License: MIT, but the README asks for a user-visible link back to the project.
  Credit wowsims in our README and in what the bot shows.
- To verify: whether the build needs the protobuf toolchain and generated files
  (`.pb.go`), and the Go version required.

## Design

### Components

1. **Sim runner**: wowsimcli binary built from source at a pinned ref (see
   "How we get wowsims"), invoked by the MCP server with a generated input JSON.
2. **MCP server** (**Python**, decided 2026-10-26; FastMCP, `uv`, pytest, same
   layout as `~/git/vunit-mcp`: `pyproject.toml`, `src/wowsims_mcp/`, `tests/`;
   the sim is a Go subprocess, so the wrapper's language is independent of it):
   validates input, builds the
   `RaidSimRequest`, runs the sim, returns a compact summary (DPS, stat
   weights, comparison deltas).
3. **Storage**: SQLite on a Docker volume (e.g. `data/presets.db`), owned by the
   MCP server. The bot only reaches it through tools.
4. **Deployment**: container next to the other MCP containers; registered in
   `openclaw.json`; a short section in the bot's `TOOLS.md` saying when to use it.

### Data model

Keyed by Discord user ID plus character, not by user alone, because one user
can have several characters.

- `characters`: discord_user_id, name (two-part), game_mode, spec, settings_json
  (sim input), raw_import (what the user pasted), is_default, updated_at.
- Exactly one default per user. The user can change it ("byt till min rogue").

### Features

The full interface (arguments, return shapes, errors, limits, annotations) is
in [docs/INTERFACE.md](docs/INTERFACE.md). Features, **in build order**; each is
a milestone that is useful on its own:

| # | Feature | Tools | Data source | Needs the sim binary? |
| --- | --- | --- | --- | --- |
| F1 | **Item lookup (first)**: misspelling-tolerant search with probabilities; filter/browse without a name; full item card (stats, effects, set, restrictions, sources); loot by boss or zone; random-suffix variants; sets; side-by-side compare; enchants and consumables; Wowhead links. Details in "F1 feature set" below | `wowsims_search_items`, `wowsims_get_item`, `wowsims_get_loot`, `wowsims_get_set`, `wowsims_compare_items`, `wowsims_search_enchants`, `wowsims_search_consumables`, `wowsims_get_wowhead_link` | `assets/database/db.json` from `wowsims/forever` at the pinned ref (8,656 items, 246 enchants, consumables, zones, NPCs, encounters, as of 2026-10-26) | No |
| F2 | **Single sims**: DPS for a preset spec, with overrides (race, items by name or ID, talents) | `wowsims_list_specs`, `wowsims_simulate` | pinned `wowsimcli` | Yes |
| F3 | **Comparisons**: which racial/item/enchant is better, with noise flagging; stat weights | `wowsims_compare`, `wowsims_stat_weights` | pinned `wowsimcli` | Yes |
| F4 | **Characters**: store several characters per Discord user, with a default | `wowsims_save_character`, `wowsims_list_characters`, `wowsims_get_character`, `wowsims_set_default_character`, `wowsims_delete_character` | SQLite | No (sims then use them) |
| F5 | **Gear import**: exporter addon string or wowsims UI JSON into a character | `wowsims_save_character` (`source=exporter` or `sim_json`) | user paste | Yes (to validate) |
| F6 | **Item sources**: merged into F1 (`wowsims_get_item` card and `wowsims_get_loot`); `db.json` has source data for 2,875 items and all 625 drop sources link to a named boss and zone | see F1 | `db.json` | No |
| F7 | **Patch changes**: what changed for an item/spell in recent patches | `wowsims_get_patch_changes` | `wowsims/gamedata` (`patches/<version>/CHANGES.md`, `items-changed.diff`), **fetched at runtime from the public repo, never bundled** (see Decisions) | No |
| F8 | **Character lookup by name** (after 4 Nov): fetch gear for a character without a paste | `wowsims_lookup_character` | an allowed source only: Blizzard's API, or a supported route agreed with the armorywowforever.com owner. Never its `/api/` (robots.txt) | Yes (to validate) |
| F9 | **Raid-level sims**: buffs and debuffs from other classes in the raid | extend `wowsims_simulate` / `wowsims_compare` | pinned `wowsimcli` | Yes |

F1 must be bulletproof against misspellings: the bot should always either find
the item or ask a good "menade du X?" question, never silently pick the wrong
one and never answer with a bare "not found". Design, status levels and the
acceptance benchmark are in the "Matching and misspellings" section of
docs/INTERFACE.md. A prototype against the real `db.json` found the intended
item first for 93-96% of generated typos and in the top five for 98%.

Caveat found while prototyping: `db.json` holds only phase 1 items (all 8,656),
and some well-known Classic items (Ashkandi, Bloodfang, Nightslayer) are not in
it. `not_found` therefore means "not in the sim database", never "no such item".

### F1 feature set

What `db.json` supports (checked 2026-10-26): 8,656 items, of which 2,875 have
source data (1,943 crafted, 625 drops, 307 reputation; all 625 drops link to a
named NPC and zone), 1,058 in 186 sets, 1,433 with class restrictions, 689 with
on-use or proc effects, 1,641 with random-suffix options; plus 436 consumables
and 246 enchants. Items without source data (e.g. Thunderfury) report
"source unknown", never "does not drop".

Each item below is part of F1 and has its own acceptance tests:

1. **Misspelling-tolerant search with probabilities** (the matcher in
   INTERFACE.md): `wowsims_search_items(query)`.
2. **Browse and filter without a name**: the same tool with `query` optional and
   filters for class, slot, weapon type, quality, item-level range, faction,
   profession, set, and has-proc/has-on-use. Example: "rogue daggers ilvl 60+".
3. **Full item card**: `wowsims_get_item` returns stats, weapon speed, on-use
   and proc effects (cooldown, ppm), set, unique flag, class/faction/profession
   restrictions, and random-suffix options.
4. **Item sources** inside the card: drop (boss, zone, difficulty), crafted
   (profession), reputation (faction), or "unknown".
5. **Loot by boss or zone**: `wowsims_get_loot(boss_or_zone)`, the reverse lookup
   ("what drops from Edwin VanCleef"); the name is matched with the same fuzzy
   resolver and probabilities.
6. **Random-suffix variants**: "Cloak of the Eagle" resolves to the base item
   plus the suffix (the matcher splits a trailing "of the X" and checks it against
   the suffix table), and the result carries `suffix`.
7. **Sets**: `wowsims_get_set(name)` lists the pieces, class, and which pieces
   an item belongs to (186 sets).
8. **Side-by-side compare**: `wowsims_compare_items(items[])` shows stat
   differences, item level, effects and restrictions, before the sim exists.
9. **Consumables and enchants**: `wowsims_search_consumables` (436: potions,
   flasks, food, with effects and class restrictions) and `wowsims_search_enchants`
   (246, by slot); same fuzzy resolver.
10. **Best items for a slot** (after F3): rank items for a slot by the stat
    weights from `wowsims_stat_weights`. Not part of the first F1 release.
11. **Wowhead links**: every item, enchant, set, consumable, NPC and zone result
    carries a `wowhead_url`, and `wowsims_get_wowhead_link(kind, id_or_name)`
    builds one for any of them (kinds: item, spell, npc, zone, item-set).
    - We only **generate links**; we never fetch Wowhead (its `robots.txt`
      disallows AI crawlers, and the bot does not need the content).
    - Base path is configurable (`WOWHEAD_BASE`). Probed 2026-10-26:
      `https://www.wowhead.com/forever/item=<id>` answers 403 to a scripted
      request while unrelated paths answer 404, so the route likely exists but is
      **unverified**; check it in a browser before relying on it. Fallback is the
      closest era path (`/classic/`), clearly labelled as such.
    - Links go out wrapped in `<...>` to suppress Discord embeds when several are
      posted (per the bot's `AGENTS.md`).
    - Open check: Wowhead item IDs are assumed to equal the sim's IDs (same
      client data); verify with a handful of items.

### Keeping the tool count manageable

F1 is 8 tools (search, get, loot, set, compare, enchants, consumables, link), and
the whole v1 is about 17. The openclaw `discord` agent already carries about 45
tools, which is a lot for a local model. Three measures, all in the plan (no
single-dispatcher tool such as `wowsims_call(tool, args)`: the client would see no
argument schemas, small models would guess arguments, and we would lose per-tool
validation and annotations):

1. **Per-agent allowlist.** The `discord` agent has an explicit `tools.allow` list
   in `openclaw.json` (wildcards such as `warcraftlogs__*` are supported), so new
   tools are invisible to it until added. Expose to the Discord agent only what it
   needs: `wowsims_search_items`, `wowsims_get_item`, `wowsims_get_loot`,
   `wowsims_get_wowhead_link`, `wowsims_simulate`, `wowsims_compare`, and
   `wowsims_help`. Everything else (character management, sets, consumables,
   enchants, compare_items, ...) stays hidden from it, or goes to another agent.
   Revisit the list per milestone. Allowlist edits hot-reload, but a gateway
   restart is needed after the MCP container changes.
2. **openclaw's `tool_search`.** The `discord` agent's allowlist already includes
   `tool_search`. Step 0 checks how it behaves (does it hide tool definitions
   until they are searched for?). If it loads definitions on demand, allow the
   whole `wowsims__*` set and let the agent find tools through it; if not, rely
   on measures 1 and 3.
3. **`wowsims_help(task?)`**, a small read-only tool in our server. Given a plain
   description ("find where an item drops", "compare two racials") it returns the
   matching tool names, a one-line description and an example call; with no
   argument it returns a short index of all tools. It exists so the bot can
   discover the hidden tools without every definition sitting in the prompt, and
   it still helps if `tool_search` does not do what we hope. Keep every tool
   description short.

How F1 feeds the rest: once F1 exists, every `items`/`enchants` override in F2,
F3 and F5 accepts a name as well as an ID. An exact match resolves; an
ambiguous one returns `INVALID_OVERRIDE` with candidates so the bot asks the
user which one.

Scope note: the server keeps the name `wowsims_mcp` while the features all come
from the wowsims build and data (F1-F5, F9). F6 uses the same `db.json`; F8
pulls in another source. Revisit splitting F8 into a second server, or renaming,
if it grows.

Decisions (2026-10-26):
- `db.json` is trusted as the complete item/enchant source for the pinned
  version. No separate coverage check.
- `wowsims/gamedata` is assumed to have no license. We may use it, but we do
  **not bundle it**: nothing from it is committed to this repo or baked into the
  image. F7 fetches the files it needs at runtime from the public repo (raw
  GitHub URLs, pinned to nothing since the data tracks live patches), and keeps
  a short-lived cache on the data volume only, which is git-ignored. The bot
  quotes short results (what changed), never dumps the files. If a license is
  later added or the owners object, remove F7.
- No Swedish aliases for item names. Names are matched as they appear in
  `db.json`; the bot asks the user when a name is ambiguous or not found.

Character resolution (F4): explicit name, else the user's default, else if the
user has several and no default the bot asks which one (per the
ask-when-unclear rule in `SOUL.md`). Anyone can sim a character by name without
owning it.

### Getting gear

| Source | Status |
| --- | --- |
| Exporter addon (`/wse export`), pasted to the bot | Preferred. Need to confirm Forever support and the output format; export string is not plain sim JSON, so an import step is needed. |
| Settings JSON exported from the wowsims web UI | Fallback, already in the CLI's format. |
| armorywowforever.com | Not before 4 Nov. Do not use `/api/` (robots.txt). Ask the site owner (Discord link on the page) for a supported way, or use Blizzard's character API directly once Forever access exists. |
| Existing `wow-armory` MCP | Classic/TBC characters only. |
| Gear typed in chat | Last resort, unreliable. |

## Open questions

1. Which ruleset does `wowsims/forever` simulate, and which specs does it
   support? (Check `sim/` and `ui/`.)
2. Does the exporter addon support Forever, and what is its output format?
3. Is the sim accurate for the cases that triggered this (racials, haste
   effects)? Validate with one known case.
4. How do we turn an export string into a `RaidSimRequest` without
   reimplementing the whole UI importer?
5. Where does the project run (container on this box, same network as the other
   MCP servers)?
6. Is the Wowhead Forever route (`/forever/item=<id>`) valid, and do Wowhead IDs
   match the sim's item IDs? (Check in a browser.) The question of whether
   `db.json` links items to bosses is answered: yes for all 625 drop sources.
   (Coverage of `db.json` itself is trusted, see Decisions.)
7. Do the `gamedata` patch files (`items-changed.diff`, `CHANGES.md`) contain item
   names and IDs, and how big are they (needed for F7 and its runtime fetch)?

## Milestones

0. **Checks (read-only).** Open questions 1 and 2 from the repo. Check how
   openclaw's `tool_search` works (docs or source) and whether per-agent
   `tools.allow` also applies to MCP tools added later. Pin the tag and
   commit SHA to use. Inspect `db.json` (done at a high level: items have id,
   name, slot type, armor type, quality, phase, ilvl, stats).
1. **F1 item lookup.** Scaffold the Python/FastMCP server (stateless streamable
   HTTP). Fetch `db.json` at the pinned ref at image build time, build an
   in-memory index with the misspelling-tolerant matcher (status levels
   exact/confident/ambiguous/suggestions/not_found, slot/quality filters) and
   its test benchmark. Tools: the full F1 feature set above (items 1-9 and 11;
   item 10 waits for F3). Build in this order inside the milestone: search and
   matcher, item card with sources, filters, loot, suffixes, sets, compare,
   consumables/enchants, Wowhead links. No Go toolchain or sim binary
   needed. Include `wowsims_help`. Containerise, register in `openclaw.json`, add
   only the Discord-needed tools to the `discord` agent's `tools.allow` (see
   "Keeping the tool count manageable"), add a `TOOLS.md` section, restart the
   gateway, test from Discord.
2. **Sim build.** Clone `wowsims/forever` at the pinned ref, build `wowsimcli`
   (note the toolchain it needs), run one sim by hand with a preset JSON. Add the
   build stage to the Dockerfile.
3. **F2 single sims.** `wowsims_list_specs`, `wowsims_simulate` with preset specs
   and overrides; item names resolved through F1.
4. **F3 comparisons.** `wowsims_compare`, `wowsims_stat_weights`; validate against
   one known case (racials, haste effects).
5. **F4 characters.** SQLite storage and the character tools; `owner` resolution.
6. **F5 gear import.** Exporter string or UI JSON, whichever step 0 confirms,
   with warnings for anything unmapped.
7. **F6 item sources**: done inside F1 (see above). **F7 patch changes**: runtime fetch from `wowsims/gamedata`
   with a short-lived volume cache, not bundled (see Decisions); first confirm
   the diff files contain item names and IDs, and write the parser.
8. **F8 character lookup by name**: after 4 Nov, and only via an allowed source.
9. **F9 raid-level sims**: last, if single-character sims prove useful.

Each milestone ends with a container rebuild, a gateway restart, and a test in
Discord.

## Notes

- Recreating the MCP container keeps the data (volume), but openclaw needs a
  gateway restart afterwards.
- Stored data is Discord user IDs and game gear only.
