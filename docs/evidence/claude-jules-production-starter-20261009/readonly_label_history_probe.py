"""Read-only probe: can this environment read the full label history of private issues?

Only GET requests through `gh api`. No writes, no token output. Prints one JSON object.
Usage: python3 -I readonly_label_history_probe.py [--repo owner/name] [--issues 335,338] [--per-page 100]
Pagination follows the Link header page number but always re-requests repos/{owner}/{repo}/... :
the cloud proxy refuses the numeric repositories/{id}/... URLs that `gh api --paginate` follows (HTTP 403).
"""
import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone

LINK_NEXT = re.compile(r'<[^>]*[?&]page=(\d+)[^>]*>;\s*rel="next"')


def run(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:  # noqa: BLE001 - classify, never retry
        return None, "", type(e).__name__


def redact(text):
    return re.sub(r"(gh[opsu]_|github_pat_)[A-Za-z0-9_]+", r"\1***", text)[:300]


def get_page(path):
    """One GET with response headers. Returns (status, headers_text, body or None)."""
    rc, out, err = run(["gh", "api", "-i", "-X", "GET", path])
    if rc is None:
        return None, "", None, redact(err)
    head, _, body = out.replace("\r\n", "\n").partition("\n\n")
    m = re.match(r"HTTP/\S+\s+(\d+)", head)
    status = int(m.group(1)) if m else None
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    return status, head, data, redact(err) if rc else ""


def read_all_events(repo, issue, per_page=100):
    pages, events, page = [], [], 1
    while True:
        status, head, data, err = get_page(f"repos/{repo}/issues/{issue}/events?per_page={per_page}&page={page}")
        nxt = LINK_NEXT.search(head)
        pages.append({"page": page, "status": status, "items": len(data) if isinstance(data, list) else None,
                      "has_next": bool(nxt), "error": err or None})
        if status != 200 or not isinstance(data, list):
            return {"complete": False, "pages": pages, "events": events}
        events.extend(data)
        if not nxt:
            return {"complete": True, "pages": pages, "events": events}
        page = int(nxt.group(1))
        if page > 50:
            return {"complete": False, "pages": pages, "events": events, "error": "page cap"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="kamiyusense/multi-ai-council-phase0")
    ap.add_argument("--issues", default="335,338")
    ap.add_argument("--per-page", type=int, default=100)
    a = ap.parse_args()
    out = {"profile": "CLAUDE_JULES_READONLY_LABEL_HISTORY_PROBE_V1",
           "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "gh_path": shutil.which("gh"), "python3": True, "writes": 0}
    rc, o, e = run(["gh", "--version"])
    out["gh_version"] = o.splitlines()[0] if rc == 0 and o else None
    rc, o, e = run(["gh", "auth", "status"])
    out["gh_auth_status_exit"] = rc
    out["gh_auth_status_summary"] = redact((o + e).strip().splitlines()[1] if (o + e).strip().count("\n") else (o + e))
    status, _, data, err = get_page(f"repos/{a.repo}")
    out["repo_get"] = {"status": status, "private": (data or {}).get("private") if isinstance(data, dict) else None,
                       "error": err or None}
    out["issues"] = {}
    for n in [int(x) for x in a.issues.split(",") if x]:
        r = read_all_events(a.repo, n, a.per_page)
        labeled = [[ev.get("event"), (ev.get("label") or {}).get("name"), (ev.get("actor") or {}).get("login"),
                    ev.get("created_at")] for ev in r["events"] if ev.get("event") in ("labeled", "unlabeled")]
        st, _, cur, _ = get_page(f"repos/{a.repo}/issues/{n}")
        cur_labels = sorted(l.get("name") for l in (cur or {}).get("labels", [])) if isinstance(cur, dict) else None
        out["issues"][str(n)] = {
            "events_complete": r["complete"], "pages": r["pages"], "event_count": len(r["events"]),
            "event_types": sorted({ev.get("event") for ev in r["events"]}),
            "label_events": labeled,
            "ever_labeled_jules": any(x[0] == "labeled" and x[1] == "jules" for x in labeled) if r["complete"] else None,
            "current_labels": cur_labels,
            "updated_at": (cur or {}).get("updated_at") if isinstance(cur, dict) else None,
            "body_sha256": __import__("hashlib").sha256(((cur or {}).get("body") or "").encode()).hexdigest()
            if isinstance(cur, dict) else None,
        }
    out["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
