FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c

WORKDIR /opt/phase0
COPY --chown=1000:1000 docker/auth-control-plane/auth_control_plane_proxy.mjs /opt/phase0/auth_control_plane_proxy.mjs

USER 1000:1000
ENTRYPOINT ["node", "/opt/phase0/auth_control_plane_proxy.mjs"]
