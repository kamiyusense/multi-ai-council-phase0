# Relay Minimal-Reuse Roadmap

Updated: 2026-10-01
Status: proposed execution roadmap / documentation only
Source policy: PR #191 Controller Operating Guide + PR #192 Development Acceleration Playbook

## 1. Purpose

This roadmap shortens Relay development by changing the unit of work.

Do not ask Jules to:
- design a complete mechanism;
- make a subsystem production-ready;
- add general safety architecture;
- research broad best practices;
- create a new framework before trying an existing primitive.

Instead, every Jules mission should have this shape:

> Inspect this named upstream implementation, take this named small primitive, adapt it into these named existing Phase 0 files with the smallest compatible diff, and stop.

The target is a minimally connected Relay that can reach the next real integration boundary quickly. Hardening comes after observed failures, not before them.

Fixed Phase 0 boundaries still apply:
- retry=0 / fallback=disabled at the Phase 0 control boundary;
- no automatic API-key / paid-route fallback;
- no billing / credits / overage mutation;
- no dangerous permission bypass;
- no live provider/model execution without explicit approval;
- no default-branch direct write, force push or automatic Merge;
- UNKNOWN at a live safety boundary fails closed.

## 2. Controller rule inherited from PR #191

Use the current Controller Operating Guide for routing and repair decisions.

For each new mission:
1. fresh-read current target HEAD/tree and relevant current carrier;
2. choose the smallest implementation boundary;
3. use Jules normally for bounded code/tests/docs work;
4. after a FAIL, diagnose first;
5. Controller repairs a small local defect directly when safe;
6. only return to Jules for a semantic/substantial defect;
7. publish to a non-default canonical branch only after independent verification and fast-forward safety.

A previous worker choice does not make that worker sticky. A task should not be sent to WORK merely because it is difficult if a small bounded Jules task is available.

## 3. Acceleration rule inherited from PR #192

Before implementing anything:
1. reuse accepted repository code;
2. use provider/platform official implementation;
3. use a tiny permissively licensed upstream primitive;
4. use design-only reference if direct reuse is unnecessary;
5. write new generic infrastructure only as the last option.

Do not add queues, DLQs, orchestration frameworks, new databases, dashboards, retry engines or generalized abstractions unless a measured failure proves the existing smaller route insufficient.

## 4. Current Relay parts to preserve

Current Relay canonical branch contains reusable pieces that should not be rewritten merely to adopt upstream components:

- `src/relay/envelope.py`
- `src/relay/duplicate_guard.py`
- `src/relay/dispatcher.py`
- `src/relay/lifecycle.py`
- `src/relay/result.py`
- `src/relay/core_adapter.py`
- `src/relay/acp_client.py`
- `src/providers/codex_acp.py`
- `src/providers/claude_acp.py`
- `src/providers/antigravity_acp.py`
- `src/providers/policy.py`
- `src/providers/preflight.py`

Existing Claude Admission Gate remains the host-owned one-upstream-generation boundary:
- `automation/command_bus/claude_admission_gate.py`

The goal is to replace or simplify provider-specific plumbing behind these seams, not redesign the whole Relay.

## 5. Stop extending the checklist factory

After the currently active Antigravity billing-route result is independently reviewed, do not automatically create one new Markdown proof contract + one bespoke parser test for every remaining UNKNOWN.

Existing readiness/checklist/proof files remain as evidence and reference. Do not delete them merely to make the tree smaller.

For the next mock/static integration phase:
- freeze further checklist expansion;
- keep live execution blocked;
- use existing `live_readiness*` and proof documents as reference/cold-path evidence;
- do not require every hypothetical future proof to be fully automated before connecting official adapters in mock/static mode.

If a real integration test later exposes a missing guard, add that exact regression only then.

## 6. Reuse target A — ACP protocol/runtime plumbing

Upstream:
- `agentclientprotocol/python-sdk`
- Apache-2.0 family project; verify current license/commit before direct copying.

Reuse target:
- generated/schema types where useful;
- stdio JSON-RPC transport;
- subprocess/process-lifecycle helper behavior.

