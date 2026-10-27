# MCP interface design

Status: draft. Field names for gear/talents/overrides are provisional until we
have run a real sim and seen the `RaidSimRequest` (PLAN.md, step 2).

## Principles

The caller is an LLM in a Discord chat (Lockbot, running on a local Qwen model or
GPT), answering casual questions from non-technical users. So:

- **Few tools, simple arguments.** About 18 tools in v1 (F1 has 8, plus
  `wowsims_help`, F2-F5 the rest), plus a few provisional ones later
  (best-items-for-slot, F7, F8). The Discord agent already carries about 45 tools,
  so it only gets a subset through its `tools.allow` list, descriptions are kept
  short, and `wowsims_help` plus openclaw's `tool_search` cover discovery of the
  rest. No single dispatcher tool. The model passes names and short
  strings, never protobuf-shaped blobs. We build the `RaidSimRequest`.
- **Resolve, don't interrogate.** The server resolves "which character" and says
  what it resolved (`resolved_character`), so the bot can mention it.
- **Errors that tell the next step.** When something is ambiguous or missing, the
  error says exactly what to ask the user (and lists candidates), matching the
  bot's "search, then ask what's still unclear" rule.
- **Small outputs.** Results are compact JSON plus a one-line `summary` the bot
  can quote. Raw sim output is never returned.
- **Honest about the sim.** Every result carries `sim_version` and
  `ruleset_note`, and results are labelled as sim output, not logs.
- **Stateless.** Streamable HTTP in stateless JSON mode: no `mcp-session-id`, so
  recreating this container does not leave openclaw holding dead sessions (the
  stale-session problem from the Plex/Overseerr MCPs).

## Naming and transport

- Server: `wowsims_mcp` (Python, FastMCP). Tools prefixed `wowsims_`.
- Transport: streamable HTTP, stateless JSON, on the Docker network next to the
  other MCP containers. Bind to the container network, not the host.
- Identity: `owner` is the Discord user ID as a string (openclaw passes `senderId`
  on every message). It is a namespace, not a credential: characters are not
  secret, anyone may sim anyone's character by name.

## Character references

A character is identified by `owner` + `name` (two-part Forever name, matched
case-insensitively). Every sim/read tool takes a **`character`** string that
may be:

- `"Name-Part"`: look up by name for the given `owner`, else globally if unique.
- omitted: the `owner`'s default character.

Resolution rules, in order:

1. Explicit name matches one character: use it.
2. No name: use the owner's default.
3. No name, no default, several characters: error `AMBIGUOUS_CHARACTER` with
   `candidates` (the bot asks the user which one).
4. Owner has no characters: error `NO_CHARACTERS` with the import instructions.

## Tools

All tools return `{ "ok": true, ... }` or an error (below). `owner` is required
wherever a default may need resolving. Tools are grouped by feature; the feature
numbers (F1-F9) and build order are in PLAN.md.

### Tool discovery

**`wowsims_help`**: find the right tool without every definition in the prompt
(see "Keeping the tool count manageable" in PLAN.md).
- args: `task?` (plain-language description, e.g. "where does an item drop")
- returns: with `task`: `{matches: [{tool, description, example_call, visible_to_you?}]}` (best first, at most 3);
  without: `{index: [{tool, one_line}]}` for all tools.
- matching is simple keyword and similarity scoring over each tool's description
  and a short list of example phrases kept next to the tool definition; no LLM.
- the response notes when a matching tool is not exposed to the calling agent
  (when the server can tell), so the bot can say it cannot do that instead of
  guessing.

### Item lookup (F1, built first)

Backed by the sim's own database (`db.json` at the pinned ref), loaded into an
in-memory index at startup. Read-only, no sim binary needed.

