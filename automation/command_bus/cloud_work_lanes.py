"""Only lane metadata; Work generation and Jules Loop numbers stay separate."""
LANES = ("blue", "yellow", "green", "red")


def lane_identity(lane: str) -> dict[str, str]:
    if lane not in LANES:
        raise ValueError("unknown Cloud Work lane")
    upper = lane.upper()
    return {"lane": lane, "label": "cloud-" + lane, "jules_lane": "J-" + upper,
            "command_prefix": f"[CW_{upper}_V1]",
            "receipt_prefix": f"[CW_{upper}_RECEIPT_V1]"}


def result_review_task(lane: str) -> str:
    identity = lane_identity(lane)
    return (f"fresh-read GitHub; verify exact {identity['jules_lane']} claim/command/session/result lineage and current result head; "
            "independently inspect paths/semantics/negative tests/test evidence; return PASS/FAIL/BLOCKED/UNKNOWN plus one bounded "
            "next-task proposal; perform no target write and do not dispatch Jules.")


def result_review_verification(lane: str) -> tuple[str, ...]:
    identity = lane_identity(lane)
    return ("fresh result PR/branch/head readback", f"durable {identity['jules_lane']} lineage verification",
            "independent diff/test evidence inspection",
            "confirmation no target write/Jules dispatch/live provider execution occurred")
