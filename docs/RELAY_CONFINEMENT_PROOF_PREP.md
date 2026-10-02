# Relay Confinement Proof Preparation

This document defines a machine-checkable STATIC proof-preparation contract for `common_confinement`. It defines exactly what a future separately authorized bounded proof must observe to establish filesystem/network/process confinement for each provider path, without executing any provider/model/API turn, changing settings, or claiming confinement is already proven.

## Static Declarations Are Insufficient

- A disposable workspace design alone does not prove runtime confinement.
- A path allowlist alone does not prove runtime confinement.
- A container declaration alone does not prove runtime confinement.
- A mock test alone does not prove runtime confinement.

## Current State Contract

| provider_id | workspace_boundary_state | filesystem_confinement_state | network_confinement_state | child_process_state | teardown_state | restart_replay_state | evidence_stage | blocker_state |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openai | STATIC_PREPARED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | UNKNOWN | BLOCKED_UNKNOWN |
| anthropic | STATIC_PREPARED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | UNKNOWN | BLOCKED_UNKNOWN |
| google | STATIC_PREPARED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | UNKNOWN | BLOCKED_UNKNOWN |

## Required Evidence

Future bounded-proof evidence fields:
- `provider_id`
- `proof_correlation_id`
- `observed_workspace_root`
- `filesystem_boundary_observation`
- `network_boundary_observation`
- `child_process_observation`
- `teardown_observation`
- `restart_observation`
- `forbidden_path_probe_result`
- `forbidden_network_probe_result`
- `evidence_source`
- `evidence_locator_or_hash`
- `captured_at`
- `verification_state`

## Properties that must be explicitly distinguished:
- checked-in workspace/path isolation;
- actual runtime filesystem reachability;
- actual runtime network reachability;
- child/subprocess inheritance;
- teardown/cancellation;
- restart/recovery behavior;
- proof that host secrets/credential paths are not reachable;
- proof event identity and evidence source.

## Safety and Provenance Rules

- No raw secrets/tokens/credential values belong in future evidence.
- Evidence must be provider- and proof-event-bound; one provider cannot satisfy another.
- Fail closed / remain BLOCKED_UNKNOWN when any of these are unknown or ambiguous:
    - filesystem reachability
    - network reachability
    - child-process inheritance
    - teardown completion
    - restart/replay behavior
    - forbidden host path exposure
    - evidence provenance
    - provider/proof-event binding.
- If proving a property would require accessing a real secret or sending a provider/model request, that proof method is forbidden; use synthetic markers or safe negative probes only in a later separately authorized harness.
- Zero live confinement evidence is acquired by this batch.
- `common_confinement` remains unresolved/BLOCKED_UNKNOWN.