**`wowsims_search_items`**
Find items by name, tolerant of misspellings (see "Matching and misspellings"
below). For "vad heter den där trinketen", and for resolving names before an
override.
- args: `query?` (name or part of it; omit to browse by filters only),
  `slot?`, `min_quality?`, `armor_type?`, `weapon_type?`, `class?`, `faction?`,
  `profession?`, `set?`, `ilvl_min?`, `ilvl_max?`, `has_proc?`, `has_on_use?`,
  `limit?` (default 5, max 25), `offset?`
- with `query` the result is the probability list below; without `query` it is a
  plain filtered list ordered by item level (descending) with `total`,
  `has_more`, `next_offset`, and no probabilities.
- a trailing "of the <suffix>" in the query (e.g. "Cloak of the Eagle") is split
  off and matched against the random-suffix table; the candidate then carries
  `suffix`.
- returns:
  ```json
  {
    "ok": true,
    "status": "exact | confident | ambiguous | suggestions | not_found",
    "query": "thunderfuri",
    "candidates": [
      {"id": 19019, "name": "Thunderfury, Blessed Blade of the Windseeker", "slot": "...", "ilvl": 0, "quality": "...", "probability": 0.72, "same_name_count": 1}
    ],
    "none_of_these": 0.28,
    "summary": "Thunderfury, Blessed Blade of the Windseeker: 72% likely; 28% it is not in the database."
  }
  ```
  **The LLM decides from the probabilities.** `candidates` is ordered best first
  (up to `limit`); every `probability` is the chance that this item is the one
  the user meant; `none_of_these` is the chance that the intended item is not in
  the list or not in the database at all. Candidates plus `none_of_these` sum to
  1. `status` is only an advisory label derived from those numbers (so the
  thresholds live in one place); the bot is free to ignore it.

**`wowsims_get_item`**: the full item card.
- args: `item` (ID, or a name resolved by the fuzzy matcher), `suffix?`
- returns: `{id, name, slot, armor_type, weapon_type?, hand_type?, weapon_speed?, quality, ilvl, phase, stats: {...}, effects: [{name, on_use?: {cooldown_s}, proc?: {ppm}, duration_s?}], set?: {id, name}, unique, restrictions: {classes?, faction?, profession?}, suffix_options?: [...], sources: [...], wowhead_url}`
- `sources` entries: `{type: "drop", boss, zone, difficulty?}`,
  `{type: "crafted", profession}`, `{type: "reputation", faction, standing?}`,
  or `[{type: "unknown"}]` when the database has no source data (this means
  "unknown", not "does not drop").
- an unresolved name returns the same probability list as search, as an error.

**`wowsims_get_loot`**: the reverse lookup.
- args: `boss_or_zone` (fuzzy-matched, with probabilities like item search),
  `slot?`, `class?`, `limit?`, `offset?`
- returns: `{resolved: {type: "boss"|"zone", id, name, zone?, probability}, items: [{id, name, slot, ilvl, quality}], total, has_more, next_offset, wowhead_url}`

**`wowsims_get_set`**
- args: `name` (fuzzy-matched)
- returns: `{id, name, class?, pieces: [{id, name, slot, ilvl, sources}], wowhead_url}`; if given an item, also `contains_item`.

**`wowsims_compare_items`**
- args: `items` (2-4: IDs or names), `suffixes?`
- returns: `{items: [{id, name, slot, ilvl, quality}], stat_table: {stat: [values...]}, differences: [...], effects: [[...]], restrictions: [[...]], summary}`
- error `SLOT_MISMATCH` (warning, not failure) when the slots differ.

**`wowsims_search_enchants`**
- args: `query?`, `slot?`, `limit?`
- returns: `{enchants: [{id, name, slots, stats, probability?}], total, has_more, none_of_these?}` (with a query: probability list like item search)

**`wowsims_search_consumables`**
- args: `query?`, `type?` (potion, flask, food, ...), `class?`, `limit?`
- returns: `{consumables: [{id, name, type, level, stats, effects, probability?}], total, has_more, none_of_these?}`

