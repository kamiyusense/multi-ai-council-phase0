# Visible Work Routing Checkpoint — 2026-09-24

Repository: `kamiyusense/multi-ai-council-phase0`

## Goal

Remove the requirement that the human manually finds the hidden Work execution
created by a GitHub event-triggered Scheduled Task.

## Canonical target

- PR #4 branch: `feature/relay-transport-7070955470193506982`
- frozen head: `2fc399ac7b415746763114c3951aa2e3b45adee7`
- frozen tree: `9e2d22b7caf001449d1a5aa4fd374fec81a415fe`

## Priority 1 — Scheduled Task associated chat

OpenAI product documentation confirms the Scheduled Task model has an
associated chat: deleting the associated chat pauses the task, while deleting
the task does not delete the associated chat.

Official references:
- https://help.openai.com/ja-jp/articles/10291617-chatgpt-%E3%81%AE%E3%82%BF%E3%82%B9%E3%82%AF
- https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex

For the exact Scheduled Task `Phase 0 PR6 Command Bus`, however, current
task-management metadata exposed to this control path does not directly prove a
stable user-visible/openable associated-chat locator. Two bounded event-trigger
discovery commands did not produce durable per-task associated-chat evidence.

Current classification:
- associated_chat_state = ASSOCIATED_CHAT_PRESENT_BUT_UNVERIFIED
- associated_chat_user_visible = UNKNOWN
- associated_chat_stable = UNKNOWN
- associated_chat_identifier_persisted = false

No chat/thread/conversation/session ID is used as a correctness input.

## Priority 2 — native existing-thread delegation

A bounded capability-inspection route was attempted from the event-triggered
Work runtime. It produced no durable callable-tool/readback evidence.

Current classification:
- native_thread_delegation_capability = UNKNOWN
- native_thread_delegation_live_tested = false
- external_send_attempted = false

No cross-thread message was sent and no target model turn was started.

## Priority 3 — Cloud Browser -> ChatGPT Web -> existing Work

Static fail-closed implementation is prepared:

- `automation/command_bus/chatgpt_web_preflight.py`
- `automation/command_bus/tests/test_chatgpt_web_preflight.py`
- `automation/command_bus/schema/chatgpt_web_preflight_evidence.schema.json`
- `docs/CHATGPT_WEB_EXISTING_WORK_PREFLIGHT.md`
- runtime contract section 7G

The live preflight is strictly navigation/read-only:
- may open `https://chatgpt.com`
- may inspect ChatGPT / Work UI and existing Work list
- may look only for exact preferred title `Phase 0 Jules Operator`
- may open that Work read-only if found
- must not type or send any message
- must not create a Work
- must not start a target model turn
- must not start human auth
- must not start Jules
- must not persist chat/thread/session/browser-control identifiers

Static validation must PASS before this live preflight is issued.

## Human auth / Jules gate

Blocked until a reliable human-visible route is proved.

- human_auth_started = false
- jules_started = false
- credential_material_persisted = false
- retry_count = 0
- fallback_used = false

## Existing human-auth command

The previous Jules human-auth bootstrap is terminal BLOCKED with durable
evidence that its intended user-visible entry was not actually visible to the
human. It must not be replayed.
