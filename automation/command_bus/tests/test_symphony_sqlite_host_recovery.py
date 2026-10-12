"""Actual null-provider regression and isolated read-only host repair, all STATIC."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ..symphony_codex_app_server import JsonlCodexAppServer
from .test_symphony_security_corrective import FakeProcess


def installed_config():
    # Only nonprivate fields from the actual same-process config/read result.
    return {"config": {"model_provider": None, "model_providers": {},
        "forced_login_method": None, "service_tier": "default",
        "openai_base_url": None, "chatgpt_base_url": "https://chatgpt.com/backend-api/"}}


class HostRecoveryTests(unittest.TestCase):
    def probe(self, process, sqlite_home=None):
        with patch.dict(os.environ, {"PATH":"/bin", "HOME":"/STATIC_HOME",
                "CODEX_HOME":"/STATIC_AUTH_HOME", "GH_TOKEN":"STATIC_NEVER_CHILD"}, clear=True), \
             patch("automation.command_bus.symphony_codex_app_server.subprocess.Popen",
                   return_value=process) as launch:
            result=JsonlCodexAppServer().probe_read_only(cwd="/STATIC",sqlite_home=sqlite_home)
        return result, launch

    def test_installed_null_default_account_same_process_and_no_model(self):
        process=FakeProcess(config=installed_config());result,_=self.probe(process)
        self.assertEqual(result["status"],"DONE")
        self.assertEqual([x["method"] for x in process.calls],
                         ["initialize","initialized","account/read","config/read"])
        self.assertEqual(process.calls[2]["params"],{"refreshToken":False})
        self.assertEqual(result["model_dispatch"],0)
        self.assertIn("NOT_ADMISSION",result["route"]["provenance"])
        self.assertNotIn("plan_type",result["route"])

    def test_null_partial_response_is_unknown_not_default_authority(self):
        for cfg in [{}, {"model_provider":None},
                    {k:v for k,v in installed_config()["config"].items() if k!= "openai_base_url"}]:
            with self.subTest(cfg=cfg):
                result,_=self.probe(FakeProcess(config={"config":cfg}))
                self.assertEqual(result["status"],"BLOCKED")

    def test_null_default_does_not_allow_api_or_unverified_account(self):
        for account in [{"requiresOpenaiAuth":True,"account":{"type":"apiKey"}},
                        {"requiresOpenaiAuth":True,"account":None},
                        {"requiresOpenaiAuth":False,"account":{"type":"chatgpt"}}]:
            result,_=self.probe(FakeProcess(account=account,config=installed_config()))
            self.assertEqual(result["status"],"BLOCKED")
            self.assertEqual(result["thread_starts"],0)

    def test_unknown_endpoint_paid_tier_fallback_or_provider_stays_closed(self):
        for key,value in [("openai_base_url","https://api.openai.com/v1"),
                ("chatgpt_base_url","https://chatgpt.com.evil.example/backend-api/"),
                ("chatgpt_base_url","https://user@chatgpt.com/backend-api/"),
                ("chatgpt_base_url","https://chatgpt.com/backend-api/?token=STATIC"),
                ("chatgpt_base_url","http://chatgpt.com/backend-api/"),
                ("model_provider","azure"), ("model_providers",{"custom":{}}),
                ("service_tier","fast"), ("forced_login_method","api"),
                ("paid_credit_fallback_configured",True), ("paid_provider_fallback_configured",0)]:
            with self.subTest(key=key,value=value):
                cfg=installed_config();cfg["config"][key]=value
                result,_=self.probe(FakeProcess(config=cfg))
                self.assertEqual(result["status"],"BLOCKED")

    def test_explicit_openai_proxy_does_not_bypass_endpoint_check(self):
        cfg=installed_config();cfg["config"]["model_provider"]="openai"
        cfg["config"]["openai_base_url"]="https://proxy.invalid"
        result,_=self.probe(FakeProcess(config=cfg))
        self.assertEqual(result["status"],"BLOCKED")

    def test_empty_private_isolation_keeps_auth_home_and_no_child_token(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);p.chmod(0o700)
            result,launch=self.probe(FakeProcess(config=installed_config()),p)
            self.assertEqual(result["status"],"DONE")
            self.assertEqual(launch.call_args.args[0],["codex","app-server","-c",
                            "sqlite_home="+json.dumps(str(p))])
            env=launch.call_args.kwargs["env"]
            self.assertEqual(env["CODEX_HOME"],"/STATIC_AUTH_HOME")
            self.assertNotIn("GH_TOKEN",env)
            self.assertEqual(list(p.iterdir()),[])

    def test_existing_database_symlink_or_nonprivate_directory_never_opened(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);p.chmod(0o700);db=p/"state_5.sqlite";db.write_bytes(b"PRESERVE_EXISTING")
            result,launch=self.probe(FakeProcess(),p)
            self.assertEqual(result["status"],"UNKNOWN");launch.assert_not_called()
            self.assertEqual(db.read_bytes(),b"PRESERVE_EXISTING")
            link=p/"link";empty=p/"empty";empty.mkdir(mode=0o700);link.symlink_to(empty,target_is_directory=True)
            for directory in [link,"relative/dir",p/"missing"]:
                result,launch=self.probe(FakeProcess(),directory)
                self.assertEqual(result["status"],"UNKNOWN");launch.assert_not_called()
            empty.chmod(0o755);result,launch=self.probe(FakeProcess(),empty)
            self.assertEqual(result["status"],"UNKNOWN");launch.assert_not_called()

    def test_diagnostic_isolation_never_becomes_worker_or_live_authorization(self):
        with tempfile.TemporaryDirectory() as root, \
             patch("automation.command_bus.symphony_codex_app_server.subprocess.Popen") as launch:
            result=JsonlCodexAppServer()._session(cwd="/STATIC",prompt="STATIC",live_enabled=True,
                                                readonly=False,sqlite_home=root)
            self.assertEqual(result.status,"UNKNOWN");launch.assert_not_called()
            result=JsonlCodexAppServer().execute_one_turn(cwd="/STATIC",prompt="STATIC")
            self.assertEqual(result.status,"BLOCKED");launch.assert_not_called()

    def test_real_transport_cleanup_also_runs_after_unknown_initialization(self):
        class FailedProcess(FakeProcess):
            def write(self,line):raise BrokenPipeError("STATIC")
        process=FailedProcess();process.stopped=False
        original=process.terminate
        def terminate():process.stopped=True;original()
        process.terminate=terminate
        result,_=self.probe(process)
        self.assertEqual(result["status"],"UNKNOWN");self.assertTrue(process.stopped)
        self.assertEqual(result["model_dispatch"],0)


if __name__ == "__main__":unittest.main()