Local destination:
- primarily `src/relay/acp_client.py`
- only touch `src/relay/transport.py` or `src/relay/lifecycle.py` if the existing seam cannot accept the primitive.

Jules mission wording:

> Inspect `agentclientprotocol/python-sdk` and the current `src/relay/acp_client.py`. Adapt only the smallest stdio/process/JSON-RPC primitive needed to remove equivalent handwritten plumbing. Preserve current Relay interfaces. Do not redesign lifecycle, dispatcher, envelopes, receipts, readiness or provider policy. Do not add a new abstraction layer.

Acceptance:
- existing caller interface preserved or minimally adapted;
- one focused mock test proving the borrowed primitive is wired;
- existing Relay suite stays green;
- no provider/model execution.

## 7. Reuse target B — Codex adapter

Upstream:
- `agentclientprotocol/codex-acp`
- use the official adapter as the Codex-facing process instead of reproducing its translation logic.

Local destination:
- `src/providers/codex_acp.py`
- existing `src/relay/acp_client.py` seam.

Do not copy the whole upstream repository into Phase 0. Prefer invoking/pinning the upstream adapter and keeping local code as a thin profile/launch mapping.

Jules mission wording:

> Inspect current `src/providers/codex_acp.py` and official `agentclientprotocol/codex-acp`. Replace only the local Codex-specific ACP translation/launch plumbing that the official adapter already supplies. Keep current ProviderStaticProfile/preflight/Relay lifecycle unchanged. Do not design a new Codex backend.

Important limit:
Codex has provider-internal request/stream/auth-recovery retry paths. Do not spend more development loops attempting to prove every internal retry path away before mock integration.

For Phase 0, the later live path should use a host-owned one-upstream-generation admission boundary analogous to the existing Claude Gate if mock routing proves ChatGPT subscription traffic can be safely bound through it. That boundary should be a small adaptation of existing gate semantics, not a new safety framework.

## 8. Reuse target C — Claude adapter

Upstream:
- `agentclientprotocol/claude-agent-acp`

Local destination:
- `src/providers/claude_acp.py`
- existing ACP client seam
- existing Claude Admission Gate remains outside/around model upstream transmission.

Jules mission wording:

> Inspect current `src/providers/claude_acp.py` and official `agentclientprotocol/claude-agent-acp`. Adapt the smallest official launch/session primitive necessary to replace equivalent local Claude ACP plumbing. Preserve the existing Admission Gate as the one-upstream-generation boundary. Do not redesign Claude retry handling, auth control, Gate persistence or lifecycle.

Use official permission/session controls where available rather than adding another local permission framework.

Do not resume research whose goal is “prove native Claude never retries.” Phase 0 already has a stronger outer invariant: additional generation attempts must not become additional upstream generations.

## 9. Reuse target D — Google Antigravity adapter

Preferred upstream:
- ACP Registry entry for Google-distributed Antigravity ACP server / `agy_acp_server`.

Local destination:
- `src/providers/antigravity_acp.py`
- current ACP client seam.

Jules mission wording:

> Inspect current `src/providers/antigravity_acp.py` and the official ACP Registry Antigravity package. Replace only the local Antigravity ACP launch/binary-selection plumbing that the Google-distributed `agy_acp_server` already supplies. Preserve current provider policy/preflight and Relay lifecycle. Do not create a custom Antigravity shim.

Do not substitute Gemini CLI merely because it is easier. The selected target remains Antigravity unless a later explicit product decision changes it.

## 10. Reuse target E — Antigravity read-only account/billing observations

Preferred upstream:
- Antigravity CLI read-only print-mode slash commands when present in the selected runtime:
  - `/usage`
  - `/quota`
  - `/credits`
  - `/model`
  - other explicitly read-only print commands only when required.

Goal:
Use official machine-readable read-only output before inventing a billing/account probe.

