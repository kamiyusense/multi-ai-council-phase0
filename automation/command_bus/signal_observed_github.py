def map_github_workflow_run_to_observed_check(status, conclusion):
    """
    Pure function mapping GitHub workflow run status and conclusion
    to the Observed Signal state.
    """
    if not isinstance(status, str):
        return "UNKNOWN"

    if status == "queued" and conclusion is None:
        return "VERIFYING"
    elif status == "in_progress" and conclusion is None:
        return "VERIFYING"
    elif status == "completed":
        if conclusion == "success":
            return "PASS"
        elif conclusion == "failure":
            return "FAIL"
        else:
            return "UNKNOWN"
    else:
        return "UNKNOWN"
