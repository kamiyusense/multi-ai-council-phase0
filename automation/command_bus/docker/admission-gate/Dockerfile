FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /opt/phase0

USER root
RUN install -d -o 1000 -g 1000 -m 0700 /opt/phase0 /var/lib/phase0/claude-gate
COPY --chown=1000:1000 claude_admission_gate.py /opt/phase0/claude_admission_gate.py
COPY --chown=1000:1000 claude_gate_compose.yaml /opt/phase0/claude_gate_compose.yaml
COPY --chown=1000:1000 docker/admission-gate/gate_entrypoint.py /opt/phase0/gate_entrypoint.py
COPY --chown=1000:1000 docker/admission-gate/gate_bootstrap_entrypoint.py /opt/phase0/gate_bootstrap_entrypoint.py

USER 1000:1000
ENTRYPOINT ["python3", "/opt/phase0/gate_entrypoint.py"]
CMD ["serve"]
