# Implementation Notes — Deployment (`design-deployment.md`)

## APIs

- **[uv]** index pinning by platform marker (verified against uv docs; named indexes
  must be defined in `pyproject.toml` itself):

  ```toml
  [tool.uv.sources]
  torch = [{ index = "pytorch-cpu", marker = "sys_platform == 'linux'" }]

  [[tool.uv.index]]
  name = "pytorch-cpu"
  url = "https://download.pytorch.org/whl/cpu"
  explicit = true
  ```

- **[uv]** Docker layering (verified against uv Docker guide; tag `0.12.1` exists and
  matches the local uv):

  ```dockerfile
  COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/
  RUN --mount=type=cache,target=/root/.cache/uv \
      --mount=type=bind,source=uv.lock,target=uv.lock \
      --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
      uv sync --locked --no-install-project --no-dev
  COPY . /app
  RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev
  ```

## Libraries

- torch 2.13.0+cpu — CPU index ships `manylinux_2_28_x86_64` and `_aarch64` wheels:
  advisor/webui images build for linux/amd64 and linux/arm64; macOS keeps the PyPI
  MPS wheel (marker excludes darwin).
- ollama/ollama:0.32.5 — pinned to the local client; stock service and baked image
  (`docker/leader.Dockerfile`, build verified).

## StarCraft II Linux client

- Download: `https://blzdistsc2-a.akamaihd.net/Linux/SC2.4.10.zip`; unzip password
  `iagreetotheeula` is the AI and Machine Learning License acceptance — the game
  image build argument carries it, no default.
- Install root: burnysc2 Linux default is `~/StarCraftII` (`sc2/paths.py`);
  `SC2PATH` overrides.
- Blizzard map packs (`.../MapPacks/<name>.zip`, same password) end at Ladder 2019
  Season 3 — Ancient Cistern LE (2023) is not in them.