Local action:
- first attempt direct bounded parsing at the current evidence seam;
- store classifications/hashes/locators, not raw secrets or private account/billing identifiers;
- if the official command does not expose enough evidence, leave the field UNKNOWN;
- do not create a second framework to “complete” missing upstream visibility.

Jules mission wording:

> Reuse the official Antigravity CLI read-only JSON output for this exact field. Add only the smallest parser/adapter needed by the existing evidence structure. Do not build a general account/billing inspection subsystem. If the official output does not contain the required fact, return UNKNOWN.

## 11. Reuse target F — ACP conformance testing

Upstream:
- `agentclientprotocol/acp-tck`

Use it for:
- initialize;
- session lifecycle;
- prompt;
- cancel;
- close;
- transport/error conformance.

Do not port its test suite into Phase 0.
Do not create duplicate bespoke conformance fixtures unless:
1. TCK demonstrates a failure;
2. the failure is Phase 0-specific;
3. a local regression is needed for the exact adapter patch.

Jules mission wording for a failure:

> Reproduce only ACP-TCK failure <ID> against the current adapter. Port no general TCK framework. Apply the smallest local patch that makes this one upstream conformance case pass while preserving existing Relay behavior.

## 12. Development/debug tool — record/replay only when needed

Candidate:
- OrcaReplay or an equivalent current permissively usable recorder/replayer.

Rule:
Do not integrate record/replay into production Relay.
Use it only as a development tool when a provider path is difficult to observe and a captured/replayed request materially shortens diagnosis.

If ordinary logs + existing receipts answer the question, do not add record/replay.

## 13. Parts explicitly deferred from the minimal hot path

Do not delete these now; simply stop expanding/wiring them into every mock milestone unless needed:

- additional per-gap proof-contract documents;
- additional readiness schema variants;
- generalized provenance frameworks;
- new filesystem/network confinement subsystems;
- generalized model-verification framework;
- generic billing/account framework;
- generic retry inspector;
- custom ACP compatibility harness beyond ACP-TCK;
- new workflow engine / queue / database.

They may return only after observed evidence shows the minimal path cannot proceed safely.

## 14. Preferred execution order

### M0 — finish current result, then freeze checklist expansion

- independently review the current Antigravity billing-route Jules result;
- if acceptable, adopt it by the existing exact-head/fast-forward process;
- do not automatically dispatch another “one blocker = one checklist” task.

Exit:
- current result is PASS/FAIL/UNKNOWN with evidence;
- no new checklist task is queued by default.

### M1 — prove the existing Relay seam can host one official ACP adapter

Pick one provider only. Prefer the one requiring the least local change.

Task:
- wire one official adapter behind current `ACPClient` / provider profile;
- no generalized refactor;
- mock/static only.

Exit:
- existing dispatcher/lifecycle can start/communicate with one official adapter in a fake/no-provider mode;
- focused test + existing Relay tests green.

### M2 — Codex: minimum official-adapter wiring

Task:
- thin local `codex_acp.py` launch/profile mapping to official `codex-acp`;
- no internal retry research;
- no live ChatGPT turn.

Exit:
- static/mock session handshake works;
- existing Relay result path receives expected structured events.

### M3 — Claude: minimum official-adapter wiring

Task:
- thin local `claude_acp.py` mapping to official `claude-agent-acp`;
- retain existing Admission Gate;
- use upstream permission/session primitive instead of adding another system.

Exit:
- fake/local/no-provider handshake works through current Relay;
- no change to live authorization.

### M4 — Antigravity: minimum official-adapter wiring

Task:
- use Google-distributed `agy_acp_server`;
- replace custom binary/ACP assumptions only where necessary;
- no Gemini CLI fallback;
- no live model turn.

Exit:
- local/static ACP handshake works through current Relay.

### M5 — run upstream ACP-TCK

Run TCK against each selected adapter.

Rule:
- PASS => do not add local duplicate tests;
- FAIL => one small corrective task for the exact failing case;
- SKIP/unsupported capability => do not invent support unless Phase 0 actually needs that capability.

Exit:
- required ACP subset has upstream conformance evidence.

