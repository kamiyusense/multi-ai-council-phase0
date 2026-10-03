<!-- DRY RUN ONLY: rendered from proposed-registry-v3-fixture.json with no lane inputs; never written to Issue #33 -->
🚦 Phase 0 — 🟢0 SEMI / 🟣0 AUTO / 🔴4 NEEDS YOU

<!-- phase0-loop-runtime:start -->
# Runtime Loops

この一覧は **display surface only** です。durable correctnessの正本は
state / owner chain / receipt / evidence / provider observation / fresh target / authority/fencing です。

## 🔴 HUMAN NEEDED

- **Chat -> Jules** — REVIEW REQUIRED (UNKNOWN): verified per-loop projection is unavailable
- **Chat -> Work** — REVIEW REQUIRED (UNKNOWN): verified per-loop projection is unavailable
- **Claude -> Jules** — REVIEW REQUIRED (UNKNOWN): verified per-loop projection is unavailable
- **Work -> Jules** — REVIEW REQUIRED (UNKNOWN): verified per-loop projection is unavailable

| Signal | Loop | Mode | Controller → Worker | Schedule | Target | Gen | Last durable event | Human |
| --- | --- | --- | --- | --- | --- | ---: | --- | --- |
| ⚪ UNKNOWN | Chat -> Jules | SEMI_AUTO | ChatGPT → Jules | - | - | - | UNKNOWN | REVIEW REQUIRED |
| ⚪ UNKNOWN | Chat -> Work | SEMI_AUTO | ChatGPT → Work | - | - | - | UNKNOWN | REVIEW REQUIRED |
| ⚪ UNKNOWN | Claude -> Jules | AUTO | Claude → Jules | - | - | - | UNKNOWN | REVIEW REQUIRED |
| ⚪ UNKNOWN | Work -> Jules | AUTO | Work → Jules | - | - | - | UNKNOWN | REVIEW REQUIRED |

❄ **Frozen (not counted as active):** Claude -> Claude

## Notification policy

- RUNNING / heartbeat / status refresh: body/title refresh only; no notification comment.
- Notification classes are limited to **TURN COMPLETE** and **HUMAN NEEDED**.
- Dedupe identity is loop_id + durable event_id; replay is a NO-OP.

<!-- phase0-control-tower-json:v1
{"generated_at":"2026-10-04T00:00:00Z","loops":[{"controller_kind":"CHATGPT","display_name":"Chat -> Jules","display_state":"UNKNOWN","generation":null,"human_action":"REVIEW REQUIRED","identity_state":"DURABLE","last_event_id":null,"last_event_kind":"UNKNOWN","loop_id":"chatgpt-semi-auto","mode":"SEMI_AUTO","safe_detail_ref":"issue:33","schedule_hint":null,"target_ref":null,"worker_kind":"JULES"},{"controller_kind":"CHATGPT","display_name":"Chat -> Work","display_state":"UNKNOWN","generation":null,"human_action":"REVIEW REQUIRED","identity_state":"PLACEHOLDER","last_event_id":null,"last_event_kind":"UNKNOWN","loop_id":"chat-work-semi-auto","mode":"SEMI_AUTO","safe_detail_ref":"issue:33","schedule_hint":null,"target_ref":null,"worker_kind":"WORK"},{"controller_kind":"CLAUDE","display_name":"Claude -> Jules","display_state":"UNKNOWN","generation":null,"human_action":"REVIEW REQUIRED","identity_state":"PLACEHOLDER","last_event_id":null,"last_event_kind":"UNKNOWN","loop_id":"claude-jules-auto","mode":"AUTO","safe_detail_ref":"issue:33","schedule_hint":null,"target_ref":null,"worker_kind":"JULES"},{"controller_kind":"WORK","display_name":"Work -> Jules","display_state":"UNKNOWN","generation":null,"human_action":"REVIEW REQUIRED","identity_state":"PLACEHOLDER","last_event_id":null,"last_event_kind":"UNKNOWN","loop_id":"work-jules-auto","mode":"AUTO","safe_detail_ref":"issue:33","schedule_hint":null,"target_ref":null,"worker_kind":"JULES"}],"project":"phase0","schema_version":1}
-->
<!-- phase0-loop-runtime:end -->
