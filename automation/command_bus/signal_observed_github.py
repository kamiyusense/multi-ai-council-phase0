import re

def _is_valid_sha(sha):
    if not isinstance(sha, str):
        return False
    return bool(re.fullmatch(r'[a-f0-9]{40}', sha))

def map_result_pr_head_to_observed_state(pr_head_sha):
    if pr_head_sha is None:
        return "NO_RESULT_PR"
    if _is_valid_sha(pr_head_sha):
        return "PR_READY"
    return "UNKNOWN"

def map_exact_head_github_run_to_observed_check(pr_head_sha, run_head_sha, status, conclusion):
    if not _is_valid_sha(pr_head_sha) or not _is_valid_sha(run_head_sha):
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
