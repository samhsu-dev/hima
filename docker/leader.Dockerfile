# Leader service with qwen3:8b baked into the image at build time.
# Build once, push to a registry, and any device runs the leader offline:
#   docker compose --profile baked build leader-baked
# The image is ~6 GB (qwen3:8b weights included). Pinned to the same Ollama
# version as the local client so baked weights and server always match.
FROM ollama/ollama:0.32.5

# Start a temporary server inside this build layer, wait until it answers
# (bounded to 60 attempts), pull the model, then let the layer's shell exit.
RUN ollama serve & \
    for attempt in $(seq 1 60); do \
        ollama list >/dev/null 2>&1 && break; \
        sleep 1; \
    done && \
    ollama pull qwen3:8b

EXPOSE 11434
