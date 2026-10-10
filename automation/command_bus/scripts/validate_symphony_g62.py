"""Validate published STATIC bytes and immutable upstream observation boundary."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from ..symphony_result_manifest import safe_path

ROOT = Path(__file__).resolve().parents[3]


def validate(root=ROOT):
    count = 0
    for name in ("docs/evidence/symphony-g61-static/manifest.json",
                 "docs/evidence/symphony-g61-ci-recovery/manifest.json",
                 "docs/evidence/symphony-g62-static/manifest.json"):
        manifest = json.loads((root / name).read_text(encoding="utf-8"))
        seen = set()
        for entry in manifest["files"]:
            path = entry["path"]
            if not safe_path(path) or path in seen:
                raise ValueError("evidence path invalid/duplicate")
            seen.add(path)
            data = (root / path).read_bytes()
            if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("evidence byte/hash mismatch: " + path)
            count += 1
    old = root / "docs/evidence/symphony-g61-ci-recovery/original-full-tests-windows.txt.gz"
    if hashlib.sha256(gzip.decompress(old.read_bytes())).hexdigest() != "c62b01fcf572560d8087f94080db3145712d370d4a7ec66ac8c9761506df6a70":
        raise ValueError("original failed Windows log changed")
    if hashlib.sha256((root / "automation/command_bus/symphony_g5_observer.patch").read_bytes()).hexdigest() != "404b4001d279351c8b800816142862ee47dfd209615b0f9211fbe6ccc5170f3b":
        raise ValueError("Official Symphony observation patch changed")
    cp = json.loads((root / "docs/evidence/symphony-g62-static/checkpoint.json").read_text())
    if cp["counts"] != {"new_live_workers": 0, "model_provider_live": 0, "real_result_adoption": 0,
                         "real_graphql_mutations": 0, "paid_fallback": 0}:
        raise ValueError("STATIC boundary mismatch")
    print(json.dumps({"result": "PASS", "verified_files": count, "original_failure_preserved": True,
                      "official_observation_patch_unchanged": True, "live_count": 0}))


if __name__ == "__main__":
    validate()
