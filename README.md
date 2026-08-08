# hima

> After the HIMA agent from [Society of Mind Meets Real-Time Strategy](https://arxiv.org/abs/2508.06042) (COLM 2025); this fork repackages the [reference implementation](https://github.com/snumprlab/hima).

Workspace packaging of the COLM 2025 HIMA StarCraft II agent: game, advisor inference, observation webui, operations CLI.

## Install

Prerequisites: [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com/),
and retail StarCraft II 5.0.16 with the ladder map — game client setup in the
[paper README](packages/hima-dht-game/README.md). Docker (via
[OrbStack](https://orbstack.dev/) or Docker Desktop) is needed only for the
headless run mode.

```sh
brew install ollama   # macOS: native Ollama uses the Metal GPU; container VMs cannot
git clone git@github.com:samhsu-dev/hima.git
cd hima
uv sync
```

## Usage

Native run (the retail macOS client renders the game on screen — for watching
a game live):

```sh
uv run hima up        # launch advisor + webui; provision a local Ollama only when
                      # the leader URL is the default, else verify the endpoint
uv run hima run       # play one game, archive its outputs under runs/
uv run hima metrics   # aggregate metric.json across runs/
```

Headless run (the game plays in a container with no display — for batch
experiments; the leader is an endpoint you run yourself — on a Mac, the
host's native Ollama, see "Run modes and the leader engine"):

```sh
uv run hima down                # free the ports held by the native services
brew services start ollama      # leader: native Metal Ollama on 11434

uv run hima up --backend docker # advisor + webui containers; verifies the leader endpoint
uv run hima status              # every check ✓ before running

# once per machine, in .env: SC2_LICENSE=iagreetotheeula accepts the
# Blizzard AI and Machine Learning License; the first run then builds
# the game image (multi-GB download)
uv run hima run --headless      # one headless game, archived under runs/

uv run hima metrics             # aggregate results
open http://localhost:8123      # observation webui
```

Restore the native steady state afterwards:

```sh
uv run hima down && brew services stop ollama && uv run hima up
```

## Run modes and the leader engine

- **Native**: everything runs as host processes. `hima up` spawns and owns
  `ollama serve`, the advisor, and the webui (pid files under
  `tmp/services/`); `hima run` launches the retail macOS client, which
  renders the game. This is the default and the fastest setup.
- **Headless**: the game runs in a container as the SC2 4.10 Linux client
  under qemu-user emulation — no display, suitable for unattended batch
  experiments. It reaches the advisor as a compose service and the leader
  through `host.docker.internal` ([design](docs/design-deployment.md)).
- **Why the leader must be the host's native Ollama on a Mac**: macOS
  container VMs (OrbStack, Docker Desktop) expose no Apple-GPU passthrough,
  so a containerized Ollama runs CPU-only. Measured on an M4 Pro: native
  Ollama answers a `qwen3:8b` leader completion in 29.5 s on Metal; the
  containerized CPU engine never finishes inside the client's 600 s timeout.
  Games are LLM-bound — the leader engine sets the experiment's wall clock.
  The compose `ollama` service (opt-in profile `leader`) exists for Linux
  hosts with NVIDIA GPUs.
- In the native flow, `hima up` provisions `ollama serve` itself when the
  leader URL is the local default. With `--backend docker` it never
  provisions the leader — it verifies the configured endpoint and fails
  fast, so run the leader yourself (`brew services start ollama`, since
  `hima down` has stopped the hima-owned one) or point
  `HIMA_LEADER_BASE_URL` at any OpenAI-compatible server.

## Configuration

- Every setting resolves as CLI flag > exported environment > `.env` > code
  default. `.env` sits beside `docker-compose.yml` and is shared with compose
  interpolation, so one file configures both backends. All `HIMA_*` keys and
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
