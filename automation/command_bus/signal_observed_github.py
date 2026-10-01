import re

def map_exact_head_github_run_to_observed_check(pr_head_sha, run_head_sha, status, conclusion):
    if not isinstance(pr_head_sha, str) or not isinstance(run_head_sha, str):
        return "UNKNOWN"
    if not re.match(r'^[a-f0-9]{40}$', pr_head_sha):
        return "UNKNOWN"
    if not re.match(r'^[a-f0-9]{40}$', run_head_sha):
        return "UNKNOWN"
    if pr_head_sha != run_head_sha:
        return "UNKNOWN"
    return map_github_workflow_run_to_observed_check(status, conclusion)

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
