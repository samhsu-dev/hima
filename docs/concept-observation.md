# Concept — Game Observation (`src/cli/web/`)

## 1. Context

**Problem Statement** — Experiments run without a visual surface: leader decisions and
executed commands land in text logs, and watching a finished game requires the retail
StarCraft II client or a manually exported page. A game in progress and a finished game
need one browser interface built on one data contract.

**System Role** — Observation subsystem: turns recorded game state and decision logs
into browser pages, for the game currently playing and for archived games alike.

**Data Flow**
- **Inputs:** frame records sampled by the playing bot; decision and command logs
  written by the leader; archived run directories; replay files (for games recorded
  before frame sampling existed).
- **Outputs:** game list, live observation page, replay observation page.
- **Connections:** game process → frame records → observation server → browser;
  run archive → observation server → browser.

**Scope Boundaries**
- **Owned:** the record schema (frame, decision, command), folding records into a game
  payload, live incremental delivery, archived-game delivery, game listing.
- **Not Owned:** game execution and archiving (experiment run), engine re-simulation
  of old replays (export, see `design-cli.md`), model services, StarCraft II's own
  rendering.

## 2. Concepts

**Conceptual Diagram**

```
bot (game playing)              run archive (game finished)
      | frame records                 | frame records + logs
      v                               v
              observation server
      | payload-so-far + live stream  | complete payload
      v                               v
  live page  <---- one renderer ---->  replay page
```

**Core Concepts**

- **Name:** Frame record
  - **Definition:** One sampled snapshot of visible game state — game time, resources,
    supply, and every visible unit with type, position, owner, and health.
  - **Scope:** Includes only what the observed player sees (fog of war). Excludes
    orders, pathing, and animation state.
  - **Relationships:** References unit types by index into the type registry; folded
    into the game payload; delivered on the live stream.

- **Name:** Type registry
  - **Definition:** The ordered set of unit types seen so far in one game, with radius
    and structure flag per type.
  - **Scope:** Grows during a game as new types appear; never shrinks.
  - **Relationships:** Referenced by frame records; part of the game payload.

- **Name:** Decision record
  - **Definition:** One leader inference outcome: game time, action count, and the
    action summary.
  - **Scope:** Excludes prompts and raw model output (those stay in run logs).
  - **Relationships:** Parsed from the leader's output log; folded into the game
    payload; delivered on the live stream.

- **Name:** Command record
  - **Definition:** One executed command: game time, action name, execution status.
  - **Scope:** Excludes queued-but-unsent actions.
  - **Relationships:** Parsed from the command log; folded into the game payload;
    delivered on the live stream.

- **Name:** Game payload
  - **Definition:** The complete data for one game: metadata, type registry, and all
    frame, decision, and command records. The fold of every record of that game.
  - **Scope:** Self-contained — a page holding a payload needs no other game data.
  - **Relationships:** Served whole for archived games; served as payload-so-far for
    the live game.

- **Name:** Live stream
  - **Definition:** Incremental delivery of new records — the same record kinds as the
    payload — while the game is in progress.
  - **Scope:** Carries only records created after the receiving page loaded.
  - **Relationships:** Appends to the payload the live page already holds.

- **Name:** Observation page
  - **Definition:** The single browser renderer for a game payload: map canvas,
    decision timeline, command feed, playback controls.
  - **Scope:** One renderer for both modes. Live mode appends stream records and
    follows the newest frame; replay mode scrubs a complete payload.
  - **Relationships:** Consumes the game payload; live mode also consumes the live
    stream; the standalone exported page (`design-cli.md`) embeds the same payload.

**The unified-interface requirement reduces to: live = payload-so-far + live stream;
replay = complete payload. One schema, one renderer.**

## 3. Contracts & Flow

**Data Contracts**
- **With the experiment run:** the playing bot appends frame records to the run's
  working directory; the leader writes decision and command logs there.
- **With the run archive:** a finished game's records and logs move into the archive
  unchanged; the payload folds from them on request.
- **With the browser:** game list, one payload per game, one live stream for the
  in-progress game — all using the record vocabulary above.

**Internal Processing Flow**
1. Sample — during play, the bot records one frame record per sampling interval.
2. Fold — on request, records and logs of one game combine into its payload.
3. Deliver — replay pages receive the payload; the live page receives payload-so-far,
   then stream records as they appear.

## 4. Scenarios

- **Typical:** A run starts; the observer opens the live page and watches units move,
  decisions appear on the timeline, and commands scroll as the leader acts. After the
  game ends, the archive lists it and the same page replays it.
- **Boundary:** A replay recorded before frame sampling existed has no frame records;
  its payload is produced once by engine re-simulation (export) and then served like
  any archived game.
- **Interaction:** The observer opens the live page mid-game: the server sends the
  payload-so-far, and the page continues from the live stream without a gap.
