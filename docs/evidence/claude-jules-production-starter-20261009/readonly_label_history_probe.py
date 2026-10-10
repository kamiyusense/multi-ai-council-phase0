"""Read-only probe: can this environment read the full label history of private issues?

Only GET requests through `gh api`. No writes, no retries, no token output.
Usage: python3 -I readonly_label_history_probe.py [--repo owner/name] [--issues 335,338] [--per-page 100]
                                                  [--out result.json]

Output (v2): the COMPLETE result is written as UTF-8 JSON to --out (default: a new file in the system temp
directory). stdout is ONE short ASCII line with the summary, the output path and its SHA-256, so `head`, a
truncating viewer or a Windows cp932 console can neither cut nor break it.  Read the file for details.

Pagination follows the Link header page number but always re-requests repos/{owner}/{repo}/... : the cloud
proxy refuses the numeric repositories/{id}/... URLs that `gh api --paginate` follows (HTTP 403).
A history is complete only when every page answered HTTP 200, each next page is exactly the following page,
the announced last page was reached, and no event id appeared twice.  Otherwise it is UNKNOWN (null), never
"no label history".  `gh auth status` is reported for information only; the real authenticated GET decides.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

PROFILE = "CLAUDE_JULES_READONLY_LABEL_HISTORY_PROBE_V2"
MAX_PAGES = 50
LINK = re.compile(r'<([^>]*)>\s*;\s*rel="([^"]+)"')
PAGE = re.compile(r"[?&]page=(\d+)(?:&|$)")
STATUS = re.compile(r"HTTP/\S+\s+(\d{3})")
STDERR_STATUS = re.compile(r"\(HTTP (\d{3})\)")


def run(cmd, timeout=60):
    """One subprocess, decoded as UTF-8 whatever the console code page is (Windows cp932 broke v1)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as e:  # noqa: BLE001 - classify, never retry
        return None, "", type(e).__name__


def redact(text):
    return re.sub(r"(gh[opsu]_|github_pat_)[A-Za-z0-9_]+", r"\1***", text or "")[:300]


def link_pages(head):
    pages = {}
    for line in head.split("\n"):
        name, _, value = line.partition(":")
        if name.strip().lower() != "link":
            continue
        for url, rels in LINK.findall(value):
            m = PAGE.search(url)
            for rel in rels.split():
                pages[rel] = int(m.group(1)) if m else -1
    return pages


def get_page(path):
    """One GET with response headers. Returns (status, headers_text, body or None, error)."""
    if not path.startswith("repos/"):
        return None, "", None, "refused: only repos/{owner}/{repo}/... paths"
    rc, out, err = run(["gh", "api", "--method", "GET", "--include", path])
    if rc is None:
        return None, "", None, redact(err)
    head, _, body = out.replace("\r\n", "\n").partition("\n\n")
    found = STATUS.findall(head)
    status = int(found[-1]) if found else None
    if status is None:
        m = STDERR_STATUS.findall(err)
        status = int(m[-1]) if m else None
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    return status, head, data, redact(err) if rc else ""


def read_all_events(repo, issue, per_page=100):
    pages, events, seen, page, last = [], [], set(), 1, None

    def fail(reason):
        return {"complete": False, "pages": pages, "events": events, "error": reason}
    while page <= MAX_PAGES:
        status, head, data, err = get_page(f"repos/{repo}/issues/{issue}/events?per_page={per_page}&page={page}")
        links = link_pages(head)
        pages.append({"page": page, "status": status, "items": len(data) if isinstance(data, list) else None,
                      "next": links.get("next"), "last": links.get("last"), "error": err or None})
        if status != 200 or not isinstance(data, list):
            return fail(f"page {page}: status {status}")
        for ev in data:
            key = ev.get("id") if isinstance(ev, dict) else None
            if key is not None and key in seen:
                return fail(f"page {page}: event {key} seen twice (list moved while paging)")
            seen.add(key)
        events.extend(data)
        if "last" in links:
            if last is not None and links["last"] != last:
                return fail(f"page {page}: last page moved {last} -> {links['last']}")
            last = links["last"]
        if "next" not in links:
            if last is not None and page > 1 and page != last:
                return fail(f"stopped at page {page}, last announced {last}")
            return {"complete": True, "pages": pages, "events": events, "error": None}
        if links["next"] != page + 1:
            return fail(f"page {page}: next is {links['next']}, not {page + 1} (skip or loop)")
        page += 1
    return fail("page cap")


def probe(repo, issues, per_page):
    out = {"profile": PROFILE, "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "gh_path": shutil.which("gh"), "python3": True, "writes": 0, "retries": 0}
    rc, o, e = run(["gh", "--version"])
    out["gh_version"] = o.splitlines()[0] if rc == 0 and o else None
    rc, o, e = run(["gh", "auth", "status"])
    lines = (o + e).strip().splitlines()
    out["gh_auth_status_exit"] = rc                 # information only: never used as the access gate
    out["gh_auth_status_summary"] = redact(lines[1] if len(lines) > 1 else (lines[0] if lines else ""))
    status, _, data, err = get_page(f"repos/{repo}")
    out["repo_get"] = {"status": status, "private": data.get("private") if isinstance(data, dict) else None,
                       "error": err or None}
    out["issues"] = {}
    for n in issues:
        r = read_all_events(repo, n, per_page)
        labeled = [[ev.get("event"), (ev.get("label") or {}).get("name"), (ev.get("actor") or {}).get("login"),
                    ev.get("created_at")] for ev in r["events"] if ev.get("event") in ("labeled", "unlabeled")]
        st, _, cur, _ = get_page(f"repos/{repo}/issues/{n}")
        cur_ok = st == 200 and isinstance(cur, dict)
        out["issues"][str(n)] = {
            "events_complete": r["complete"], "error": r["error"], "pages": r["pages"],
            "event_count": len(r["events"]) if r["complete"] else None,
            "event_ids": [ev.get("id") for ev in r["events"]],
            "event_types": sorted({str(ev.get("event")) for ev in r["events"]}),
            "label_events": labeled,
            "ever_labeled_jules": any(x[0] == "labeled" and x[1] == "jules" for x in labeled) if r["complete"] else None,
            "current_labels": sorted(l.get("name") for l in cur.get("labels", [])) if cur_ok else None,
            "state": cur.get("state") if cur_ok else None,
            "updated_at": cur.get("updated_at") if cur_ok else None,
            "body_sha256": hashlib.sha256((cur.get("body") or "").encode("utf-8")).hexdigest() if cur_ok else None,
        }
    out["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


def summary(out, path, digest):
    return {"profile": out["profile"], "out": path, "out_sha256": digest, "writes": 0,
            "gh_auth_status_exit": out["gh_auth_status_exit"], "repo_status": out["repo_get"]["status"],
            "private": out["repo_get"]["private"],
            "issues": {n: {"complete": i["events_complete"], "events": i["event_count"],
                           "pages": [p["status"] for p in i["pages"]], "ever_labeled_jules": i["ever_labeled_jules"],
                           "labels": i["current_labels"]} for n, i in out["issues"].items()}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="kamiyusense/multi-ai-council-phase0")
    ap.add_argument("--issues", default="335,338")
    ap.add_argument("--per-page", type=int, default=100)
    ap.add_argument("--out", help="full UTF-8 JSON result (default: a new file in the system temp directory)")
    a = ap.parse_args(argv)
    out = probe(a.repo, [int(x) for x in a.issues.split(",") if x], a.per_page)
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if a.out:
        path = a.out
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    else:
        fd, path = tempfile.mkstemp(prefix="label-history-probe-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    print(json.dumps(summary(out, path, digest), ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
