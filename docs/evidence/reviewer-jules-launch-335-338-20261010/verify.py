"""Offline replay of this bounded GitHub audit; no network/provider/write port."""
import json
from pathlib import Path
from automation.command_bus.claude_closed_loop_review import parse_receipt

def verify(data):
    a, b = data["issues"]["335"], data["issues"]["338"]
    for issue in (a, b):
        for kind in ("events", "timeline", "comments"):
            collection = issue[kind]
            pages = collection["pages"]
            assert collection["complete_until_empty_page"] is True
            assert pages[-1]["items"] == 0
            assert [p["page"] for p in pages] == list(range(1, len(pages) + 1))
            assert sum(p["items"] for p in pages) == len(collection["items"])
    labels = [e for e in a["events"]["items"] if e["event"] == "labeled" and e["label"] == "jules"]
    assert len(labels) == 1 and labels[0]["id"] == 32812577102
    assert labels[0]["created_at"] == "2026-10-08T17:53:06Z"
    comments = {c["id"]: c for c in a["comments"]["items"]}
    start, ready = comments[6065845035], comments[6065977783]
    for c in (start, ready):
        assert c["user"] == {"login": "google-labs-jules[bot]", "id": 161369871, "type": "Bot"}
        assert c["performed_via_github_app"] == {"id": 842251, "slug": "google-labs-jules"}
    task = "5755515948434524038"
    url = "https://jules.google.com/task/" + task
    assert url in start["body"]
    pr, commit = data["pr_337"], data["commit"]
    assert pr["number"] == 337 and "Fixes #335" in pr["body"] and url in pr["body"]
    assert pr["head"]["ref"].startswith("jules-" + task + "-")
    assert pr["html_url"] in ready["body"]
    assert labels[0]["created_at"] < start["created_at"] < commit["commit"]["author"]["date"] <= pr["created_at"] < ready["created_at"]
    assert commit["sha"] == pr["head"]["sha"]
    assert commit["author"]["login"] == "google-labs-jules[bot]"
    receipt = parse_receipt(comments[6066036644]["body"])
    assert receipt == data["reviewer_receipt"]
    assert receipt["pr_head_sha"] == commit["sha"] and receipt["pr_head_tree"] == commit["commit"]["tree"]["sha"]
    assert receipt["expected_target_head"] == commit["parents"][0] and receipt["pr"] == 337
    assert receipt["task_id"] == "grd-001" and receipt["next_issue"] == 338
    assert receipt["verdict"] == "PASS" and receipt["phase"] == "FINAL"
    assert data["pr_changed_files"][0]["filename"] == "automation/command_bus/tests/test_claude_jules_live_adapter.py"
    assert len(data["pr_changed_files"]) == pr["changed_files"] == 1
    assert any(r["head_sha"] == commit["sha"] and r["conclusion"] == "success" and r["id"] == 37821036202 for r in data["actions_exact_head"])
    assert b["state"] == "open" and b["labels"] == [] and b["comments"]["items"] == []
    assert not any(e["event"] in ("labeled", "unlabeled") for e in b["events"]["items"] + b["timeline"]["items"])
    assert data["repository_pr_inventory"]["complete_link_pagination"] is True
    assert data["repository_pr_inventory"]["no_jules_task_bound_to_338_found"] is True
    return {"issue335_launch": "PASS", "issue338_not_started": "PASS_WITHIN_GITHUB_LABEL_ROUTE", "provider_internal_state": "UNKNOWN", "new_jules_start_count": 0}

if __name__ == "__main__":
    print(json.dumps(verify(json.loads(Path(__file__).with_name("github-readback.json").read_text(encoding="utf-8"))), indent=2))