- Map source: the retail install's `/Applications/StarCraft II/Maps/Ancient Cistern
  LE.SC2Map`, copied into the image's lowercase `maps/`. The SC2 Linux server
  resolves the relative map path burnysc2 sends against `<root>/maps`; a map in
  the zip's capital `Maps/` fails CreateGame with `InvalidMapPath`. burnysc2's
  `Paths.MAPS` also prefers lowercase `maps` when it exists.
- SC2 4.10 under OrbStack's Rosetta amd64 emulation crashes at startup: after
  "Creating stub renderer..." it prints "unable to parse listen address." /
  "Failed to initialize port" and dies with signal 11. Reproduced with single-
  and double-dash arg forms, `-listen 127.0.0.1|0.0.0.0|localhost`, and on both
  Debian trixie and Ubuntu 18.04 userlands — glibc version is not the cause.
  `getaddrinfo`/`bind` from Python succeed in the same Rosetta container.
- The same binary and args under qemu-user TCG (arm64 container, `qemu-x86_64
  -L <amd64 rootfs>`) starts fully: "Listening on: 127.0.0.1:5000", "Startup
  Phase 3 complete". The crash is a Rosetta emulation defect, not an SC2 or
  image defect.
- qemu-user caveats: launching via `ld-2.27.so <binary>` breaks SC2's install-root
  discovery (`/proc/self/exe` points at the loader — "Failed to find .build.info");
  exec the binary directly with `-L`. An `-L` prefix must not contain absolute
  symlinks that escape it (Ubuntu's `/lib64/ld-linux-x86-64.so.2` does; replace
  with a copy).
- Confirmed design: the game image is arm64-native and execs only `SC2_x64`
  through qemu-user (`design-deployment.md`, emulation boundary).
- 4.10 client segfaults joining retail Ancient Cistern LE (2023): its
  `t3Terrain.xml` declares `<terrain version="115">`; the 4.10 terrain parser
  null-derefs in a sort comparator on that version. Maps that load (AcropolisLE
  2019, EquilibriumAIE) declare `version="114"` with an otherwise identical
  element structure.
- Fix part 1 (join): rewrite that one attribute to `114`; the otherwise
  untouched retail map then reaches `in_game` (verified by raw
  s2clientprotocol create/join probe under qemu).
- Fix part 2 (balance): the terrain-only fix fails at bot iteration 0 with
  `KeyError: 300` — `constants.RESEARCHS` uses live-balance upgrade IDs
  (300 = `UpgradeId.INTERFERENCEMATRIX`) absent from the 4.10 catalog.
  Injecting the `aiarena/sc2patch` `5.0.14.94137` payload into the map MPQ
  (156 files: `Base.SC2Data/GameData/*.xml` + `stableid.json` + localized
  strings + Assets; the three case-colliding display files excluded) yields a
  306-entry upgrade catalog whose numeric IDs match the python-sc2 enums.
- `stableid.json` loads from the map's `Base.SC2Data\GameData\` like any
  GameData override; the 4.10 Linux install root has no `stableid.json` and
  needs none.
- Ruled out by ablation: aiarena/sc2patch GameData injection, removing
  map-embedded GameData XMLs, stripping unknown doodads, emptying t3Water,
  remapping unknown terrain textures — all still crash with `version="115"`.
- AI Arena "AIE" maps are retail maps with the `aiarena/sc2patch` payload
  injected (balance GameData + stableid + strings) for 4.10 behavior parity;
  no Ancient Cistern AIE exists in any published pool.
- `.SC2Map` is a plain MPQ (magic `MPQ\x1A`); stored names are case-insensitive
  and use backslashes. Read with `mpyq` (in the image venv); write with
  StormLib (`brew install stormlib`) via ctypes — Debian `smpq` aborts on an
  internal assertion and cannot write.
- SC2 crash logs print a backtrace from its own SIGSEGV handler, which then
  double-faults; the core dump captures only that secondary crash. Capture the
  real fault with `qemu-x86_64 -g <port>` plus `gdb-multiarch` attached before
  continuing.
- `ldd` on `SC2_x64` (amd64 game image): libdl, libpthread, librt, libstdc++,
  libm, libgcc_s, libc + ld-linux — all covered by `libc6:amd64` +
  `libstdc++6:amd64` (libgcc-s1 arrives as a dependency).
- Debian multiarch (`dpkg --add-architecture amd64`) places those libs at the
  canonical paths (`/lib/x86_64-linux-gnu`, `/lib64/ld-linux-x86-64.so.2`), so
  `qemu-x86_64` needs no `-L` prefix.
- The `qemu-user` Debian package provides `/usr/bin/qemu-x86_64`.

## Developer instructions

- After editing `[tool.uv.sources]`: `uv lock`, commit `uv.lock`.
- No image patches site-packages: the pysc2 compatibility fixes apply
  in-process when `hima replay` spawns `hima_dht_cli.pysc2_play`.
- Compose: default profile = advisor + ollama + webui; `--profile baked` swaps the
  leader; `--profile game` adds the containerized game.
- The game image builds `FROM` the native-platform cli tag:
  `docker build -t hima-cli --build-arg PACKAGE=hima-dht-cli
  -f docker/hima.Dockerfile .`; no platform override anywhere.
- Compose forwards `SC2_LICENSE` from the environment (`${SC2_LICENSE:-}`); an
  empty value fails the guard layer naming the argument before any download.
- Compose `${VAR:-default}` interpolation reads the `.env` beside
  `docker-compose.yml`; an exported environment variable overrides the `.env`
  value. The published-port defaults live in `.env.example`.
- python:3.12-slim has no curl; the advisor healthcheck runs
  `python -c "urllib.request.urlopen(...)"` from the image venv on PATH.
- The ladder map lives in the git-tracked `maps/`; the game image COPYs it from
  there. No `docker/maps/` staging directory.
- The tracked map is the retail file (`terrain version="115"`), which the 4.10
  client cannot join; runs mount the terrain+balance patched map
  (`tmp/sc2map-aie/`) over `/root/StarCraftII/maps/Ancient Cistern
  LE.SC2Map` until the packaging decision (patch tracked file vs build-time
  rewrite vs separate artifact) lands. End-to-end verified: `hima run` in the
  game container reaches `in_game`, `get_information` passes, advisor calls
  flow.
- macOS container VMs (Docker Desktop, OrbStack) expose no Apple-GPU
  passthrough: a containerized Ollama runs CPU-only. The leader runs on native
  Ollama (`brew install ollama`); the compose `ollama` service targets Linux
  hosts (NVIDIA block commented in `docker-compose.yml`).
- Measured on the M4 Pro host: the containerized CPU Ollama never finishes a
  qwen3:8b leader completion inside the openai client's 600 s timeout; native
  Ollama (Metal) answers the same call in 29.5 s.
- Native leader on a host that also runs the compose stack: the container
  publishes 11434, so start the native server on another port —
  `OLLAMA_HOST=127.0.0.1:11435 OLLAMA_CONTEXT_LENGTH=16384 ollama serve` —
  and pass `--base-url http://host.docker.internal:11435/v1` to `hima run`
  (OrbStack forwards `host.docker.internal` to the host loopback).
- Ollama's default context is 4096 tokens; `OLLAMA_CONTEXT_LENGTH` raises it
  server-wide for leader prompts.
- Leader portability lives in the endpoint contract, not the engine: `hima run`
  prechecks `GET {HIMA_LEADER_BASE_URL}/models` with `HIMA_LEADER_API_KEY` as
  bearer token, so any OpenAI-compatible server (Ollama, vLLM, hosted
  providers) serves the leader.
