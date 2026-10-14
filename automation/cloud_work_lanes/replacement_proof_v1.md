# Cloud Work replacement proof target v1

This branch/PR exists only as a stable, read-only target for validating Cloud Work lane replacement.

Rules:
- Never merge this PR.
- Never use it for production code.
- Replacement validation may fresh-read this PR and verify its head SHA/state.
- Replacement validation must not modify this branch.
- No lane label is required.
- If the PR is unavailable or changed unexpectedly, replacement validation must use another explicitly verified read-only target and record that change in evidence.

The purpose is to let a newly created Cloud Work prove that:
1. the correct lane webhook woke it;
2. worker generation fencing passed;
3. it could fresh-read GitHub;
4. it returned exactly one terminal receipt;
5. no target write occurred.
