# hima

> After the HIMA agent from [Society of Mind Meets Real-Time Strategy](https://arxiv.org/abs/2508.06042) (COLM 2025); this fork repackages the [reference implementation](https://github.com/snumprlab/hima).

Workspace packaging of the COLM 2025 HIMA StarCraft II agent: game, advisor inference, observation webui, operations CLI.

## Install

Prerequisites: [uv](https://docs.astral.sh/uv/), an OpenAI-compatible leader
endpoint ([Ollama](https://ollama.com/) locally, or any provider), and Docker
(via [OrbStack](https://orbstack.dev/) or Docker Desktop) for the
containerized game. Retail StarCraft II 5.0.16 with the ladder map is needed
only to run the game on the host — client setup in the
[paper README](packages/hima-dht-game/README.md).

```sh
brew install ollama   # macOS: native Ollama uses the Metal GPU; container VMs cannot
git clone git@github.com:samhsu-dev/hima.git
cd hima
uv sync
```

## Usage

```sh
brew services start ollama  # the leader endpoint is yours to run
uv run hima up              # advisor as a host process; verify the leader endpoint
uv run hima status          # every check ✓ before running

# once per machine, in .env: SC2_LICENSE=iagreetotheeula accepts the
# Blizzard AI and Machine Learning License; the first run then builds
# the game image (multi-GB download)
uv run hima run             # one game in a container, archived under runs/
uv run hima metrics         # aggregate metric.json across runs/
```

To watch a game while it plays, start the observation server and ask a run to
open it:

```sh
uv run hima up --webui      # adds the webui to the managed services
uv run hima run --ui web    # opens the live page; fails fast if no webui is up
```

## Deployment axes

Three independent choices. No value of one constrains another — pick each on
its own merits.

| Choice | Option | Environment | Default |
|--------|--------|-------------|---------|
| Where the services run | `hima up --services host\|container` | `HIMA_SERVICES` | `host` |
| Whether the webui exists | `hima up --webui` | `HIMA_WEBUI` | off |
| Where the game runs | `hima run --game host\|container` | `HIMA_GAME` | `container` |
| How you watch | `hima run --ui none\|web\|pygui` | `HIMA_UI` | `none` |

- **Services**: `host` spawns the advisor (and the webui when selected) as
  host processes that `hima` owns through pid files under `tmp/services/`;
  `container` runs the same services under compose. On macOS the host
  placement keeps the advisor on the Metal GPU.
- **Game**: `container` runs the SC2 4.10 Linux client headless under
  qemu-user emulation — no display, suitable for unattended batch
  experiments, and the reference placement for comparable results. `host`
  runs the retail macOS client, which renders the game on screen; its
  results compare only with other retail runs, since the two clients differ
  in version and balance. A container game reaches a host advisor through
  `host.docker.internal`, so either service placement serves either game
  placement.
- **Watching is a separate question from where the game runs.** Both
  surfaces read the `runs/` and `tmp/` trees, which a host game and a
  container game write alike: `--ui web` opens the live browser page,
  `--ui pygui` opens the pysc2 renderer on the archived replay after the
  game. The retail client's own window is not one of these — it is the host
  SC2 engine rendering itself.
- **The leader engine is yours, always.** `hima up` never starts, stops, or
  pulls for it: it verifies that `HIMA_LEADER_BASE_URL` serves
  `HIMA_LEADER_MODEL` and fails fast when it does not. Run it however you
  like — `brew services start ollama`, the opt-in compose `leader` profile,
  or any OpenAI-compatible provider.
- **Why the leader stays native on a Mac**: macOS container VMs (OrbStack,
  Docker Desktop) expose no Apple-GPU passthrough, so a containerized Ollama
  runs CPU-only. Measured on an M4 Pro: native Ollama answers a `qwen3:8b`
  leader completion in 29.5 s on Metal; the containerized CPU engine never
  finishes inside the client's 600 s timeout. Games are LLM-bound — the
  leader engine sets the experiment's wall clock. The compose `ollama`
  service (opt-in profile `leader`) exists for Linux hosts with NVIDIA GPUs.

## Configuration

- Every setting resolves as CLI flag > exported environment > `.env` > code
  default. `.env` sits beside `docker-compose.yml` and is shared with compose
  interpolation, so one file configures every placement. All `HIMA_*` keys and
  their defaults are listed in [.env.example](.env.example).
- The leader is endpoint-portable: `HIMA_LEADER_BASE_URL`,
  `HIMA_LEADER_MODEL`, and `HIMA_LEADER_API_KEY` point at any
  OpenAI-compatible server — native Ollama (default), vLLM, or a hosted
  provider — to replace local inference entirely.
- `hima up` records what it started in `tmp/services/manifest.toml`;
  `hima down` and `hima status` operate on that record, never on port
  guessing. `hima status` exits 1 when any check fails, so scripts can gate
  on it.

## API

One uv workspace, four members ([design](docs/design-packages.md)):

| Member | Responsibility |
|--------|----------------|
| `hima-dht-records` | Shared game-record format: fields, folding |
| `hima-dht-game` | Game runtime (`python -m hima_dht_game`) and the advisor service |
| `hima-dht-web` | Observation webui: archived runs and live stream |
| `hima-dht-cli` | The `hima` console script: services, runs, metrics, replay tools |

`hima` commands: `up`, `down`, `status`, `run`, `metrics`, `replay`, `export`,
`view`, `serve` — specifications in [design-cli.md](docs/design-cli.md).

## Development

- Start at [docs/index.md](docs/index.md): each area has a `design-*.md`
  (software structure) and an `impl-*.md` (verified library findings). Read
  the pair before changing a member; update them with the change.
- Quality gates before every commit:

  ```sh
  uv run ruff format && uv run ruff check && uv run mypy --strict && uv run pytest
  ```

- One game archives under `runs/<replay-stem>/`: leader logs
  (`command,input,output,prompt`.txt), `metric.json`, `frames.jsonl`, and the
  replay. Service state and logs live under `tmp/services/`.

## Documentation

- [docs/index.md](docs/index.md) — index of the design and implementation docs.
- [packages/hima-dht-game/README.md](packages/hima-dht-game/README.md) — the
  paper README: results, game client setup, original run instructions.

## Citation

```bibtex
@inproceedings{ahnKC25,
      author    = {Daechul Ahn and San Kim and Jonghyun Choi},
      title     = {Society of Mind Meets Real-Time Strategy: A Hierarchical Multi-Agent Framework for Strategic Reasoning},
      booktitle = {COLM},
      year      = {2025}
}
```

## License

The upstream repository publishes no license file; all rights to the original
code remain with its authors. This fork adds no license of its own.
