"""
Decision helper for the Jules AWAITING_USER_FEEDBACK / readback path.
This module distinguishes a small reversible repository-answer candidate from a
human-only question, missing evidence, duplicate answer, or mismatched Session.

Important: Merge, destructive/history rewrite, settings/permissions, billing/keys/secrets,
unapproved live provider execution, and material architecture/scope changes are HUMAN_ONLY
and may never receive eligibility for auto-send.
"""

from automation.command_bus.signal_observed_jules import map_jules_session_state_to_observed_signal

def decide_same_session_feedback(
    *,
    observed_session_id: str,
    expected_session_id: str,
    jules_state: str,
    agent_message: str,
    controller_classification: str,
    already_answered: bool = False,
) -> str:
    """
    Pure decision helper to determine if a same-session feedback is eligible for auto-reply.

    Merge, destructive/history rewrite, settings/permissions, billing/keys/secrets,
    unapproved live provider execution, and material architecture/scope changes are
    HUMAN_ONLY and may never receive eligibility.
    """
    # 1. Validate session IDs: Must be nonempty ASCII digits and exactly equal.
    if (
        not isinstance(observed_session_id, str)
        or not isinstance(expected_session_id, str)
        or not observed_session_id.isascii()
        or not expected_session_id.isascii()
        or not observed_session_id.isdigit()
        or not expected_session_id.isdigit()
        or observed_session_id != expected_session_id
    ):
        return "UNKNOWN"

    # 2. Validate jules_state and derive NEEDS_INPUT
    if not isinstance(jules_state, str):
        return "UNKNOWN"

    observed_signal_state = map_jules_session_state_to_observed_signal(jules_state)

    if observed_signal_state == "UNKNOWN":
        return "UNKNOWN"

    if observed_signal_state != "NEEDS_INPUT":
        # Known non-NEEDS_INPUT state => NO_ACTION
        return "NO_ACTION"

    # 3. Validate already_answered (strict boolean check)
    if type(already_answered) is not bool:
        return "UNKNOWN"

    if already_answered is True:
        return "NO_ACTION"

    # 4. Validate agent_message: Nonempty string, trimmed length > 0 and <= 4000
    if not isinstance(agent_message, str):
        return "UNKNOWN"

    trimmed_msg = agent_message.strip()
    if len(trimmed_msg) == 0 or len(trimmed_msg) > 4000:
        return "UNKNOWN"

    # 5. Validate controller_classification
    if controller_classification == "SMALL_REVERSIBLE_REPO":
        return "CONTROLLER_REVIEW_ELIGIBLE"
    elif controller_classification == "HUMAN_ONLY":
        return "HUMAN_NEEDED"
    else:
        # includes 'UNKNOWN' or invalid classifications
        return "UNKNOWN"
