import sys
import types
import subprocess

def load_blob(module_name, tree_ish, path):
    blob_id = f"{tree_ish}:{path}"
    source = subprocess.check_output(["git", "show", blob_id]).decode("utf-8")
    mod = types.ModuleType(module_name)
    mod.__file__ = f"git_blob://{blob_id}"
    sys.modules[module_name] = mod
    exec(source, mod.__dict__)
    return mod

try:
    jules_api_request = load_blob("automation.command_bus.jules_api_request", "feature/chat-work-command-bus", "automation/command_bus/jules_api_request.py")
    print(jules_api_request.REQUIRED_KEYS)
finally:
    for m in ["automation.command_bus.jules_api_request"]:
        sys.modules.pop(m, None)
