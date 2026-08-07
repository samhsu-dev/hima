# hima

> After the HIMA agent from [Society of Mind Meets Real-Time Strategy](https://arxiv.org/abs/2508.06042) (COLM 2025); this fork repackages the [reference implementation](https://github.com/snumprlab/hima).

Workspace packaging of the COLM 2025 HIMA StarCraft II agent: game, advisor inference, observation webui, operations CLI.

## Install

Prerequisites: [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com/),
and retail StarCraft II 5.0.16 with the ladder map — game client setup in the
[paper README](packages/hima-dht-game/README.md).

```sh
brew install ollama   # macOS: native Ollama uses the Metal GPU; container VMs cannot
git clone git@github.com:samhsu-dev/hima.git
cd hima
uv sync
```

The leader runs on any OpenAI-compatible endpoint: point `HIMA_LEADER_BASE_URL`,
`HIMA_LEADER_MODEL`, and `HIMA_LEADER_API_KEY` (see `.env.example`) at a remote
provider to replace local Ollama.

## Usage

```sh
uv run hima up        # launch advisor, Ollama, and the webui, wait until healthy
uv run hima run       # play one game, archive its outputs under runs/
uv run hima metrics   # aggregate metric.json across runs/
```

Containerized services (advisor, Ollama, webui):

```sh
docker compose up -d
```

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
