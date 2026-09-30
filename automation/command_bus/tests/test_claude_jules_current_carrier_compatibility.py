import json
import unittest
from datetime import datetime, timezone
import os
import sys
import hashlib
import tempfile
import copy

class TestClaudeJulesCurrentCarrierCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # We need to dynamically load the feature branch files since this is an audit of the current carrier.
        # But for tests, we should write them to a temp dir and add it to sys.path
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(cls.temp_dir.name, 'automation_compat', 'command_bus'), exist_ok=True)
        with open(os.path.join(cls.temp_dir.name, 'automation_compat', '__init__.py'), 'w') as init_file:
            pass
        with open(os.path.join(cls.temp_dir.name, 'automation_compat', 'command_bus', '__init__.py'), 'w') as init_file:
            pass

        # Immutable carrier evidence snapshot.  Do not depend on a remote-tracking
        # branch being present in shallow CI checkouts.  The embedded UTF-8
        # sources are verified against their exact Git blob SHA before loading.
        req_src = "from __future__ import annotations\n\nimport argparse\nimport json\nimport re\nfrom datetime import datetime, timedelta, timezone\nfrom pathlib import PurePosixPath\nfrom typing import Any\n\nPROFILE = \"JULES_CHAT_SEMIAUTO_V2\"\nTARGET_REPO = \"kamiyusense/multi-ai-council-phase0\"\nMAX_PROMPT_CHARS = 12000\nMAX_LIFETIME = timedelta(hours=2)\nCOMMAND_ID_RE = re.compile(r\"^[a-z0-9][a-z0-9._-]{0,63}$\")\nSHA_RE = re.compile(r\"^[0-9a-f]{40}$\")\nBRANCH_RE = re.compile(r\"^[A-Za-z0-9._/-]+$\")\nREQUIRED_KEYS = {\n    \"schema_version\",\n    \"profile\",\n    \"command_id\",\n    \"target_repo\",\n    \"target_branch\",\n    \"work_branch\",\n    \"expected_target_head\",\n    \"expected_target_tree\",\n    \"allowed_paths\",\n    \"prompt\",\n    \"created_at\",\n    \"expires_at\",\n    \"retry\",\n    \"fallback\",\n    \"merge_allowed\",\n    \"force_push_allowed\",\n}\n\n\ndef _parse_time(value: Any, field: str) -> datetime:\n    if not isinstance(value, str) or not value:\n        raise ValueError(f\"{field} must be a non-empty timestamp\")\n    try:\n        parsed = datetime.fromisoformat(value.replace(\"Z\", \"+00:00\"))\n    except ValueError as exc:\n        raise ValueError(f\"{field} must be ISO-8601\") from exc\n    if parsed.tzinfo is None or parsed.utcoffset() is None:\n        raise ValueError(f\"{field} must include timezone\")\n    return parsed.astimezone(timezone.utc)\n\n\ndef _validate_branch(branch: Any, field: str) -> str:\n    if not isinstance(branch, str) or not branch:\n        raise ValueError(f\"{field} required\")\n    if branch in {\"main\", \"master\"}:\n        raise ValueError(f\"default branch dispatch is forbidden for {field}\")\n    if not BRANCH_RE.fullmatch(branch) or branch.startswith(\"/\") or branch.endswith(\"/\"):\n        raise ValueError(f\"invalid {field}\")\n    if \"..\" in branch or \"\\\\\" in branch or branch.startswith(\"refs/\"):\n        raise ValueError(f\"unsafe {field}\")\n    return branch\n\n\ndef _validate_path(value: Any) -> str:\n    if not isinstance(value, str) or not value:\n        raise ValueError(\"allowed path must be non-empty\")\n    path = PurePosixPath(value)\n    if path.is_absolute() or \"..\" in path.parts or value.startswith(\"./\"):\n        raise ValueError(\"unsafe allowed path\")\n    if \"\\\\\" in value or value.endswith(\"/\"):\n        raise ValueError(\"unsafe allowed path\")\n    return value\n\n\ndef validate_request(\n    request: dict[str, Any], *, now: datetime | None = None\n) -> dict[str, Any]:\n    if not isinstance(request, dict):\n        raise ValueError(\"request must be an object\")\n    keys = set(request)\n    if keys != REQUIRED_KEYS:\n        missing = sorted(REQUIRED_KEYS - keys)\n        extra = sorted(keys - REQUIRED_KEYS)\n        raise ValueError(f\"request keys mismatch missing={missing} extra={extra}\")\n    if request[\"schema_version\"] != 2 or request[\"profile\"] != PROFILE:\n        raise ValueError(\"unsupported request profile\")\n\n    command_id = request[\"command_id\"]\n    if not isinstance(command_id, str) or not COMMAND_ID_RE.fullmatch(command_id):\n        raise ValueError(\"invalid command_id\")\n    if request[\"target_repo\"] != TARGET_REPO:\n        raise ValueError(\"unexpected target_repo\")\n\n    target_branch = _validate_branch(request[\"target_branch\"], \"target_branch\")\n    work_branch = _validate_branch(request[\"work_branch\"], \"work_branch\")\n    expected_work_branch = f\"jules-work/{command_id}\"\n    if work_branch != expected_work_branch:\n        raise ValueError(\n            f\"work_branch must be the isolated per-command branch {expected_work_branch}\"\n        )\n    if work_branch == target_branch:\n        raise ValueError(\"work_branch must differ from canonical target_branch\")\n\n    for field in (\"expected_target_head\", \"expected_target_tree\"):\n        value = request[field]\n        if not isinstance(value, str) or not SHA_RE.fullmatch(value):\n            raise ValueError(f\"invalid {field}\")\n\n    paths = request[\"allowed_paths\"]\n    if not isinstance(paths, list) or not paths or len(paths) > 20:\n        raise ValueError(\"allowed_paths must contain 1..20 paths\")\n    normalized_paths = [_validate_path(item) for item in paths]\n    if len(set(normalized_paths)) != len(normalized_paths):\n        raise ValueError(\"duplicate allowed path\")\n\n    prompt = request[\"prompt\"]\n    if (\n        not isinstance(prompt, str)\n        or not prompt.strip()\n        or len(prompt) > MAX_PROMPT_CHARS\n        or \"\\x00\" in prompt\n    ):\n        raise ValueError(\"invalid prompt\")\n\n    created = _parse_time(request[\"created_at\"], \"created_at\")\n    expires = _parse_time(request[\"expires_at\"], \"expires_at\")\n    if expires <= created or expires - created > MAX_LIFETIME:\n        raise ValueError(\"invalid request lifetime\")\n    check_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)\n    if check_now >= expires:\n        raise ValueError(\"request expired\")\n\n    if request[\"retry\"] != 0 or request[\"fallback\"] != \"disabled\":\n        raise ValueError(\"retry/fallback policy mismatch\")\n    if request[\"merge_allowed\"] is not False or request[\"force_push_allowed\"] is not False:\n        raise ValueError(\"dangerous publication permission\")\n    return request\n\n\ndef build_jules_prompt(request: dict[str, Any]) -> str:\n    validate_request(request)\n    allowed = \"\\n\".join(f\"- {path}\" for path in request[\"allowed_paths\"])\n    return f\"\"\"Multi-AI Council Phase 0 — bounded Chat->Jules API task.\n\nCommand ID: {request['command_id']}\nTarget repository: {request['target_repo']}\nCanonical target branch (READ-ONLY identity): {request['target_branch']}\nIsolated Jules starting work branch: {request['work_branch']}\nExpected snapshot HEAD: {request['expected_target_head']}\nExpected snapshot tree: {request['expected_target_tree']}\n\nBefore editing, verify the checked-out work-branch HEAD is exactly the expected snapshot HEAD above. If it is not exact, make no edits and report the mismatch.\n\nThe canonical target branch is NOT your working branch. Do not commit, push, reset, rebase, merge, or otherwise mutate the canonical target branch. All Jules edits must remain on the isolated work branch or a Jules-created descendant branch/PR. A later independent reviewer will decide whether validated content is copied or fast-forwarded to the canonical target.\n\nAllowed changed paths only:\n{allowed}\n\nHard bounds:\n- do not modify any path outside the allowlist\n- do not mutate the canonical target branch\n- do not merge\n- do not force push\n- do not delete branches\n- do not change repository settings, permissions, billing, credits, secrets, or API keys\n- do not retry or use fallback if an external action is ambiguous\n- create the normal Jules pull request when the bounded task is complete\n\nTask:\n{request['prompt'].strip()}\n\"\"\"\n\n\ndef _write_github_output(path: str, request: dict[str, Any]) -> None:\n    prompt = build_jules_prompt(request)\n    marker = \"JULES_PROMPT_EOF_31D95F04\"\n    if marker in prompt:\n        raise ValueError(\"prompt contains reserved output marker\")\n    with open(path, \"a\", encoding=\"utf-8\") as stream:\n        stream.write(f\"command_id={request['command_id']}\\n\")\n        stream.write(f\"target_branch={request['target_branch']}\\n\")\n        stream.write(f\"work_branch={request['work_branch']}\\n\")\n        stream.write(f\"expected_target_head={request['expected_target_head']}\\n\")\n        stream.write(f\"expected_target_tree={request['expected_target_tree']}\\n\")\n        stream.write(f\"prompt<<{marker}\\n{prompt}\\n{marker}\\n\")\n\n\ndef main() -> int:\n    parser = argparse.ArgumentParser()\n    parser.add_argument(\"request_path\")\n    parser.add_argument(\"--github-output\", required=True)\n    args = parser.parse_args()\n    with open(args.request_path, encoding=\"utf-8\") as stream:\n        request = json.load(stream)\n    validate_request(request)\n    _write_github_output(args.github_output, request)\n    return 0\n\n\nif __name__ == \"__main__\":\n    raise SystemExit(main())\n"
        claim_src = "from __future__ import annotations\n\nimport argparse\nimport json\nimport re\nfrom datetime import datetime\nfrom pathlib import Path\nfrom typing import Any\n\nLOOP_COMMAND_RE = re.compile(\n    r\"^relay-dev-loop-(?P<loop_id>[0-9]{3,6})-(?P<task_id>[a-z0-9][a-z0-9._-]{0,63})$\"\n)\nSHA_RE = re.compile(r\"^[0-9a-f]{40}$\")\nLEGACY_LANE_ID_RE = re.compile(r\"^J-[A-Z0-9][A-Z0-9-]{0,15}$\")\nLEGACY_LANE_DISPLAYS = {\"🟥\", \"🟦\", \"🟩\", \"🟨\"}\nLANE_DISPLAY_BY_ID = {\n    \"J-RED\": \"❤️\",\n    \"J-BLUE\": \"💙\",\n    \"J-YELLOW\": \"💛\",\n    \"J-GREEN\": \"💚\",\n}\nLANE_ALIASES = {\n    \"JA\": \"J-RED\",\n    \"JB\": \"J-BLUE\",\n    \"JC\": \"J-YELLOW\",\n    \"JD\": \"J-GREEN\",\n    \"JG\": \"J-GREEN\",\n    \"RED\": \"J-RED\",\n    \"BLUE\": \"J-BLUE\",\n    \"YELLOW\": \"J-YELLOW\",\n    \"GREEN\": \"J-GREEN\",\n    \"❤️\": \"J-RED\",\n    \"💙\": \"J-BLUE\",\n    \"💛\": \"J-YELLOW\",\n    \"💚\": \"J-GREEN\",\n}\nDISPATCH_CLAIM_SCHEMA_VERSION = 3\nDUPLICATE_GUARD = \"one file per loop number; create-only; if exists choose a new number\"\n\nV1_REQUIRED_KEYS = {\n    \"schema_version\",\n    \"loop_number\",\n    \"loop_id\",\n    \"task_id\",\n    \"command_id\",\n    \"target_branch\",\n    \"expected_target_head\",\n    \"work_branch\",\n    \"state\",\n    \"claimed_at\",\n    \"duplicate_guard\",\n    \"retry\",\n    \"fallback\",\n}\n\nV2_REQUIRED_KEYS = V1_REQUIRED_KEYS | {\n    \"lane_id\",\n    \"lane_display\",\n    \"expected_target_tree\",\n}\nV3_REQUIRED_KEYS = V2_REQUIRED_KEYS\n\nDISPATCHABLE_STATE = \"CLAIMED\"\nARCHIVAL_STATES = {\"CLAIMED\", \"HISTORICAL_BACKFILL\"}\n\n\ndef _parse_time(value: Any, field: str) -> datetime:\n    if not isinstance(value, str) or not value:\n        raise ValueError(f\"{field} must be a non-empty timestamp\")\n    try:\n        parsed = datetime.fromisoformat(value.replace(\"Z\", \"+00:00\"))\n    except ValueError as exc:\n        raise ValueError(f\"{field} must be ISO-8601\") from exc\n    if parsed.tzinfo is None or parsed.utcoffset() is None:\n        raise ValueError(f\"{field} must include timezone\")\n    return parsed\n\n\ndef _validate_sha(value: Any, field: str) -> str:\n    if not isinstance(value, str) or not SHA_RE.fullmatch(value):\n        raise ValueError(f\"invalid {field}\")\n    return value\n\n\ndef normalize_lane_alias(value: Any) -> str:\n    if not isinstance(value, str) or not value.strip():\n        raise ValueError(\"lane alias must be a non-empty string\")\n    normalized = value.strip().upper()\n    if value.strip() in LANE_ALIASES:\n        return LANE_ALIASES[value.strip()]\n    if normalized in LANE_ALIASES:\n        return LANE_ALIASES[normalized]\n    if normalized in LANE_DISPLAY_BY_ID:\n        return normalized\n    raise ValueError(\"unknown Jules lane alias\")\n\n\ndef lane_display_for(lane_id: str) -> str:\n    try:\n        return LANE_DISPLAY_BY_ID[lane_id]\n    except KeyError as exc:\n        raise ValueError(\"unknown Jules lane_id\") from exc\n\n\ndef extract_numbered_loop(command_id: Any) -> tuple[str, str] | None:\n    if not isinstance(command_id, str):\n        return None\n    match = LOOP_COMMAND_RE.fullmatch(command_id)\n    if match is None:\n        return None\n    return match.group(\"loop_id\"), match.group(\"task_id\")\n\n\ndef claim_filename(loop_id: str) -> str:\n    if not isinstance(loop_id, str) or not re.fullmatch(r\"[0-9]{3,6}\", loop_id):\n        raise ValueError(\"invalid loop_id\")\n    return f\"{loop_id}.json\"\n\n\ndef validate_claim(claim: dict[str, Any]) -> dict[str, Any]:\n    if not isinstance(claim, dict):\n        raise ValueError(\"claim must be an object\")\n\n    schema_version = claim.get(\"schema_version\")\n    if schema_version == 1:\n        required = V1_REQUIRED_KEYS\n    elif schema_version == 2:\n        required = V2_REQUIRED_KEYS\n    elif schema_version == 3:\n        required = V3_REQUIRED_KEYS\n    else:\n        raise ValueError(\"unsupported claim schema_version\")\n\n    keys = set(claim)\n    if keys != required:\n        missing = sorted(required - keys)\n        extra = sorted(keys - required)\n        raise ValueError(f\"claim keys mismatch missing={missing} extra={extra}\")\n\n    loop_number = claim[\"loop_number\"]\n    if isinstance(loop_number, bool) or not isinstance(loop_number, int) or loop_number < 0:\n        raise ValueError(\"invalid loop_number\")\n\n    loop_id = claim[\"loop_id\"]\n    if not isinstance(loop_id, str) or not re.fullmatch(r\"[0-9]{3,6}\", loop_id):\n        raise ValueError(\"invalid loop_id\")\n    if int(loop_id) != loop_number:\n        raise ValueError(\"loop_number/loop_id mismatch\")\n\n    command_id = claim[\"command_id\"]\n    parsed = extract_numbered_loop(command_id)\n    if parsed is None:\n        raise ValueError(\"claim command_id must be a numbered Relay loop\")\n    command_loop_id, command_task_id = parsed\n    if command_loop_id != loop_id:\n        raise ValueError(\"claim loop_id/command_id mismatch\")\n    if claim[\"task_id\"] != command_task_id:\n        raise ValueError(\"claim task_id/command_id mismatch\")\n\n    expected_work_branch = f\"jules-work/{command_id}\"\n    if claim[\"work_branch\"] != expected_work_branch:\n        raise ValueError(\"claim work_branch/command_id mismatch\")\n    if not isinstance(claim[\"target_branch\"], str) or not claim[\"target_branch\"]:\n        raise ValueError(\"claim target_branch required\")\n\n    _validate_sha(claim[\"expected_target_head\"], \"expected_target_head\")\n    if schema_version in {2, 3}:\n        _validate_sha(claim[\"expected_target_tree\"], \"expected_target_tree\")\n\n    if schema_version == 2:\n        if (\n            not isinstance(claim[\"lane_id\"], str)\n            or not LEGACY_LANE_ID_RE.fullmatch(claim[\"lane_id\"])\n        ):\n            raise ValueError(\"invalid legacy lane_id\")\n        if claim[\"lane_display\"] not in LEGACY_LANE_DISPLAYS:\n            raise ValueError(\"invalid legacy lane_display\")\n\n    if schema_version == 3:\n        lane_id = claim[\"lane_id\"]\n        if lane_id not in LANE_DISPLAY_BY_ID:\n            raise ValueError(\"invalid lane_id\")\n        if claim[\"lane_display\"] != lane_display_for(lane_id):\n            raise ValueError(\"lane_id/lane_display mismatch\")\n\n    if claim[\"state\"] not in ARCHIVAL_STATES:\n        raise ValueError(\"invalid claim state\")\n    _parse_time(claim[\"claimed_at\"], \"claimed_at\")\n\n    if claim[\"duplicate_guard\"] != DUPLICATE_GUARD:\n        raise ValueError(\"duplicate_guard mismatch\")\n    if claim[\"retry\"] != 0 or claim[\"fallback\"] != \"disabled\":\n        raise ValueError(\"claim retry/fallback policy mismatch\")\n\n    return claim\n\n\ndef verify_command_claim(\n    request: dict[str, Any],\n    claim: dict[str, Any],\n    *,\n    require_dispatchable_current: bool = True,\n) -> dict[str, Any]:\n    parsed = extract_numbered_loop(request.get(\"command_id\"))\n    if parsed is None:\n        raise ValueError(\"request is not a numbered Relay loop\")\n\n    validated = validate_claim(claim)\n    loop_id, _ = parsed\n\n    if validated[\"loop_id\"] != loop_id:\n        raise ValueError(\"command/claim loop_id mismatch\")\n    if validated[\"command_id\"] != request.get(\"command_id\"):\n        raise ValueError(\"command/claim command_id mismatch\")\n    if validated[\"target_branch\"] != request.get(\"target_branch\"):\n        raise ValueError(\"command/claim target_branch mismatch\")\n    if validated[\"expected_target_head\"] != request.get(\"expected_target_head\"):\n        raise ValueError(\"command/claim expected_target_head mismatch\")\n    if validated[\"work_branch\"] != request.get(\"work_branch\"):\n        raise ValueError(\"command/claim work_branch mismatch\")\n    if validated[\"retry\"] != request.get(\"retry\") or validated[\"fallback\"] != request.get(\"fallback\"):\n        raise ValueError(\"command/claim retry/fallback mismatch\")\n\n    if require_dispatchable_current:\n        if validated[\"schema_version\"] != DISPATCH_CLAIM_SCHEMA_VERSION:\n            raise ValueError(\n                f\"numbered dispatch requires claim schema_version \"\n                f\"{DISPATCH_CLAIM_SCHEMA_VERSION}\"\n            )\n        if validated[\"state\"] != DISPATCHABLE_STATE:\n            raise ValueError(\"numbered dispatch requires a pre-dispatch CLAIMED claim\")\n        if validated[\"expected_target_tree\"] != request.get(\"expected_target_tree\"):\n            raise ValueError(\"command/claim expected_target_tree mismatch\")\n\n    return validated\n\n\ndef verify_claim_file(\n    request_path: str | Path,\n    claims_dir: str | Path,\n    *,\n    require_dispatchable_current: bool = True,\n) -> dict[str, Any] | None:\n    request_path = Path(request_path)\n    claims_dir = Path(claims_dir)\n\n    with request_path.open(encoding=\"utf-8\") as stream:\n        request = json.load(stream)\n\n    parsed = extract_numbered_loop(request.get(\"command_id\"))\n    if parsed is None:\n        return None\n\n    loop_id, _ = parsed\n    path = claims_dir / claim_filename(loop_id)\n    if not path.is_file():\n        raise ValueError(f\"missing durable Loop claim: {path.as_posix()}\")\n\n    with path.open(encoding=\"utf-8\") as stream:\n        claim = json.load(stream)\n\n    return verify_command_claim(\n        request,\n        claim,\n        require_dispatchable_current=require_dispatchable_current,\n    )\n\n\ndef _write_github_output(path: str, claim: dict[str, Any] | None) -> None:\n    with open(path, \"a\", encoding=\"utf-8\") as stream:\n        if claim is None:\n            stream.write(\"loop_claim_required=false\\n\")\n            stream.write(\"loop_id=\\n\")\n            stream.write(\"lane_id=\\n\")\n            stream.write(\"lane_display=\\n\")\n            return\n        stream.write(\"loop_claim_required=true\\n\")\n        stream.write(f\"loop_id={claim['loop_id']}\\n\")\n        stream.write(f\"lane_id={claim.get('lane_id', '')}\\n\")\n        stream.write(f\"lane_display={claim.get('lane_display', '')}\\n\")\n\n\ndef main() -> int:\n    parser = argparse.ArgumentParser()\n    parser.add_argument(\"request_path\")\n    parser.add_argument(\n        \"--claims-dir\",\n        default=\"automation/command_bus/loop_id_claims\",\n    )\n    parser.add_argument(\"--github-output\")\n    parser.add_argument(\n        \"--allow-legacy-or-backfill\",\n        action=\"store_true\",\n        help=\"archive/readback mode only; never use for live dispatch\",\n    )\n    args = parser.parse_args()\n\n    claim = verify_claim_file(\n        args.request_path,\n        args.claims_dir,\n        require_dispatchable_current=not args.allow_legacy_or_backfill,\n    )\n    if args.github_output:\n        _write_github_output(args.github_output, claim)\n    return 0\n\n\nif __name__ == \"__main__\":\n    raise SystemExit(main())\n"
        expected_req_blob = "1aebad3469c2bfa629e97fd109541c236dc2244a"
        expected_claim_blob = "d7aba1adfa60b0341d7db6df1b92b8c39bd8c822"

        def git_blob_sha(text):
            data = text.encode("utf-8")
            header = f"blob {len(data)}\0".encode("ascii")
            return hashlib.sha1(header + data).hexdigest()

        if git_blob_sha(req_src) != expected_req_blob:
            raise AssertionError("embedded carrier request snapshot blob mismatch")
        if git_blob_sha(claim_src) != expected_claim_blob:
            raise AssertionError("embedded carrier claim snapshot blob mismatch")

        with open(os.path.join(cls.temp_dir.name, 'automation_compat', 'command_bus', 'jules_api_request.py'), 'w', encoding='utf-8') as req_file:
            req_file.write(req_src)

        with open(os.path.join(cls.temp_dir.name, 'automation_compat', 'command_bus', 'loop_id_claim.py'), 'w', encoding='utf-8') as claim_file:
            claim_file.write(claim_src)

        sys.path.insert(0, cls.temp_dir.name)

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.temp_dir.name)
        cls.temp_dir.cleanup()
        to_del = [k for k in sys.modules if k.startswith('automation_compat')]
        for k in to_del:
            del sys.modules[k]

    def setUp(self):
        self.now = datetime(2026, 9, 30, 0, 30, tzinfo=timezone.utc)
        self.created_at = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc).isoformat()
        self.expires_at = datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc).isoformat()

        self.valid_request = {
            "schema_version": 2,
            "profile": "JULES_CHAT_SEMIAUTO_V2",
            "command_id": "relay-dev-loop-123-compat-baseline",
            "target_repo": "kamiyusense/multi-ai-council-phase0",
            "target_branch": "feature/bounded-target",
            "work_branch": "jules-work/relay-dev-loop-123-compat-baseline",
            "expected_target_head": "2457a6b9b4aa3582fc7eda526c739e1ae54952dc",
            "expected_target_tree": "c9be2e0480b5e52204089410b3583a0b4b1537de",
            "allowed_paths": ["docs/CLAUDE_NIGHT_LOOP_DESIGN.md"],
            "prompt": "Test baseline",
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "retry": 0,
            "fallback": "disabled",
            "merge_allowed": False,
            "force_push_allowed": False
        }

        self.valid_claim = {
            "schema_version": 3,
            "loop_number": 123,
            "loop_id": "123",
            "task_id": "compat-baseline",
            "command_id": "relay-dev-loop-123-compat-baseline",
            "target_branch": "feature/bounded-target",
            "expected_target_head": "2457a6b9b4aa3582fc7eda526c739e1ae54952dc",
            "expected_target_tree": "c9be2e0480b5e52204089410b3583a0b4b1537de",
            "work_branch": "jules-work/relay-dev-loop-123-compat-baseline",
            "state": "CLAIMED",
            "claimed_at": self.created_at,
            "retry": 0,
            "fallback": "disabled",
            "lane_id": "J-GREEN",
            "lane_display": "💚",
            "duplicate_guard": "one file per loop number; create-only; if exists choose a new number"
        }

    def test_baseline_validates(self):
        from automation_compat.command_bus.jules_api_request import validate_request
        from automation_compat.command_bus.loop_id_claim import validate_claim, verify_command_claim
        req = validate_request(self.valid_request, now=self.now)
        self.assertIsNotNone(req)
        claim = validate_claim(self.valid_claim)
        self.assertIsNotNone(claim)
        verified = verify_command_claim(self.valid_request, self.valid_claim)
        self.assertIsNotNone(verified)

    def test_real_target_side_bridge_proof(self):
        from automation.command_bus.claude_loop import prepare_jules_semiauto_request, LoopResult
        from automation_compat.command_bus.jules_api_request import validate_request, REQUIRED_KEYS

        prepared = {
            "request_id": "req-1",
            "loop_id": "123",
            "round": 1,
            "correlation_id": "cor-1",
            "generation": 1,
            "expected_repo": "kamiyusense/multi-ai-council-phase0",
            "expected_target_head": "2457a6b9b4aa3582fc7eda526c739e1ae54952dc",
            "expected_target_tree": "c9be2e0480b5e52204089410b3583a0b4b1537de",
            "expected_pr": 99,
            "path_policy": [{"path": "docs/CLAUDE_NIGHT_LOOP_DESIGN.md", "allowed_ops": ["ADD"]}],
            "objective": "Test",
            "expires_at": self.expires_at,
            "executor_kind": "jules-api",
            "action": "PREPARE_JULES_API_REQUEST",
            "execution_mode": "PREPARE_ONLY",
            "capability": "prepare-only",
            "retry": 0,
            "fallback": "disabled",
            "workspace_integrity_profile": "TREE_IDENTITY_V1",
            "requires_live_model": False,
            "requires_github_write": False,
            "live_start_permitted": False,
        }

        result = prepare_jules_semiauto_request(
            prepared,
            target_branch="feature/bounded-target",
            default_branch="main",
            created_at=self.created_at,
            command_id="relay-dev-loop-123-compat-baseline"
        )
        self.assertEqual(result.status, "PREPARED")
        req = result.request

        # Output carries origin_loop_id, origin_round, origin_correlation_id, origin_generation
        self.assertEqual(req["origin_loop_id"], "123")
        self.assertEqual(req["origin_round"], 1)
        self.assertEqual(req["origin_correlation_id"], "cor-1")
        self.assertEqual(req["origin_generation"], 1)

        # Validate with current carrier validator, proves rejection
        with self.assertRaises(ValueError) as cm:
            validate_request(req, now=self.now)
        self.assertIn("request keys mismatch", str(cm.exception))

        # Change schema_version to 2, still rejected
        req["schema_version"] = 2
        with self.assertRaises(ValueError) as cm:
            validate_request(req, now=self.now)
        self.assertIn("request keys mismatch", str(cm.exception))
        self.assertIn("'work_branch'", str(cm.exception))

    def test_request_schema_version_mismatch(self):
        from automation_compat.command_bus.jules_api_request import validate_request
        req_copy = self.valid_request.copy()
        req_copy["schema_version"] = 1
        with self.assertRaises(ValueError) as cm:
            validate_request(req_copy, now=self.now)
        self.assertIn("unsupported request profile", str(cm.exception))

    def test_request_missing_work_branch(self):
        from automation_compat.command_bus.jules_api_request import validate_request
        req_copy = self.valid_request.copy()
        del req_copy["work_branch"]
        with self.assertRaises(ValueError) as cm:
            validate_request(req_copy, now=self.now)
        self.assertIn("request keys mismatch", str(cm.exception))
        self.assertIn("work_branch", str(cm.exception))

    def test_request_wrong_work_branch_derivation(self):
        from automation_compat.command_bus.jules_api_request import validate_request
        req_copy = self.valid_request.copy()
        req_copy["work_branch"] = "jules-work/wrong-branch-name"
        with self.assertRaises(ValueError) as cm:
            validate_request(req_copy, now=self.now)
        self.assertIn("work_branch must be the isolated per-command branch", str(cm.exception))

    def test_request_target_branch_equals_work_branch(self):
        from automation_compat.command_bus.jules_api_request import validate_request
        req_copy = self.valid_request.copy()
        # Set target_branch to the valid work_branch so that the derivation check passes,
        # but the equality check fails.
        req_copy["target_branch"] = req_copy["work_branch"]
        with self.assertRaises(ValueError) as cm:
            validate_request(req_copy, now=self.now)
        self.assertIn("work_branch must differ from canonical target_branch", str(cm.exception))

    def test_request_unsupported_origin_field(self):
        from automation_compat.command_bus.jules_api_request import validate_request
        req_copy = self.valid_request.copy()
        req_copy["origin_loop_id"] = "456"
        with self.assertRaises(ValueError) as cm:
            validate_request(req_copy, now=self.now)
        self.assertIn("request keys mismatch", str(cm.exception))
        self.assertIn("origin_loop_id", str(cm.exception))

    def test_claim_missing_claim_file_through_verify_claim_file(self):
        from automation_compat.command_bus.loop_id_claim import verify_claim_file
        import json
        import os

        with tempfile.TemporaryDirectory() as td:
            req_path = os.path.join(td, "request.json")
            with open(req_path, "w") as f:
                json.dump(self.valid_request, f)

            claims_dir = os.path.join(td, "claims")
            os.makedirs(claims_dir, exist_ok=True)

            with self.assertRaises(ValueError) as cm:
                verify_claim_file(req_path, claims_dir)
            self.assertIn("missing durable Loop claim", str(cm.exception))

    def test_claim_schema_version_mismatch(self):
        from automation_compat.command_bus.loop_id_claim import verify_command_claim
        claim_copy = self.valid_claim.copy()
        claim_copy["schema_version"] = 2
        claim_copy["lane_id"] = "J-GREEN"
        claim_copy["lane_display"] = "🟩"  # Legacy lane display to pass validate_claim
        with self.assertRaises(ValueError) as cm:
            verify_command_claim(self.valid_request, claim_copy)
        self.assertIn("numbered dispatch requires claim schema_version 3", str(cm.exception))

    def test_claim_historical_backfill(self):
        from automation_compat.command_bus.loop_id_claim import verify_command_claim
        claim_copy = self.valid_claim.copy()
        claim_copy["state"] = "HISTORICAL_BACKFILL"
        with self.assertRaises(ValueError) as cm:
            verify_command_claim(self.valid_request, claim_copy)
        self.assertIn("numbered dispatch requires a pre-dispatch CLAIMED claim", str(cm.exception))

    def test_claim_lane_id_lane_display_mismatch(self):
        from automation_compat.command_bus.loop_id_claim import validate_claim
        claim_copy = self.valid_claim.copy()
        claim_copy["lane_display"] = "❤️" # mismatched display for J-GREEN
        with self.assertRaises(ValueError) as cm:
            validate_claim(claim_copy)
        self.assertIn("lane_id/lane_display mismatch", str(cm.exception))

    def test_cross_binding_expected_target_head_mismatch(self):
        from automation_compat.command_bus.loop_id_claim import verify_command_claim
        claim_copy = self.valid_claim.copy()
        claim_copy["expected_target_head"] = "0000000000000000000000000000000000000000"
        with self.assertRaises(ValueError) as cm:
            verify_command_claim(self.valid_request, claim_copy)
        self.assertIn("command/claim expected_target_head mismatch", str(cm.exception))

    def test_cross_binding_expected_target_tree_mismatch(self):
        from automation_compat.command_bus.loop_id_claim import verify_command_claim
        claim_copy = self.valid_claim.copy()
        claim_copy["expected_target_tree"] = "0000000000000000000000000000000000000000"
        with self.assertRaises(ValueError) as cm:
            verify_command_claim(self.valid_request, claim_copy)
        self.assertIn("command/claim expected_target_tree mismatch", str(cm.exception))

    def test_cross_binding_work_branch_mismatch(self):
        from automation_compat.command_bus.loop_id_claim import verify_command_claim
        claim_copy = self.valid_claim.copy()
        claim_copy["work_branch"] = "jules-work/relay-dev-loop-123-different"
        with self.assertRaises(ValueError) as cm:
            verify_command_claim(self.valid_request, claim_copy)
        self.assertIn("claim work_branch/command_id mismatch", str(cm.exception))

    def test_cross_binding_command_id_mismatch(self):
        from automation_compat.command_bus.loop_id_claim import verify_command_claim
        claim_copy = self.valid_claim.copy()
        # Change command_id and work_branch in claim so that validate_claim succeeds but cross-binding fails
        claim_copy["command_id"] = "relay-dev-loop-123-different"
        claim_copy["work_branch"] = "jules-work/relay-dev-loop-123-different"
        claim_copy["task_id"] = "different"
        with self.assertRaises(ValueError) as cm:
            verify_command_claim(self.valid_request, claim_copy)
        self.assertIn("command/claim command_id mismatch", str(cm.exception))

    def test_cross_binding_mismatch_with_request_mutation(self):
        from automation_compat.command_bus.loop_id_claim import verify_command_claim
        req_copy = self.valid_request.copy()
        req_copy["work_branch"] = "jules-work/relay-dev-loop-123-different"
        with self.assertRaises(ValueError) as cm:
            verify_command_claim(req_copy, self.valid_claim)
        self.assertIn("command/claim work_branch mismatch", str(cm.exception))

    def test_origin_fields_not_in_required_keys_and_rejected_if_added(self):
        from automation_compat.command_bus.jules_api_request import validate_request, REQUIRED_KEYS
        from automation_compat.command_bus.loop_id_claim import validate_claim, V3_REQUIRED_KEYS

        origin_fields = ["origin_loop_id", "origin_round", "origin_correlation_id", "origin_generation"]

        # Verify fields are absent from REQUIRED_KEYS and V3_REQUIRED_KEYS
        for field in origin_fields:
            self.assertNotIn(field, REQUIRED_KEYS)
            self.assertNotIn(field, V3_REQUIRED_KEYS)

        # Verify request rejects them
        req_copy = self.valid_request.copy()
        for field in origin_fields:
            req_copy[field] = "some-value"
        with self.assertRaises(ValueError) as cm_req:
            validate_request(req_copy, now=self.now)
        self.assertIn("request keys mismatch", str(cm_req.exception))
        for field in origin_fields:
            self.assertIn(field, str(cm_req.exception))

        # Verify claim rejects them
        claim_copy = self.valid_claim.copy()
        for field in origin_fields:
            claim_copy[field] = "some-value"
        with self.assertRaises(ValueError) as cm_claim:
            validate_claim(claim_copy)
        self.assertIn("claim keys mismatch", str(cm_claim.exception))
        for field in origin_fields:
            self.assertIn(field, str(cm_claim.exception))
