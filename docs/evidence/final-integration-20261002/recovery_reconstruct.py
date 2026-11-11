#!/usr/bin/env python3
"""Read-only recovery drill: rebuild the Loop A state from GitHub durable records only.

Uses `git show` against remote-tracking refs (fetch first). No chat id, thread id,
browser session, Claude session or Jules UI is consulted. Writes nothing.
Usage: python3 recovery_reconstruct.py [data_ref] [carrier_ref]
"""
import json, re, subprocess, sys

DATA = sys.argv[1] if len(sys.argv) > 1 else "origin/claude/claude-jules-autoloop-data"
CARRIER = sys.argv[2] if len(sys.argv) > 2 else "origin/feature/chat-work-command-bus"
EV = "automation/command_bus/evidence/"


def git(*a):
    r = subprocess.run(["git", *a], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"UNKNOWN: git {' '.join(a)} failed: {r.stderr.strip()}")
    return r.stdout


def tree(ref, prefix):
    return [p for p in git("ls-tree", "-r", "--name-only", ref, prefix).splitlines()]


def js(ref, path):
    return json.loads(git("show", f"{ref}:{path}"))


out = {"sources": {"data_ref": DATA, "data_sha": git("rev-parse", DATA).strip(),
                   "carrier_ref": CARRIER, "carrier_sha": git("rev-parse", CARRIER).strip()}}

# owner chain: latest event wins, chain must be contiguous
events = sorted(tree(DATA, "automation/command_bus/loop_owner_events/"))
chain = [js(DATA, p) for p in events]
gens = [e["generation"] for e in chain]
out["owner_chain_contiguous"] = gens == list(range(1, len(gens) + 1))
last = chain[-1]
out["owner"] = {k: last[k] for k in ("loop_id", "owner_role", "holder_id", "generation", "fencing_token", "event_type", "expires_at", "expected_pr", "expected_target_head")}
out["owner"]["fencing_monotonic"] = [e["fencing_token"] for e in chain] == sorted(e["fencing_token"] for e in chain)

# budget: contiguous slots, never released
slots = sorted(tree(DATA, EV + "claude-auto-live-budget/"))
recs = [js(DATA, p) for p in slots]
out["budget"] = {"cap": recs[0]["cap"] if recs else None, "used": len(recs), "remaining": (recs[0]["cap"] - len(recs)) if recs else None,
                 "contiguous": [r["slot"] for r in recs] == list(range(1, len(recs) + 1)),
                 "commands": [r["command_id"] for r in recs]}

# last command on the carrier
cmds = sorted(p for p in tree(CARRIER, "automation/command_bus/jules_api_requests/") if re.search(r"relay-dev-loop-\d+", p))
cmds.sort(key=lambda p: int(re.search(r"relay-dev-loop-(\d+)", p).group(1)))
last_cmd = cmds[-1]
out["last_numbered_command_on_carrier"] = last_cmd.rsplit("/", 1)[1]

# per-command durable chain for Loop A commands
chains = {}
for r in recs:
    cid = r["command_id"]
    g = lambda d: (js(DATA, f"{EV}{d}/{cid}.json") if f"{EV}{d}/{cid}.json" in set(tree(DATA, EV + d + "/")) else None)
    rec = {"dispatch_receipt": (g("claude-auto-dispatch-receipts") or {}).get("state"),
           "session_id": (g("claude-auto-dispatch-observations") or {}).get("session_id"),
           "origin_binding": bool(g("claude-auto-origin-bindings")),
           "inspection_heads": [p.rsplit("/", 1)[1][:-5] for p in tree(DATA, f"{EV}claude-auto-inspections/{cid}/")],
           "review_heads": [p.rsplit("/", 1)[1][:-5] for p in tree(DATA, f"{EV}claude-auto-reviews/{cid}/")]}
    ad = g("claude-auto-adoption-receipts")
    rec["adoption"] = ({"state": ad["state"], "head_before": ad["head_before"], "head_after": ad["head_after"], "merge": ad["merge"], "force_push": ad["force_push"]} if ad else None)
    chains[cid] = rec
out["commands"] = chains

# adopted head = last ADOPTED head_after; must equal target branch tip in the owner's expected head
adopted = [c["adoption"]["head_after"] for c in chains.values() if c["adoption"] and c["adoption"]["state"] == "ADOPTED"]
out["adopted_head"] = adopted[-1] if adopted else None
out["owner_expected_head_matches_adopted_head"] = (last["expected_target_head"] == out["adopted_head"])

# next safe task from the live roadmap (first task without a dispatch receipt)
roadmap = js(DATA, "automation/command_bus/config/claude_jules_autoloop_roadmap.live.json")
done = {cid.split("-", 4)[-1] for cid in chains}
pending = [t["task_spec"]["task_id"] for t in roadmap["tasks"] if t["task_spec"]["task_id"] not in done and not any(t["task_spec"]["task_id"] in c for c in chains)]
out["next_safe_task"] = pending[0] if pending else None
out["next_action_rule"] = ("Owner is %s (generation %d); Claude AUTO must NOT act until the lease expired + stall >= 2h + no running Jules, or a human hands over."
                           % (last["owner_role"], last["generation"])) if last["owner_role"] != "AUTO" else "Owner is AUTO"
print(json.dumps(out, indent=2, ensure_ascii=False))
