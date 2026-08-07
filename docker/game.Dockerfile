# The cli member image plus the StarCraft II Linux headless client (4.10)
# and the ladder map from maps/. The image is native-platform; only SC2_x64
# runs under amd64 emulation via qemu-user (design-deployment.md).
#   docker build -t hima-cli --build-arg PACKAGE=hima-dht-cli \
#     -f docker/hima.Dockerfile .
#   SC2_LICENSE=<acceptance> docker compose --profile game build game
ARG HIMA_IMAGE=hima-cli
FROM ${HIMA_IMAGE}

RUN dpkg --add-architecture amd64 \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl unzip qemu-user libc6:amd64 libstdc++6:amd64 \
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

COPY docker/sc2-wrapper.sh /tmp/sc2-wrapper.sh
RUN cd /root/StarCraftII/Versions/Base75689 \
 && mv SC2_x64 SC2_x64.real \
 && install -m 755 /tmp/sc2-wrapper.sh SC2_x64 \
 && rm /tmp/sc2-wrapper.sh

# Lowercase maps/: the SC2 Linux server resolves the relative map path
# against <root>/maps, not the zip's Maps/ (impl-deployment.md).
COPY ["maps/Ancient Cistern LE.SC2Map", "/root/StarCraftII/maps/"]

ENV SC2PATH=/root/StarCraftII
