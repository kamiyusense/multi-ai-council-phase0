import re
from automation.command_bus.signal_observed_feedback import decide_same_session_feedback

def prepare_same_session_message_request(
    *,
    observed_session_id: str,
    expected_session_id: str,
    observed_activity_name: str,
    expected_activity_name: str,
    jules_state: str,
    agent_message: str,
    controller_classification: str,
    answer_text: str,
    already_answered: bool = False,
    prior_message_request_exists: bool = False,
) -> dict[str, str]:
    """
    Pure preparation seam to form an eligible message request.
    Does not initiate actual send, POST, side effects, or deduplication inference.
    """
    # 1. Validate expected_session_id is ASCII digits.
    # observed_session_id is validated by decide_same_session_feedback.
    if not isinstance(expected_session_id, str) or not expected_session_id.isascii() or not expected_session_id.isdigit():
        raise ValueError("expected_session_id must be ASCII digits")

    # 2. Validate activity names
    if not isinstance(observed_activity_name, str) or not isinstance(expected_activity_name, str):
        raise ValueError("Activity names must be strings")
    if not observed_activity_name or not expected_activity_name:
        raise ValueError("Activity names must be nonempty")
    if observed_activity_name != expected_activity_name:
        raise ValueError("Activity names must be exactly equal")

    # Validate activity name format
    # matches f"sessions/{expected_session_id}/activities/{activity_id}"
    prefix = f"sessions/{expected_session_id}/activities/"
    if not observed_activity_name.startswith(prefix):
        raise ValueError("Activity name does not match expected session ID")

    activity_id = observed_activity_name[len(prefix):]
    if not activity_id:
        raise ValueError("Activity ID must be nonempty")

    # nonempty ASCII letters/digits/dash/underscore/dot only
    if not re.fullmatch(r"[a-zA-Z0-9\-_.]+", activity_id):
        raise ValueError("Activity ID contains invalid characters")

    # 3. Call decide_same_session_feedback
    decision = decide_same_session_feedback(
        observed_session_id=observed_session_id,
        expected_session_id=expected_session_id,
        jules_state=jules_state,
        agent_message=agent_message,
        controller_classification=controller_classification,
        already_answered=already_answered
    )

    if decision != "CONTROLLER_REVIEW_ELIGIBLE":
        raise ValueError(f"Not eligible for review: {decision}")

    # 4. Validate prior_message_request_exists
    if type(prior_message_request_exists) is not bool:
        raise ValueError("prior_message_request_exists must be a strict boolean")
    if prior_message_request_exists is True:
        raise ValueError("prior_message_request_exists must be False")

    # 5. Validate answer_text
    if not isinstance(answer_text, str):
        raise ValueError("answer_text must be a string")

    trimmed_answer = answer_text.strip()
    if not trimmed_answer:
        raise ValueError("answer_text must be nonblank")

    if len(trimmed_answer) < 1 or len(trimmed_answer) > 4000:
        raise ValueError("answer_text must be between 1 and 4000 characters after trim")

    # Reject CR, LF, and control chars
    # Control chars in ASCII are 0-31 and 127
    if any(ord(c) < 32 or ord(c) == 127 for c in answer_text):
        raise ValueError("answer_text must not contain control characters or newlines")

    # 6. Return exactly {"session_id": expected_session_id, "expected_state": "AWAITING_USER_FEEDBACK", "prompt": trimmed_answer_text}
    return {
        "session_id": expected_session_id,
        "expected_state": "AWAITING_USER_FEEDBACK",
        "prompt": trimmed_answer
    }