**`wowsims_get_wowhead_link`**
- args: `kind` (`item`, `spell`, `npc`, `zone`, `item-set`), `id_or_name`
- returns: `{url, kind, id, name, verified: false}`; the base path comes from
  `WOWHEAD_BASE`. Links are generated, never fetched. A name is resolved with
  the fuzzy matcher, so the result can be a probability list as an error.
- every item, enchant, consumable, set, boss and zone result also carries its
  own `wowhead_url`.

**`wowsims_best_items_for_slot`** (after F3): rank items for a slot by the stat
weights from `wowsims_stat_weights`.
- args: `owner`, `character?`, `slot`, `limit?`
- returns: `{ranked: [{id, name, ilvl, score, delta_vs_equipped}], summary}`

Name resolution used by every override (F2 onward) is the same resolver as
`wowsims_search_items`: `exact` and `confident` resolve silently (the tool
reports what it resolved to); `ambiguous`, `suggestions` and `not_found` return
`INVALID_OVERRIDE` carrying the same `candidates` (with probabilities) and
`none_of_these`, so the bot can ask "menade du X?".

### Matching and misspellings (F1)

Goal: the bot can always either find the item or ask a good "did you mean"
question, however the user typed it. Never a silent wrong match, never a bare
"not found".

**Normalisation** (query and item names): lowercase, strip accents, drop
apostrophes, turn other punctuation into spaces, collapse spaces, ignore the
words "the" and "of". Exact slot words (e.g. "shoulders") may be used as a slot
hint but are not an alias table; there are no Swedish aliases.

**Candidate generation and scoring** (all in memory, precomputed at startup):
1. exact normalised name: score 100.
2. per-query-word fuzzy match against the item-name vocabulary: exact word,
   prefix of a word (partial typing), or edit distance within a limit that grows
   with word length (1 for up to 4 letters, 2 up to 8, 3 above), counting
   transposed letters as one edit. Query words may come in any order.
3. whole-name character-trigram similarity, which catches run-together or split
   words ("premierlamellar", "band ofthe").
4. combined score: word coverage, penalty for extra unmatched words in the item
   name, trigram similarity, bonus for prefix and for equal-ignoring-spaces.
   Ties go to the higher item level.
Identical names with several IDs (141 such names, e.g. "Insignia of the Horde"
x16) are collapsed into one entry with `same_name_count` and listed with their
differing fields (slot, ilvl, id) when the user has to choose.

**Probabilities.** Raw match scores are turned into probabilities with a
softmax over the top candidates plus a reserved "none of these" outcome. The two
fitted constants (a temperature and the none-of-these offset) are calibrated on
the typo benchmark below, with unknown-item queries mixed in (about a quarter of
the weight) so the none-of-these mass is meaningful. Calibration is re-fitted
whenever the pinned `db.json` or the scorer changes, and the fit is stored in
the repo with the benchmark seed.