### M6 — use official read-only account/quota surfaces

Before any live model turn:
- consume official read-only account/usage/quota/model output where available;
- map only required facts into existing evidence fields;
- UNKNOWN stays UNKNOWN.

Do not build a generalized inspector.

### M7 — static/mock three-provider E2E

Exercise:

```text
Phase 0 request
-> existing dispatcher / duplicate guard
-> current provider profile
-> official ACP adapter/server
-> fake/local terminal result
-> existing receipt/result
```

No model/provider generation is required.

Exit:
- one request produces one local execution path and one result per provider;
- duplicate request remains NO-OP at the Phase 0 layer.

### M8 — add only the minimum live admission boundary still missing

Claude:
- reuse existing Admission Gate.

Codex:
- if current mock route proves the subscription endpoint can be safely proxied, adapt the existing one-generation gate pattern rather than create a new system.

Antigravity:
- only add an equivalent outer request-count gate if the selected official runtime exposes a practical interception point and live proof requires it.
- if it does not, leave live status UNKNOWN rather than create speculative machinery.

Exit:
- there is a small, inspectable “at most one upstream generation” control for each provider where technically feasible.

### M9 — first bounded live proof

This is an explicit human approval boundary.

Run the smallest possible proof:
- one provider at a time;
- one dispatch;
- one generation;
- no automatic retry/fallback by Phase 0;
- readback/receipt;
- stop.

Do not combine first-live testing with new feature development.

### M10 — harden only from observed defects

For every observed defect:
1. preserve exact evidence;
2. identify one cause;
3. patch the smallest component;
4. add one regression for that defect;
5. re-run only the required focused/full validation.

Do not convert an incident into a platform redesign unless repeated evidence proves the small repair insufficient.

## 15. Jules prompt contract for this roadmap

Every roadmap task should contain these sections:

```text
Upstream source:
<repo + exact file/module/release/registry entry>

Small component to reuse:
<one concrete primitive>

Existing local destination:
<one or a few current Phase 0 files>

Do:
- adapt the named primitive with the smallest compatible diff
- preserve current interfaces unless the primitive requires one minimal seam change
- run the named focused tests and current required suite

Do not:
- design a complete mechanism
- add a framework/abstraction “for future use”
- refactor unrelated Relay code
- add speculative safety/features
- expand the task because another improvement looks useful
- add retry/fallback
- perform live provider/model execution
- Merge

Stop condition:
If the small primitive cannot fit without a broad redesign, stop and report the exact incompatibility. Do not redesign around it.
```

Bad prompt:
> Design a complete safe Codex transport and all tests necessary for production.

Good prompt:
> Inspect official `codex-acp` launch/session code and current `src/providers/codex_acp.py`. Replace only the duplicate Codex ACP launch/translation code with the official adapter path. Touch only the provider adapter plus one focused test unless a minimal seam change is strictly required.

## 16. Controller acceptance rule

A roadmap step is complete enough to move forward when:
- the named upstream primitive is connected;
- current fixed safety boundaries are unchanged;
- the next real integration boundary can be exercised;
- failure is observable;
- the change is reversible/non-adoptable;
- independent validation is green.

Do not wait for:
- every future blocker to have a bespoke document;
- every provider-internal behavior to be fully explained;
- every hypothetical negative case to have a local test;
- every hardening idea to be implemented.

## 17. Canonical direction

The desired shrinking architecture is:

```text
existing Phase 0 envelope / duplicate guard / lifecycle
                    |
              thin ACP seam
        +-----------+-----------+
        |           |           |
 official       official      Google official
 codex-acp   claude-agent-acp  agy_acp_server
        |           |           |
   thin live admission/request-count boundary where required
                    |
             provider subscription route
```

Keep Phase 0-specific code only where upstream cannot own the policy:
- duplicate dispatch prevention;
- one-upstream-generation admission;
- no paid/API fallback;
- no dangerous permission bypass;
- evidence/receipt correlation;
- human live/Merge boundary.

Everything else should earn its continued custom implementation through a concrete need.
