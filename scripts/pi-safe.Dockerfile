# Pi safe profile image. The Pi version is pinned for reproducible local use.
FROM node:24-bookworm-slim

ARG PI_VERSION=0.84.1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends bash ca-certificates git ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global --ignore-scripts "@earendil-works/pi-coding-agent@${PI_VERSION}"

WORKDIR /workspace
ENTRYPOINT ["pi"]
