# Claude夜間自動ループ設計（Phase 0）

## 判定

静的実装・mock・dry-run・unit/regression/static testまでを対象とする。
Claude OAuth/token、Secrets、permissions、billing、live Claude/Jules起動、
PR merge、default branch直接write、force push、destructive deleteは対象外で、
この設計から実行できない。

## 2つの独立backend

```text
Claude structured verdict
  -> common machine gate
     -> JULES_BACKEND  -> existing executor PREPARE_ONLY request
                          -> existing Jules API request/closed-loop route
     -> CLAUDE_BACKEND  -> existing executor PREPARE_ONLY request
                          + TREE_IDENTITY_V1 + path_policy
```

`JULES_BACKEND` と `CLAUDE_BACKEND` は明示指定する。`AUTO`、残量判定による
自動切替、fallback、重複dispatchは存在しない。既存PR #6のdispatch実装を
再実装せず、今回のコードは既存executor durable requestを1件準備するだけである。
実送信は行わず、Aは既存のJules API request/closed-loop routeへ渡すPREPARE_ONLY
記録を作る。Bは既存executor request schemaが要求する具体的tree identityと
path policyを必須にする。

## 2026-09-28 current status

- PR #25 was merged to `main` after the bounded REAL Claude Gate proof passed.
- B / `CLAUDE_BACKEND`: the one-request REAL proof is live-green. The proof
  remains bounded evidence, not standing authorization for another Claude run.
- A / `JULES_BACKEND`: the historical Jules API transport has live smoke
  evidence, but the complete Claude-verdict -> Jules closed-loop correlation has
  not yet been run live. Treat integrated A as **LIVE UNKNOWN**.
- `prepare_jules_closed_loop_command()` is the static bridge from the existing
  JULES_BACKEND executor preparation to the existing `JULES_API_CLOSED_LOOP`
  command contract. It returns an in-memory artifact only; it does not persist a
  command, move durable state to RUNNING, dispatch a workflow, start Jules, or
  start Claude.
- The bridge narrows authority rather than widening it: exact file paths only,
  `ADD`/`MODIFY` only, explicit non-default starting branch, pinned
  head/tree, retry=0, fallback=disabled. Glob paths, destructive operations,
  duplicate paths, default-branch targets, or tampered live flags fail closed.
- Persisting/activating the returned live-capable Jules command remains a
  separate LIVE boundary requiring explicit authorization and fresh preflight.

## JULES_BACKEND transport bridge

There are two distinct Jules contracts and they must not be conflated:

1. `prepare_jules_closed_loop_command()`
   - internal `JULES_API_CLOSED_LOOP` command artifact;
   - used to validate correlation/head/tree/path-policy compatibility with the
     closed-loop implementation;
   - no I/O and no workflow dispatch.

2. `prepare_jules_semiauto_request()`
   - current live GitHub workflow request profile for Claude-origin work:
     `JULES_CHAT_SEMIAUTO_V2` (V1 remains accepted for existing Chat-driven tasks);
   - converts the already-safe JULES_BACKEND PREPARE_ONLY request into the exact
     request read by `.github/workflows/jules-chat-semiauto.yml`;
   - reuses the internal bridge first, then validates again with
     `jules_api_request.validate_request()`;
   - preserves origin loop/round/correlation/generation plus target repo, branch,
     exact head/tree, allowlisted paths, prompt, expiry, retry=0,
     fallback=disabled, merge=false and force-push=false;
   - generation is a required Claude verdict field and is copied through the
     PREPARE_ONLY executor request and internal closed-loop command; the live
     bridge does not accept a separate generation override;
   - carries per-path ADD/MODIFY operation bounds into the task prompt and
     explicitly forbids DELETE/RENAME;
   - still performs no file persistence, GitHub write, workflow dispatch, Jules
     API call, Jules session start, or Claude start.

The only live transition after this static bridge is to append exactly one new
`automation/command_bus/jules_api_requests/<command_id>.json` on the approved
carrier branch. That write is the trigger for the existing semi-auto workflow
and therefore remains a separate explicit LIVE authorization boundary.

The workflow must still fresh-read the target branch head/tree immediately
before the one Jules API call. Post-run Jules PR ancestry, changed paths,
operations and tests must be independently read back; Actions green alone is
not PASS.

## 共通machine gate

- `round <= max_rounds <= 6`
- `retry=0`, `fallback=disabled`
- expected target head と fresh observed head が一致
- expected target tree と fresh observed tree が一致
- merge / default-branch write / force-push / destructive deleteを拒否
- live model / external sendを拒否
- structured verdictの `execution_mode=PREPARE_ONLY`
- `model_executed=false`, `external_send_attempted=false`
- 既存executor receiptとloop/round/correlation/head/treeが一致すればNO-OP

carrier PR headは判定対象にせず、target PRのhead/treeだけを比較する。
`COMPLETE` / `BLOCKED` / `UNKNOWN` verdictはterminalとして記録可能だが、
次のexecutor requestを作らない。missing/empty/不一致のevidenceはfail-closed。

## 既存資料から採用しないもの

旧 `/next`、GPT予約タスク、BrowserHookによるJules launch、重複Jules
dispatch実装は再利用しない。Claudeのstructured reviewer/plannerという役割と、
GitHubをdurable stateにする考え方だけを採用する。

## 検証範囲

`automation/command_bus/tests/test_claude_loop.py` がA/B双方、明示mode、fresh
head/tree、loop cap、安全拒否、terminal replay prevention、live flag拒否を検証する。
本変更だけではlive providerの可用性や契約枠残量を証明しない。
