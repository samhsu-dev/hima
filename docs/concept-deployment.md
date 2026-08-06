# Concept — Deployment Topology (`docker/`)

## 1. Context

**Problem Statement** — Experiments must reproduce across devices, but the parts have
unequal portability: Python dependencies lock cleanly, model services containerize
cleanly, while StarCraft II and Apple-silicon inference resist containers. The
deployment layer states what runs where and how the parts reach each other.

**System Role** — Deployment layer: packages every portable part as a container image
built from the locked environment, and names the host-native placements for the rest.

**Data Flow**
- **Inputs:** the locked environment (one lock file for all platforms), advisor model
  weights, leader model weights, the StarCraft II program.
- **Outputs:** running advisor and leader services; on Linux, a containerized game
  runtime; archives reachable by the observation subsystem.
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
macOS device                          Linux device
  game process (native, retail 5.0.16)  game container (headless 4.10)
      |            \                        |            \
      v             v                       v             v
  advisor service   leader service      advisor service   leader service
  (container/native)(container/native)  (container)       (container)
```

**Core Concepts**

- **Name:** Locked environment
  - **Definition:** The single dependency lock resolving every platform; every image
    and every native install derives from it.
  - **Scope:** Python dependencies only. Excludes model weights and the game program.
  - **Relationships:** Source of every container image; source of the host install.

- **Name:** Advisor service
  - **Definition:** The three fine-tuned advisor models behind one inference endpoint.
  - **Scope:** Weights download on first start into a persistent volume; CPU inference
    in containers, Apple-silicon inference only native.
  - **Relationships:** Built from the locked environment; called by the game process.

- **Name:** Leader service
  - **Definition:** The leader model behind an inference endpoint, in one of two forms:
    a stock image pulling weights once per device into a volume, or a baked image
    carrying the weights so a device needs no pull.
  - **Scope:** The baked form trades image size for offline, per-device-zero-setup use.
  - **Relationships:** Called by the game process; the baked image is built once and
    distributed through a registry.

- **Name:** Game runtime placement
  - **Definition:** Where the game process and StarCraft II run: native on macOS with
    the retail client, or containerized on Linux with the headless client.
  - **Scope:** The two clients differ in game version and balance; results from one
    placement are not comparable with results from the other. The headless client is
    x86-only and requires the user's license acceptance.
  - **Relationships:** Either placement reaches the advisor and leader services over
    the service network; both produce archives the observation subsystem reads.

- **Name:** Service network
  - **Definition:** How the parts address each other: containers by service name on a
    shared network, the host-native game process by published localhost ports.
  - **Scope:** Excludes any cross-device networking.
  - **Relationships:** Connects the game runtime to the advisor and leader services
    and the observation server to browsers.

## 3. Contracts & Flow

**Data Contracts**
- **With the game process:** the advisor and leader endpoints keep the same addresses
  whether their services run native or containerized.
- **With the observation subsystem:** archives land on the host filesystem; the
  observation server reads them regardless of where the game ran.

**Internal Processing Flow**
1. Lock — resolve the environment once; commit the lock.
2. Build — derive each image from the lock; bake the leader image when offline
   distribution is wanted.
3. Run — start services; start the game in its placement; services persist across
   games.

## 4. Scenarios

- **Typical:** On the macOS device, the game runs native for Apple-silicon inference
  and retail-version fidelity; the advisor and leader run as containers or natively.
- **Boundary:** A Linux server runs everything containerized with the headless client;
  its results feed development and regression checks, not version-sensitive
  comparisons with retail runs.
- **Interaction:** A new device clones the repository, restores the locked
  environment, pulls the baked leader image, and replays an archived game without any
  model download.
