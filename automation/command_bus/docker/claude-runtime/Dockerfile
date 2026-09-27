FROM node:20-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0

ENV CLAUDE_CONFIG_DIR=/home/node/.claude
WORKDIR /home/node

USER root
RUN install -d -o 1000 -g 1000 -m 0700 /home/node/.claude /opt/phase0
COPY --chown=1000:1000 docker/claude-runtime/claude_runtime_launcher.mjs /opt/phase0/claude_runtime_launcher.mjs
RUN npm install --global @anthropic-ai/claude-code@2.1.283

USER node
ENTRYPOINT ["node", "/opt/phase0/claude_runtime_launcher.mjs"]
