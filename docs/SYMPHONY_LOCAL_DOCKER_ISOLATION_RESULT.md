# Local approved Docker acquisition and isolation — PASS / LIVE NO-GO

Work order: PR #343 comment6097786830. Measured source and starting development HEAD `e43636c07f2e51245fdb28a360ed4d7c6847b249`; main `abb5402079d4af341c349ea9e8b6a8a5c3f2d37c`. The final PR receipt binds the evidence-only development commit, exact-head CI/run/job/artifact digests and full remote byte readback. This measurement replaces the prior Local NOT_RUN_IMAGE_UNAVAILABLE gate; old evidence remains immutable and accurate for its own time.

## Exact authorized acquisition

The remote workflow blob and Local bytes matched at the fresh HEAD; workflow SHA256 `28c6085b5c9bbe335dc242ba3a2584e64da7943fce5e03b490f134889727e37e`. Its PYTHON_IMAGE/SCANNER_IMAGE strings matched the user's authorization exactly.

- Official Docker Hub `python@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce`: absent before, one normal pull, exit0, exact RepoDigest/linux/amd64 readback. Public runtime version Python3.11.17; size187061249 bytes.
- GHCR `ghcr.io/gitleaks/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f`: absent before, one normal pull, exit0, exact RepoDigest/linux/amd64 readback. Public runtime version v8.30.1; size76584831 bytes.

No alternate tag/registry/image, retag, repeated pull, login/credential entry, daemon/config/permission/Billing change. Normal system-reviewed command path used. Actual Ubuntu WSL2 → Docker Desktop4.91.0/Engine29.8.0 connected. WSL/Windows free-space observations are saved; Docker Desktop VHD free capacity was not inferred from host df and remains UNKNOWN. No disk-space error occurred.

## Actual Local container proof

Five test containers and two mount-free public-version containers used the exact images with pull=never. Root read-only, network none, uid65534, cap-drop ALL, no-new-privileges, CPU2/memory256MiB/PIDs64, restricted tmpfs64MiB with noexec/nosuid. No port/host PID/host IPC, Docker socket, .git, home/config/credential or real workspace mount. Only the new dedicated synthetic fixture and a minimal hash-pinned operator code dependency closure were mounted read-only; the two-file full synthetic candidate inventory/bytes were verified before/after.

The existing CI's original isolation/syntax/candidate export and independent behavior test were reused without a new mock phase. The additional runtime probe measured actual UID, CapEff0, NoNewPrivs1, root/source/candidate ro mounts, write rejection, loopback-only interface and cgroup memory.max268435456/pids.max64/cpu.max ratio2. Forbidden credential/base-url/MAC/event selector presence was checked by name only and was zero. Docker inspect separately verified every test container's configured image, resources and readonly bind source whitelist.

| Case | Exit | Result |
| --- | --- | --- |
| Python runtime probe + original source/full-candidate syntax | 0 | PASS |
| Original read-only host/provenance12 integration tests + independent synthetic behavior | 0 | PASS |
| Gitleaks clean fixture | 0 | PASS |
| Gitleaks complete synthetic candidate | 0 | PASS |
| Gitleaks intentionally synthetic negative fixture | 1 | PASS_EXPECTED_REFUSAL |

The negative string was fabricated solely for this test and is not an account credential. Logs are redacted/sanitized; no raw negative credential-shaped file is committed. Local fixture archive SHA256 `6f20666d48e0136eb26c7e5fa88f194e1d6d6f46aa00dcfa7b27651d5b853016`; original fixture archive and full operator records are retained in Windows storage. Every source/fixture file SHA is indexed in fixture-manifest.json; each terminal log has separate byte/compressed hashes.

All seven containers exited and were removed only after evidence capture, without force/prune or touching others. The first cleanup helper reply assertion failed; readback proved that one container absent before continuing, with no resend. This did not affect the five successful measurements. Exact cleanup receipts and the intermediate readback are retained. Both approved images and the prior persistent backup (archive SHA256 `57083b6da83e7c83ae7bacaac6ac7423457d6c0c959721e57d984350374fcd92`) remain.

## Boundary after Local PASS

No production implementation change was needed: reviewed existing GET-only recovery/provenance and prepare-only seams remain unchanged. Official Symphony polling/scheduling/continuation/retry/backoff/stall/concurrency/cleanup is unchanged. Zero new model/provider/worker LIVE, real candidate publication, actual Git adoption, runtime CAS, proof Issue/ref creation, main/parent/sibling/historical ledger write, Merge, billing/permissions/settings change or API fallback.

Local isolation PASS is one completed readiness gate. REAL_CANDIDATE_NOT_QUALIFIED, REAL_SENDER_NOT_WIRED and one-run authorization NONE remain. Independently reviewed operator real-candidate checkout/trusted tests/scanner/real attestation integration and narrow issuer-verifiable sender capability are still required; neither a synthetic test nor image acquisition supplies those authorities. No further Docker settings or image acquisition operation is needed for this observed environment. Future LIVE requires separate explicit approval.

Evidence: `docs/evidence/symphony-local-docker-isolation/`. Source code/workflow/historical evidence unchanged; current readiness report updated and meaningful measured evidence appended. Final remote/CI claims are made only in the final PR receipt after readback.
