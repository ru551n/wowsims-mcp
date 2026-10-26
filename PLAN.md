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
- Prebuilt zips (Windows/macOS/Linux amd64) on the Releases page. The repo has a
  `Dockerfile` and `docker-compose.yml`.
- `wowsims/exporter` addon: `/wse export` opens a copyable window with gear,
  enchants, talents (and glyphs/runes). Output format and Forever support are
  not confirmed.
- armorywowforever.com: lookup by region, game mode and name; character pages at
  `/c/<flavor>/<region>/<server>/<name>`. Covers TBC Anniversary only for now;
  the Forever armory opens at launch (4 Nov 2026) once Blizzard grants API
  access. Forever has no realms, characters have two-part names.
  `robots.txt` has `Disallow: /api/`, so we do not call its JSON endpoints.

## Design

### Components

1. **Sim runner**: wowsimcli binary (release build or built from the repo's
   Dockerfile) invoked by the MCP server with a generated input JSON.
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

### Tools (draft)

- `link_character(user, name, import_data)`: parse an export, store it.
- `list_characters(user)`, `set_default(user, name)`, `delete_character(user, name)`.
- `simulate(user?, character?, overrides?)`: run a sim. Overrides cover race,
  single items, talents, so "same gear but Troll" needs no re-import.
- `compare(user?, character?, variants[])`: run several variants, return deltas.
- `stat_weights(user?, character?)`.
- `supported_specs()`.
- Anyone can sim a character by name without owning it.

Character resolution: explicit name, else the user's default, else if the user
has several and no default the bot asks which one (per the ask-when-unclear
rule in `SOUL.md`).

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

## Steps

1. Answer open questions 1 and 2 from the repo (read-only).
2. Download the Linux release, run one sim by hand with a preset JSON.
3. Write the MCP server with `simulate` and `supported_specs` only, no storage.
4. Add SQLite storage and the character tools.
5. Add import (exporter string, or UI JSON, whichever step 1 confirms).
6. Containerise, register in openclaw, add to `TOOLS.md`, restart the gateway
   (stale MCP sessions otherwise).
7. After 4 Nov: character lookup by name once an allowed data source exists.

## Notes

- Recreating the MCP container keeps the data (volume), but openclaw needs a
  gateway restart afterwards.
- Stored data is Discord user IDs and game gear only.
