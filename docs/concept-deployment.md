# Concept — Deployment Topology (`docker/`)

## 1. Context

**Problem Statement** — Experiments must reproduce on any device with no cloud
dependency: the game headless in a container, the leader and advisor models served
locally. The parts have unequal portability — Python dependencies lock cleanly and
model services containerize cleanly, while retail StarCraft II and Apple-silicon
inference resist containers — so the fully containerized stack is the reference
placement and the host-placed game is a development placement.

**System Role** — Deployment layer: packages every part as a container image built
from the locked environment, and names the host placements that remain outside it.

**Data Flow**
- **Inputs:** the locked environment (one lock file for all platforms), advisor model
  weights, leader model weights, the StarCraft II program.
- **Outputs:** running advisor and leader services; a containerized game runtime on
  any device (amd64 emulation on Apple silicon); archives reachable by the
  observation subsystem.
- **Connections:** game process → advisor service; game process → leader service;
  observation server → run archive.

**Scope Boundaries**
- **Owned:** container images, service topology, ports and volumes, cross-device
  reproducibility of the environment.
- **Not Owned:** experiment semantics (`design-cli.md`), the observation record schema
  (`concept-observation.md`), model fine-tuning, license acceptance (the user accepts the
  StarCraft II license themselves).

## 2. Concepts

**Conceptual Diagram**

```
Any device (reference)                macOS device (development)
  game container (headless 4.10)        game process (host, retail 5.0.16)
      |            \                        |            \
      v             v                       v             v
  advisor service   leader service      advisor service   leader service
  (container)       (container)         (container/host)  (container/host)
```

**Core Concepts**

- **Name:** Locked environment
  - **Definition:** The single dependency lock resolving every platform; every image
    and every host install derives from it.
  - **Scope:** Python dependencies only. Excludes model weights and the game program.
  - **Relationships:** Source of every container image; source of the host install.

- **Name:** Advisor service
  - **Definition:** The three fine-tuned advisor models behind one inference endpoint.
  - **Scope:** Weights download on first start into a persistent volume; CPU inference
    in containers, Apple-silicon inference only on the host.
  - **Relationships:** Built from the locked environment; called by the game process.

- **Name:** Leader service
  - **Definition:** The leader model behind an inference endpoint, in one of two forms:
    a stock image pulling weights once per device into a volume, or a baked image
    carrying the weights so a device needs no pull.
  - **Scope:** The baked form trades image size for offline, per-device-zero-setup use.
  - **Relationships:** Called by the game process; the baked image is built once and
    distributed through a registry.

- **Name:** Game runtime placement
  - **Definition:** Where the game process and StarCraft II run: containerized with
    the headless client on any device (the reference placement), or on the host on
    macOS with the retail client (a development placement).
  - **Scope:** The two clients differ in game version and balance; results from one
    placement are not comparable with results from the other. The headless client is
    x86-only and requires the user's license acceptance; the ladder map is not
    redistributable, so each device supplies it from a retail installation.
  - **Relationships:** Either placement reaches the advisor and leader services over
    the service network; both produce archives the observation subsystem reads.

- **Name:** Deployment axis
  - **Definition:** One independent choice a deployment makes: where the services
    run, whether an observation server exists, where the game runs, and which
    surface a human watches through.
  - **Scope:** No value of one axis constrains another; a containerized game
    reaches host services as readily as containerized ones, and any surface
    watches either game placement.
  - **Relationships:** The service and game runtime placements are two axes over
    the same host/container choice; the observation surface reads the archives
    both game placements write.

- **Name:** Service network
  - **Definition:** How the parts address each other: containers by service name on a
    shared network, a host-placed part by published localhost ports and the host
    gateway name.
  - **Scope:** Excludes any cross-device networking.
  - **Relationships:** Connects the game runtime to the advisor and leader services
    and the observation server to browsers.

## 3. Contracts & Flow

**Data Contracts**
- **With the game process:** the advisor and leader endpoints keep the same addresses
  whether their services run on the host or in containers.
- **With the observation subsystem:** archives land on the host filesystem; the
  observation server reads them regardless of where the game ran.

**Internal Processing Flow**
1. Lock — resolve the environment once; commit the lock.
2. Build — derive each image from the lock; bake the leader image when offline
   distribution is wanted.
3. Run — start services; start the game in its placement; services persist across
   games.

## 4. Scenarios

- **Typical:** Any device runs the full containerized stack — headless game, advisor,
  and leader — and one compose invocation reproduces an experiment; runs compare with
  other containerized runs.
- **Boundary:** The macOS device runs the game on the host for Apple-silicon inference and
  retail-version fidelity; those runs are version-sensitive and compare only with
  other retail runs.
- **Interaction:** A new device clones the repository, restores the locked
  environment, pulls the baked leader image, and replays an archived game without any
  model download.
