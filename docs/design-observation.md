# Design — Game Observation (`packages/hima-dht-web/`, `packages/hima-dht-records/`)

Concepts and terminology: `concept-observation.md`. Workspace membership and the
record contract: `design-packages.md`. Phases Model and Spec are skipped: pure
infrastructure over an already-confirmed record vocabulary, no non-trivial algorithm
(folding is sequential accumulation).

## Design Overview

- **Classes**: `GameSampler` (`hima_dht_game.sampler`), `GameStore`, `StreamCursor`
- **Modules**: `hima_dht_records.records` (record contract: schema constants and
  folding); in `hima_dht_web`: `logs` (decision and command
  log parsing), `games` (game listing and payload assembly), `stream` (live game
  tailing), `server` (HTTP surface)
- **Relationships**: `server` uses `games` and `stream` (one-way). `games` uses
  `hima_dht_records` and `logs`. `stream` uses `logs`. `hima_dht_game.sampler`
  contains `GameSampler` (the sc2-dependent record writer).
  `games` contains `GameStore`. `stream` contains `StreamCursor`.
  The bot process uses `sampler`. `hima_dht_cli.export` uses `sampler`
  (writes the same record file during re-simulation) and `hima_dht_records`
  (folding). `hima_dht_cli.viewer` uses `logs`.
- **Abstract**: none.
- **Exceptions**: none raised by the web member (per-request failures map to
  HTTP status codes); `hima serve` in `hima_dht_cli.cli` maps uvicorn's
  startup failure to `CommandError`, keeping the web member free of cli types.
- **Dependency roles**: Data holders: record dicts (schema below), `StreamCursor`
  (one client's stream progress: record byte offset, decision and command entry
  counts). Orchestrator: `server`. Helpers: `records`, `logs`, `games`, `stream`.
- **Assets**: `player_template.html` and `index_template.html`
  (`hima_dht_web/_resources/templates/`, read via `importlib.resources`).
  The player template gains a live-mode section: when the injected
  payload carries `live: true`, the page subscribes to the record stream and appends
  incoming records; all rendering code is shared with replay mode. The templates
  live in the web member so the webui image is self-contained; `hima_dht_cli.viewer`
  reuses `server.render` for the standalone export. The index template carries the
  placeholder `__HIMA_ROWS__`; the server injects one table row per game.

## Page Design System

Both browser pages (game list and observation) share one visual identity: the
JHU palette and type system recorded in `impl-observation.md`, declared as CSS
custom properties inline in each page — no external fetch.

- **Themes**: light and dark, from `prefers-color-scheme` with
  `:root[data-theme]` overrides; the observation page's canvas reads its colors
  from the computed custom properties and redraws on scheme change.
- **Color semantics**: own units Heritage/Spirit Blue, enemy units Dark Red,
  minerals Spirit Blue, vespene Homewood Green; result badges Victory green,
  Defeat red, Tie quiet, live Spirit Blue.
- **Observation page additions**: a unit-color legend in the header, keyboard
  playback control (space toggles play, arrow keys seek), and unit
  identification on canvas hover (type name and health).
- **Game list page**: one table row per game — id linking to its observation
  page, result badge, duration.

## Record Schema (`records`)

One JSON object per line in `frames.jsonl`, discriminated by `k`:

| `k` | Fields | Meaning |
|-----|--------|---------|
| `meta` | `map`, `playable`, `neutral` | Emitted once at first sample |
| `type` | `name`, `r`, `s` | Type registry entry; index = order of appearance |
| `frame` | `t`, `m`, `g`, `su`, `sc`, `u` | One frame record (fields as in `design-cli.md`) |
| `end` | `result` | Emitted when the game ends |

Decision records `{t, n, s}` and command records `{t, a, st}` are not in
`frames.jsonl`; they fold from the run's `output.txt` and `command.txt` via `logs`.
The game payload is the fold: `{meta, types, type_meta, neutral, frames, decisions,
commands}` — identical to the exported-page payload in `design-cli.md`.

## Class / Type Specifications

### GameSampler (`records`)
- **Responsibility**: Write the record file for one game while an AI object steps.
- **State**: `path: Path`, `sample_interval: int`, `_type_index: dict[str, int]`.
- **Methods**:
  - `step(ai, iteration)` — Behavior: on first call append the `meta` record and
    neutral-resource data; every `sample_interval` iterations append one `frame`
    record, appending `type` records for first-seen unit types. Input: a BotAI- or
    ObserverAI-compatible object, iteration index. Output: none. Errors: `OSError`
    propagates.
  - `finish(result)` — Behavior: append the `end` record. Input: result label.

