# HIMA — multi-agent StarCraft II experiment operations

| File | Content |
|------|---------|
| concept-observation.md | Record vocabulary and live/replay unification of game observation |
| concept-deployment.md | Locked environment, service topology, and game runtime placement |
| design-packages.md | Workspace members, dependency edges, contracts, and image mapping |
| design-cli.md | Modules, classes, and command specifications of the `hima` CLI |
| design-cli-services.md | Service lifecycle subsystem: placement, manifest, health, game job |
| design-cli-run.md | Game run subsystem: game placement and observation surface |
| design-observation.md | Record schema, sampler, store, and server of the observation subsystem |
| design-deployment.md | Image and compose service specifications of the deployment layer |
| impl-cli.md | Verified dotenv, uvicorn factory, and psutil APIs for the CLI design |
| impl-observation.md | Verified SSE, uvicorn, and record-file APIs for the observation design |
| impl-deployment.md | Verified uv, torch-CPU, ollama, and SC2 Linux facts for deployment |
| impl-packages.md | Verified uv workspace, hatchling, and per-member sync facts |
