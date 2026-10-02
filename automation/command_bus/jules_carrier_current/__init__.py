"""Pinned byte-for-byte snapshot of the current Jules carrier validators.

``jules_api_request.py`` and ``loop_id_claim.py`` are exact copies of the
files on the live carrier branch ``feature/chat-work-command-bus`` (Git blob
SHAs are pinned in ``PINNED_BLOB_SHA`` and checked by tests).  The Claude AUTO
loop validates every carrier request/claim it prepares with these exact
validators instead of the older, divergent ``command_bus.jules_api_request``
on this branch.  Do not edit the copies; re-vendor them from the carrier and
update the pins when the carrier contract changes.
"""

PINNED_CARRIER_BRANCH = "feature/chat-work-command-bus"
PINNED_BLOB_SHA = {
    "jules_api_request.py": "1aebad3469c2bfa629e97fd109541c236dc2244a",
    "loop_id_claim.py": "d7aba1adfa60b0341d7db6df1b92b8c39bd8c822",
}
