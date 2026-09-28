FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c

ENV CLAUDE_CONFIG_DIR=/home/node/.claude
WORKDIR /home/node

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap socat \
    && rm -rf /var/lib/apt/lists/*
RUN install -d -o 1000 -g 1000 -m 0700 /home/node/.claude /opt/phase0
COPY --chown=1000:1000 docker/claude-runtime/claude_runtime_launcher.mjs /opt/phase0/claude_runtime_launcher.mjs
RUN npm install --global @anthropic-ai/claude-code@2.1.283

USER node
ENTRYPOINT ["node", "/opt/phase0/claude_runtime_launcher.mjs"]
