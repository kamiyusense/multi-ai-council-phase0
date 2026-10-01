"""
Small component to adapt raw Jules Session state to Observed Signal state.
"""

def map_jules_session_state_to_observed_signal(jules_state) -> str:
    """
    Pure function mapping a raw Jules Session state to the Observed Signal state.
    """
    if not isinstance(jules_state, str):
        return "UNKNOWN"

    mapping = {
        "QUEUED": "DISPATCHED",
        "PLANNING": "IN_PROGRESS",
        "IN_PROGRESS": "IN_PROGRESS",
        "AWAITING_USER_FEEDBACK": "NEEDS_INPUT",
        "FAILED": "FAIL",
        "COMPLETED": "SESSION_COMPLETE",
    }

    return mapping.get(jules_state, "UNKNOWN")