**Advisory status** (derived from the probabilities, for the bot's convenience):

| status | when | suggested bot behaviour |
| --- | --- | --- |
| `exact` | normalised name equals exactly one item | use it |
| `confident` | top probability at least 0.85 | use it, mention the corrected name ("antar att du menar X") |
| `ambiguous` | several candidates with similar probability (e.g. a partial name shared by a whole set) | ask which one, listing the candidates |
| `suggestions` | no candidate above 0.85 but plausible ones exist | ask "menade du X, Y eller Z?" |
| `not_found` | `none_of_these` at least 0.8 | say it is not in the sim database; do not guess |

Same-name duplicates with different IDs are always `ambiguous` unless the user
gave enough to pick one (slot filter, ilvl).

**Not in the database is not "does not exist".** `db.json` holds only the items
the sim knows about (checked 2026-10-26: all 8,656 are phase 1, and well-known
Classic items such as Ashkandi, Bloodfang and Nightslayer pieces are absent). A
`not_found` therefore means "not in the sim's database", and the summary says
exactly that, so the bot does not tell users an item is fake. New phases appear
when we bump the pinned ref.

**Measured on a prototype** (2026-10-26, real `db.json`, 400 random real item
names with generated typos: deleted, inserted, substituted, doubled or
transposed letters, dropped spaces, swapped words, truncated names, plus
two-typo combinations):
- single typo: right item first 96%, in the top five 98%
- two typos: first 93%, top five 98%
- all misses were truncated names shared by a whole set ("Duskwov", "Virtuous"),
  which is the `ambiguous` case and should list the set rather than pick one
- about 34 ms per query in unoptimised Python; the production index (word
  vocabulary with a symmetric-delete or BK-tree lookup) should be well under
  that.

**Probability calibration, measured on the prototype** (700 typo queries plus 200
unknown-item queries, same `db.json`; a simple two-constant fit):
- Where it matters, it is trustworthy: every query where the top candidate got
  60% or more was right (567 queries, 0 wrong); at 90% or more, 438 of 438.
- Unknown items: the none-of-these mass averaged 0.62 for unknown-item queries
  and 0.11 for real ones; 72% of unknown-item queries got at least 0.5.
- Weak spots to fix in the real implementation, not papered over:
  - **Underconfident in the middle:** below 0.4, the top candidate was actually
    right 2-57% of the time depending on the bin (not monotone), so probabilities
    there are rough. A proper fit on more features (word coverage, trigram
    similarity, margin to the runner-up, number of close candidates) should
    replace the two-constant softmax.
  - **Run-together set prefixes** such as "premierlamellar" (a real set, spaces
    dropped) got 0.97 none-of-these, because the scorer penalises item names with
    extra words. Whole-name matching without spaces must count as a strong prefix
    match, and the result should be an `ambiguous` list of the set's pieces.
  - **Set prefixes in general** ("duskwov", "dragonmaw") correctly split
    probability across the pieces (0.26/0.26/0.26...), which is the right signal
    to ask the user.
  Acceptance includes a reliability check on held-out queries (see tests).

**Tests (acceptance for F1):** a fixed regression list of real-world mistakes
(including ones from the Discord logs as they turn up), plus the generated-typo
benchmark with the thresholds above (top-1 at least 90%, top-5 at least 97%,
zero silent wrong picks: a `confident` result must be the intended item in the
benchmark; calibration on held-out queries: among top candidates with
probability at least 0.85, at least 97% are right, and the mean predicted
probability in each 0.1-wide bin is within 0.10 of the observed rate). Plus unit tests for each status, for same-name duplicates, for empty
and very long queries, and for non-ASCII input.

### Discovery (read-only)

**`wowsims_list_specs`**
Supported class/spec combinations, races, and which specs have a built-in
default preset. Lets the bot answer "kan ni simma X?" and pick valid inputs.
- args: none
- returns: `{specs: [{class, spec, races: [...], has_default_preset}], sim_version, ruleset_note}`

**`wowsims_list_characters`**
- args: `owner`
- returns: `{characters: [{name, spec, race, is_default, updated_at}]}`

**`wowsims_get_character`**
Show one stored character: gear per slot (item name + id), enchants, talents,
race. For "vad har jag på mig?".
- args: `owner`, `character?`
- returns: `{resolved_character, race, spec, talents, gear: [{slot, item_id, item_name, enchant?, gems?}], updated_at}`

### Character management (writes)

**`wowsims_save_character`**
Create or replace a character from an import, or from a default preset.
- args:
  - `owner`
  - `name`
  - `source`: `"exporter"` | `"sim_json"` | `"preset"`
  - `data`: the pasted export string / JSON (for `exporter`, `sim_json`)
  - `spec`: required for `source="preset"` (start from the spec's default preset)
  - `make_default?`: default true if it is the owner's first character
- returns: `{saved, resolved_character, race, spec, warnings: [...]}`
  where `warnings` lists anything the importer could not map (unknown item id,
  unsupported enchant), so the bot can tell the user.
- idempotent: same name replaces.

**`wowsims_set_default_character`**
- args: `owner`, `character`
- returns: `{default_character}`

**`wowsims_delete_character`** (destructive)
- args: `owner`, `character`, `confirm` (must be `true`)
- returns: `{deleted}`. Without `confirm=true`: error `CONFIRM_REQUIRED`.

### Simulation (read-only on stored data)

**`wowsims_simulate`**
Run one sim for a character, optionally with changes applied on the fly (not
saved).
- args:
  - `owner`
  - `character?`
  - `overrides?`: `{race?, items?: {slot: item_id}, enchants?: {slot: id}, talents?, buffs?, consumables?}`
  - `encounter?`: `{duration_s? (default 300), targets? (default 1)}`
  - `iterations?`: default 3000, max 20000
- returns:
  ```json
  {
    "resolved_character": "Name-Part",
    "applied_overrides": {"race": "Troll"},
    "dps": {"mean": 1234.5, "stdev": 12.3},
    "iterations": 3000,
    "duration_s": 300,
    "top_abilities": [{"name": "...", "pct": 21.4}],
    "sim_version": "<sha>",
    "ruleset_note": "...",
    "summary": "Troll Rogue: ~1235 DPS (±12) over a 300s single-target fight."
  }
  ```

**`wowsims_compare`**
Run a baseline and several variants with the same seed and iterations, return
deltas. The tool for "which racial / which trinket is better".
- args: `owner`, `character?`, `variants` (1-8 items, each `{label, overrides}`), `encounter?`, `iterations?`
- returns: `{baseline: {dps}, results: [{label, dps, delta, delta_pct}], best, summary}`
  sorted best to worst. A delta inside the noise (below ~2 stdev) is flagged
  `"within_noise": true` so the bot does not overclaim.

**`wowsims_stat_weights`**
- args: `owner`, `character?`, `encounter?`
- returns: `{weights: [{stat, value, relative}], baseline_dps, summary}`
- method: finite differences, +50 (+100 attack power) of each stat via `bonusStats`, shared RNG; `value` is DPS per point, `relative` is scaled to the best stat. No stat caps modelled.

### Later features (provisional, shapes may change)

(F6 item sources moved into F1: see `wowsims_get_item` and `wowsims_get_loot`.)

**`wowsims_get_patch_changes`** (F7): what changed recently.
- args: `item_or_spell?`, `since_patch?`, `limit?`
- returns: `{changes: [{patch, kind, name, before, after}], has_more}`
- source: `wowsims/gamedata` patch files, fetched at runtime and cached briefly
  on the data volume. Never bundled in the repo or image. If the fetch fails:
  error `SOURCE_UNAVAILABLE`, and the bot falls back to web search.

**`wowsims_lookup_character`** (F8, after 4 Nov): fetch a character's gear by name.
- args: `name`, `game_mode?`
- returns: a character in the same shape as `wowsims_get_character`, not saved;
  save it with `wowsims_save_character`.
- only via an allowed data source (Blizzard's API or an agreed route).

**F10-F15 (candidate, shapes only after their data is checked; see PLAN.md):**
`wowsims_get_stat_caps(spec, race?)`, `wowsims_get_talents(spec)` (plus talent
overrides in `simulate`/`compare`), `wowsims_best_items_for_slot` per slot or all
slots (upgrade finder), a BiS view per spec and phase, and
`wowsims_recommend_consumables(spec, role)`. Crafting questions use the `sources`
in `wowsims_get_item`. All follow the same rules: short results with a `summary`,
sim output labelled as such, and a plain "not in the data" error instead of
guesses.

**F9 raid-level sims** extends `wowsims_simulate` / `wowsims_compare` with a
`raid_buffs` argument; no new tools.

## Errors

Tool errors are returned inside the result (`isError: true`, per MCP), never as
protocol errors. Shape:

```json
{
  "ok": false,
  "code": "AMBIGUOUS_CHARACTER",
  "message": "Owner has 3 characters and no default.",
  "candidates": ["Name-One", "Name-Two", "Name-Three"],
  "next_step": "Ask the user which character, or call wowsims_set_default_character."
}
```

Codes: `ITEM_NOT_FOUND`, `NO_CHARACTERS`, `AMBIGUOUS_CHARACTER`, `CHARACTER_NOT_FOUND`,
`UNSUPPORTED_SPEC`, `IMPORT_FAILED` (with what was wrong with the data),
`INVALID_OVERRIDE` (with the valid values), `CONFIRM_REQUIRED`,
`SIM_TIMEOUT`, `SIM_FAILED`, `BUSY`, `SOURCE_UNAVAILABLE`.

## Limits and safety

- Sim runs in a subprocess with a hard timeout (default 60 s) and a global
  concurrency limit (e.g. 2). Over the limit: `BUSY` with a retry hint.
- `iterations` capped; `variants` capped at 8; import data capped in size
  (e.g. 256 KB).
- All inputs validated with Pydantic. Item ids and slots checked against the
  game data before building the request. No shell interpolation: the CLI is
  invoked with an argument list and a temp input file.
- The temp input file is written to a per-run directory and removed afterwards.
- Storage is SQLite (see PLAN.md); only this server touches it.

## Annotations

| Tool | readOnly | destructive | idempotent | openWorld |
| --- | --- | --- | --- | --- |
| `wowsims_help` | true | false | true | false |
| `wowsims_search_items` | true | false | true | false |
| `wowsims_get_item` | true | false | true | false |
| `wowsims_search_enchants` | true | false | true | false |
| `wowsims_get_loot` | true | false | true | false |
| `wowsims_get_set` | true | false | true | false |
| `wowsims_compare_items` | true | false | true | false |
| `wowsims_search_consumables` | true | false | true | false |
| `wowsims_get_wowhead_link` | true | false | true | false |
| `wowsims_best_items_for_slot` (after F3) | true | false | true | false |
| `wowsims_get_patch_changes` (F7) | true | false | true | true |
| `wowsims_lookup_character` (F8) | true | false | true | true |
| `wowsims_list_specs` | true | false | true | false |
| `wowsims_list_characters` | true | false | true | false |
| `wowsims_get_character` | true | false | true | false |
| `wowsims_save_character` | false | false | true | false |
| `wowsims_set_default_character` | false | false | true | false |
| `wowsims_delete_character` | false | true | true | false |
| `wowsims_simulate` | true | false | true | false |
| `wowsims_compare` | true | false | true | false |
| `wowsims_stat_weights` | true | false | true | false |

## What the bot's `TOOLS.md` section should say

- Use `wowsims_search_items` to turn an item name into an ID or to check what an
  item is, before guessing. Names can be passed straight into overrides.
- Use `wowsims_simulate`/`wowsims_compare` for any "which is better / how much
  DPS" question about gear, racials or talents, instead of reasoning from memory.
- Always pass the message sender's ID as `owner`.
- If a tool returns `next_step`, follow it; ask the user only what it says to ask.
- Quote the `summary`, and mention it is a sim result. If `within_noise` is set,
  say the difference is not meaningful.
- If the spec is not in `wowsims_list_specs`, say the sim does not support it.

## Open design questions

1. Exact override shapes for items, enchants, gems and talents (depends on the
   real `RaidSimRequest` and on what the importer can produce).
2. Whether to expose raid-level sims (buffs from other classes) or keep to
   single-character sims. Start single-character.
3. Item lookup is decided (F1, first, backed by the sim's `db.json`), so
   `wowsims_get_character` returns item names as well as IDs from the start.
4. Whether `db.json`'s zone/NPC tables link to items (decides F6). Coverage of
   `db.json` itself is trusted; there is no Swedish alias table, names are
   matched as they appear in `db.json` (decisions in PLAN.md).
5. How to rank search results when many items share a name at different item
   levels (prefer the highest phase? show all?). Start by returning all, ordered
   by ilvl descending.
