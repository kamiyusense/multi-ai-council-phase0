FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /opt/phase0

USER root
RUN install -d -o 1000 -g 1000 -m 0700 /opt/phase0
COPY --chown=1000:1000 claude_oauth_egress_proxy.py /opt/phase0/claude_oauth_egress_proxy.py

USER 1000:1000
ENTRYPOINT ["python3", "/opt/phase0/claude_oauth_egress_proxy.py"]
CMD ["serve"]
