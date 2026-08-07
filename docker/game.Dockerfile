# The cli member image plus the StarCraft II Linux headless client (4.10)
# and the ladder map from maps/. linux/amd64 only (design-deployment.md).
# Build the cli base for that platform, then this image with the license
# acceptance:
#   docker build --platform linux/amd64 -t hima-cli:amd64 \
#     --build-arg PACKAGE=hima-dht-cli -f docker/hima.Dockerfile .
#   SC2_LICENSE=<acceptance> docker compose --profile game build game
ARG HIMA_IMAGE=hima-cli:amd64
FROM ${HIMA_IMAGE}

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl unzip \
 && rm -rf /var/lib/apt/lists/*

# The unzip password is Blizzard's AI and Machine Learning License
# acceptance; it never gets a default (concept-deployment.md).
ARG SC2_LICENSE
RUN test -n "${SC2_LICENSE}" || { \
      echo "build arg SC2_LICENSE required: Blizzard's AI and Machine Learning License acceptance"; \
      exit 1; }
RUN curl -fSL https://blzdistsc2-a.akamaihd.net/Linux/SC2.4.10.zip -o /tmp/SC2.zip \
 && unzip -q -P "${SC2_LICENSE}" /tmp/SC2.zip -d /root \
 && rm /tmp/SC2.zip

COPY ["maps/Ancient Cistern LE.SC2Map", "/root/StarCraftII/Maps/"]

ENV SC2PATH=/root/StarCraftII