### GameStore (`games`)
- **Responsibility**: Enumerate observable games and assemble payloads.
- **State**: `runs_dir: Path`, `tmp_dir: Path`.
- **Methods**:
  - `list_games()` — Output: one entry per archived run (id = directory name, with
    result and duration) plus a `live` entry when `tmp/frames.jsonl` exists without
    an `end` record.
  - `payload(game_id)` — Behavior: fold the game's record file and logs into the
    payload; `live` reads from `tmp/`, other ids from `runs/<id>/`. A live payload
    carries `stream.records`, the byte offset of the folded complete lines, so the
    stream resumes without gap or duplication. Errors: `KeyError` when the id names
    no game (server maps to 404); a game without a record file reports the export
    fallback in the error detail.

## Function Specifications

- **fold_records(path) -> dict** (`records`) — Behavior: read the record file,
  accumulate `meta`/`type`/`frame`/`end` records into `{meta, types, type_meta,
  neutral, frames, result}`. Errors: `FileNotFoundError` propagates.
- **fold_lines(lines) -> dict** (`records`) — Behavior: the same fold over
  in-memory lines; the live payload folds a complete-line snapshot so its byte
  offset and its fold agree. Errors: `ValueError` on an unknown record kind.
- **live_events(tmp_dir, cursor) -> async iterator** (`stream`) — Behavior: poll
  the live game's three files, yield one SSE-framed event per record, decision,
  and command appended past the cursor; `end` is always the final event and
  terminates the stream. Input: `tmp/` path, `StreamCursor`. Errors: none raised;
  an absent file reads as empty.
- **parse_decisions(path) -> list[dict]**, **parse_commands(path) -> list[dict]**
  (`logs`) — moved unchanged from the cli viewer module; absent file returns an empty list
  (the page renders without that panel).
- **create_app(store) -> FastAPI** (`server`) — Behavior: build the HTTP app with
  routes: game list page and JSON (`/`, `/api/games`), observation page and payload
  (`/games/{id}`, `/api/games/{id}`), live record stream (`/api/live/stream`,
  server-sent events). The observation page is `player_template.html` with the
  payload injected server-side — the same injection the standalone export uses.
- **create_default_app() -> FastAPI** (`server`) — Behavior: build the app over the
  run layout at the working directory (`GameStore` on cwd-joined `RUNS_DIRNAME`,
  `TMP_DIRNAME` from `hima_dht_records`); the `uvicorn --factory` target for the
  webui image and the webui managed by `hima up` (`design-cli.md`). Errors: none.
- **render(data) -> str** (`server`) — Behavior: inject one game payload JSON into
  the template's placeholder; used by the observation page and by
  `hima_dht_cli.viewer` for the standalone export. Errors: none.
- **stream events** — the live endpoint tails `tmp/frames.jsonl`, `output.txt`, and
  `command.txt`, emitting each new record with its kind (`frame`/`type`/`decision`/
  `command`/`end`); a client joining mid-game gets the payload from `/games/live`
  first, then resumes via query parameters: `records` (the payload's `stream.records`
  byte offset) plus `decisions` and `commands` (its entry counts).

## Integration Changes (outside the web member)

- `hima_dht_game.bot` — instantiate `GameSampler(save_path/frames.jsonl)` in `on_start`,
  call `step` in `on_step`, `finish` in `on_end`. Sampling adds no model or network calls.
- `hima_dht_cli.export` — `ReplayExporter` drives a `GameSampler` writing `frames.jsonl`
  beside the replay's logs, then folds it; the exported page is unchanged.
- `hima_dht_cli.workspace` — `frames.jsonl` joins `GAME_OUTPUTS` so `hima run` archives it.
- `hima_dht_cli.cli` — the `serve` subcommand (`--host`, `--port`) runs uvicorn
  in-process over `create_default_app` and maps startup failure to `CommandError`.

## Exception / Error Types

- `CommandError` (`hima_dht_cli.errors`) — raised by the cli's serve wrapper on
  startup failure (port bound); never raised inside the web member.
- HTTP 404 — unknown game id. HTTP 409 — payload requested for a game with no record
  file (message names the `hima export` fallback).
