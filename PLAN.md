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
2. **MCP server** (Python, FastMCP): validates input, builds the
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
| F1 | **Item lookup (first)**: find items and enchants by name, slot, quality; resolve names to IDs | `wowsims_search_items`, `wowsims_get_item`, `wowsims_search_enchants` | `assets/database/db.json` from `wowsims/forever` at the pinned ref (8,656 items, 246 enchants, consumables, zones, NPCs, encounters, as of 2026-10-26) | No |
| F2 | **Single sims**: DPS for a preset spec, with overrides (race, items by name or ID, talents) | `wowsims_list_specs`, `wowsims_simulate` | pinned `wowsimcli` | Yes |
| F3 | **Comparisons**: which racial/item/enchant is better, with noise flagging; stat weights | `wowsims_compare`, `wowsims_stat_weights` | pinned `wowsimcli` | Yes |
| F4 | **Characters**: store several characters per Discord user, with a default | `wowsims_save_character`, `wowsims_list_characters`, `wowsims_get_character`, `wowsims_set_default_character`, `wowsims_delete_character` | SQLite | No (sims then use them) |
| F5 | **Gear import**: exporter addon string or wowsims UI JSON into a character | `wowsims_save_character` (`source=exporter` or `sim_json`) | user paste | Yes (to validate) |
| F6 | **Item sources**: where an item drops, which boss/zone | `wowsims_get_item_sources` | zones/NPCs/encounters tables in `db.json`, if they link to items (to verify); otherwise the bot uses web search | No |
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
6. Do `db.json`'s zones/NPCs/encounters tables link to items (needed for F6)?
   (Coverage of `db.json` itself is trusted, see Decisions.)
7. Do the `gamedata` patch files (`items-changed.diff`, `CHANGES.md`) contain item
   names and IDs, and how big are they (needed for F7 and its runtime fetch)?

## Milestones

0. **Checks (read-only).** Open questions 1 and 2 from the repo. Pin the tag and
   commit SHA to use. Inspect `db.json` (done at a high level: items have id,
   name, slot type, armor type, quality, phase, ilvl, stats).
1. **F1 item lookup.** Scaffold the Python/FastMCP server (stateless streamable
   HTTP). Fetch `db.json` at the pinned ref at image build time, build an
   in-memory index with the misspelling-tolerant matcher (status levels
   exact/confident/ambiguous/suggestions/not_found, slot/quality filters) and
   its test benchmark. Tools: `wowsims_search_items`, `wowsims_get_item`,
   `wowsims_search_enchants`. No Go toolchain or sim binary
   needed. Containerise, register in `openclaw.json`, add a `TOOLS.md` section,
   restart the gateway, test from Discord.
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
7. **F6 item sources**: only if `db.json`'s zones/NPCs/encounters link to items
   (check first). **F7 patch changes**: runtime fetch from `wowsims/gamedata`
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
