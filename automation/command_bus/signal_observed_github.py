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


def _is_valid_sha(sha):
    if not isinstance(sha, str):
        return False
    if len(sha) != 40:
        return False
    for c in sha:
        if c not in "0123456789abcdef":
            return False
    return True


def bind_exact_pr_head_to_observed_check(pr_head, workflow_head_sha, observed_check):
    """
    Pure function that binds an already-mapped GitHub workflow check
    to the exact PR head SHA.
    """
    valid_checks = {"VERIFYING", "PASS", "FAIL", "UNKNOWN"}
    if observed_check not in valid_checks:
        return "UNKNOWN"

    if not _is_valid_sha(pr_head) or not _is_valid_sha(workflow_head_sha):
        return "UNKNOWN"

    if pr_head != workflow_head_sha:
        return "UNKNOWN"

    return observed_check
