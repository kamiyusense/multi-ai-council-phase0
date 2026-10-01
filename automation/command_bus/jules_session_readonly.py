"""Jules Session GET reader for verifying a single completed session.

Provides transport and field checking. Does not make state changes, create
sessions, or dispatch works. Fully decoupled from real provider calls during
tests. Retries and redirects are completely disabled.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import URLError


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirect blocked; no credential forwarding")


class JulesSessionGetReader:
    def __init__(self, existing_key: str):
        if not isinstance(existing_key, str) or not existing_key or "\n" in existing_key or "\r" in existing_key:
            raise ValueError("existing key unavailable")
        self._key = existing_key
        self._opener = build_opener(_NoRedirect())

    def read_completed_session(
        self,
        session_id: str,
        *,
        expected_branch: str,
        expected_create_time: str,
        expected_pr: int,
    ) -> dict[str, Any]:
        """Read and validate exactly one completed Jules Session via bounded GET."""
        if not isinstance(session_id, str) or not session_id.isdigit() or not session_id:
            raise ValueError("invalid session ID")
        if not isinstance(expected_branch, str) or not expected_branch.startswith("jules-work/"):
            raise ValueError("expected_branch must be an isolated jules-work branch")
        if type(expected_pr) is not int or expected_pr <= 0:
            raise ValueError("expected_pr must be a positive integer")

        # Verify expected_create_time is an aware time string (simple validation here,
        # exact string match will be performed on the response)
        try:
            parsed_time = datetime.fromisoformat(expected_create_time.replace("Z", "+00:00"))
            if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
                raise ValueError("naive")
        except Exception:
            raise ValueError("expected_create_time must be an aware datetime string") from None

        url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}"
        request = Request(
            url,
            method="GET",
            headers={"X-Goog-Api-Key": self._key},
        )

        try:
            with self._opener.open(request, timeout=30) as response:
                if response.status != 200:
                    raise ValueError("HTTP GET failed")
                raw = response.read(1024 * 1024 + 1)
        except URLError:
            raise ValueError("network or timeout error") from None
        except ValueError as e:
            # Re-raise already sanitized ValueErrors
            raise e from None
        except Exception:
            raise ValueError("unexpected request error") from None

        if len(raw) > 1024 * 1024:
            raise ValueError("response size limit exceeded")

        try:
            data = json.loads(raw, object_pairs_hook=_pairs)
        except ValueError:
            raise ValueError("malformed JSON or duplicate keys") from None
        except Exception:
            raise ValueError("JSON decode error") from None

        if not isinstance(data, dict):
            raise ValueError("response must be a JSON object")

        if data.get("name") != f"sessions/{session_id}":
            raise ValueError("session name mismatch")

        source_context = data.get("sourceContext")
        if not isinstance(source_context, dict):
            raise ValueError("missing or malformed sourceContext")

        if source_context.get("source") != "sources/github/kamiyusense/multi-ai-council-phase0":
            raise ValueError("sourceContext source mismatch")

        repo_context = source_context.get("githubRepoContext")
        if not isinstance(repo_context, dict):
            raise ValueError("missing or malformed githubRepoContext")

        if repo_context.get("startingBranch") != expected_branch:
            raise ValueError("startingBranch mismatch")

        if data.get("createTime") != expected_create_time:
            raise ValueError("createTime mismatch")

        if data.get("state") != "COMPLETED":
            raise ValueError("session state must be COMPLETED")

        outputs = data.get("outputs")
        if not isinstance(outputs, list) or len(outputs) != 1:
            raise ValueError("outputs must contain exactly ONE item")

        pr_output = outputs[0].get("pullRequest")
        if not isinstance(pr_output, dict):
            raise ValueError("output must be a pullRequest object")

        expected_pr_url = f"https://github.com/kamiyusense/multi-ai-council-phase0/pull/{expected_pr}"
        if pr_output.get("url") != expected_pr_url:
            raise ValueError("pullRequest URL mismatch")

        result = {
            "name": data["name"],
            "createTime": data["createTime"],
            "state": data["state"],
            "sourceContext": data["sourceContext"],
            "outputs": data["outputs"],
        }
        if "updateTime" in data:
            result["updateTime"] = data["updateTime"]

        return result
