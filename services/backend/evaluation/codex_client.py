"""Bounded, subscription-only Codex CLI tasks for offline evaluation."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time


VERSION = "codex-eval-v2"
INSTRUCTIONS = "Evaluate only the supplied task and evidence. Return exactly the requested JSON. Do not use tools."
TOOL_METADATA = {"tool_mode": "direct", "multi_agent_version": "disabled",
                 "shell_type": "disabled", "apply_patch_tool_type": None,
                 "experimental_supported_tools": [], "supports_search_tool": False}
SETTINGS = {
    "forced_login_method": "chatgpt",
    "model_reasoning_effort": "low", "approval_policy": "never",
    "project_doc_max_bytes": 0, "skills.include_instructions": False,
    "include_apps_instructions": False, "mcp_servers": {}, "plugins": {},
    "web_search": "disabled", "tools.update_plan.enabled": False,
    "tools.experimental_request_user_input.enabled": False,
}
for _feature in (
    "shell_tool", "unified_exec", "apps", "browser_use", "browser_use_external",
    "computer_use", "multi_agent", "code_mode", "code_mode_host", "view_image",
    "sleep_tool", "workspace_dependencies", "remote_plugin", "skill_search",
    "skill_mcp_dependency_install", "unbounded_connection_retries", "plugins", "image_generation",
):
    SETTINGS["features." + _feature] = False


class CodexError(Exception):
    """Evaluation stops without switching providers or repeating a task."""


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive checkpoints never overwrite a prior task or its failure.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def clean_environment():
    """Keep OS/login paths; remove inherited desktop sessions and API credentials."""
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "USERPROFILE",
               "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "HOME", "HOMEDRIVE",
               "HOMEPATH", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY"}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    if "CODEX_HOME" in os.environ:
        env["CODEX_HOME"] = os.environ["CODEX_HOME"]
    return env


def validate_schema(value, schema):
    """Validate the small strict JSON Schema subset used by these tasks."""
    if "enum" in schema and value not in schema["enum"]:
        raise CodexError("Output value outside schema enum")
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict) or set(value) != set(schema["required"]):
            raise CodexError("Output object fields do not match schema")
        for name, spec in schema["properties"].items():
            validate_schema(value[name], spec)
    elif kind == "array":
        if not isinstance(value, list):
            raise CodexError("Expected array")
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", float("inf")):
            raise CodexError("Wrong number of output items")
        for item in value:
            validate_schema(item, schema["items"])
    elif kind == "boolean":
        if type(value) is not bool:
            raise CodexError("Expected boolean")
    elif kind == "string":
        if not isinstance(value, str) or len(value) < schema.get("minLength", 0):
            raise CodexError("Expected nonempty string")
    else:
        raise CodexError("Unsupported output schema")


def parse_events(raw):
    text, usage, completed, thread = None, None, False, None
    model = None
    events = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        events.append(event)
        kind = event.get("type")
        if kind in {"error", "turn.failed"}:
            raise CodexError("Codex task failed")
        if kind == "thread.started":
            thread = event.get("thread_id")
        model = event.get("model", model)
        if kind and kind.startswith("item."):
            item = event.get("item", {})
            if item.get("type") == "error":
                raise CodexError("CLI diagnostic prevented acceptance: " + item.get("message", "unknown"))
            if item.get("type") not in {"agent_message", "reasoning"}:
                raise CodexError("Unexpected tool or action event")
            if kind == "item.completed" and item.get("type") == "agent_message":
                text = item.get("text")
        if kind == "turn.completed":
            if completed:
                raise CodexError("Multiple completed turns")
            completed, usage = True, event.get("usage")
    if not completed or not thread or not isinstance(text, str) or not isinstance(usage, dict):
        raise CodexError("Missing final answer, session identity or usage")
    return {"text": text, "usage": usage, "thread_id": thread, "event_model": model,
            "events": events, "finish_reason": "completed"}


class TaskBudget:
    """A locked, restartable ledger; attempts are reserved before process launch."""

    def __init__(self, path, binding):
        self.path = Path(path)
        self.config = read(self.path)
        for key in ("max_tasks", "max_input_bytes", "max_input_bytes_per_task", "timeout_seconds"):
            if type(self.config.get(key)) is not int or self.config[key] < 1:
                raise CodexError("Invalid task budget")
        if self.config["max_input_bytes_per_task"] > 16384 or self.config["timeout_seconds"] > 120:
            raise CodexError("Task budget exceeds adapter limits")
        for stage in ("generate", "judge"):
            if type(self.config.get("stages", {}).get(stage)) is not int or self.config["stages"][stage] < 0:
                raise CodexError("Explicit per-stage limits required")
        self.ledger = self.path.with_name(self.path.name + ".usage.json")
        self.lock = self.path.with_name(self.path.name + ".lock")
        self.binding = binding

    def __enter__(self):
        try:
            self.fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise CodexError("Budget already locked; inspect the previous worker before recovery") from None
        try:
            self.state = read(self.ledger) if self.ledger.exists() else {
                "budget_sha256": fingerprint(self.config), "run_sha256": self.binding,
                "billing": "chatgpt_subscription", "attempts": [], "stopped": False,
            }
            if (self.state["budget_sha256"] != fingerprint(self.config)
                    or self.state["run_sha256"] != self.binding):
                raise CodexError("Budget belongs to another configuration or run")
            if any(a["status"] == "reserved" for a in self.state["attempts"]):
                self.state["stopped"] = True
            self.flush()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def flush(self):
        temporary = self.ledger.with_name(self.ledger.name + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(self.state, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.ledger)

    def reserve(self, stage, size, key):
        attempts = self.state["attempts"]
        cfg = self.config
        if (self.state["stopped"] or len(attempts) >= cfg["max_tasks"]
                or size > cfg["max_input_bytes_per_task"]
                or sum(a["input_bytes"] for a in attempts) + size > cfg["max_input_bytes"]
                or sum(a["stage"] == stage for a in attempts) >= cfg["stages"][stage]):
            raise CodexError("Subscription task budget exhausted")
        attempt = {"stage": stage, "input_bytes": size, "cache_key": key, "status": "reserved"}
        attempts.append(attempt)
        self.flush()
        return attempt

    def finish(self, attempt, status, **metadata):
        attempt.update(status=status, **metadata)
        if status != "success":
            self.state["stopped"] = True
        self.flush()

    def __exit__(self, *exc):
        os.close(self.fd)
        self.lock.unlink()


class CodexClient:
    def __init__(self, executable="codex", model=None):
        self.executable = str(Path(shutil.which(str(executable)) or executable).resolve())
        if Path(self.executable).suffix.lower() in {".cmd", ".bat", ".ps1"}:
            raise CodexError("Use the native Codex executable, not a shell launcher")
        self.model = model
        self.identity = None
        self.catalog = None
        self.overrides = {}

    def arguments(self, catalog_path=None, instructions_path=None):
        settings = {**SETTINGS, **self.overrides}
        if self.model:
            settings["model"] = self.model
        if catalog_path is not None:
            settings["model_catalog_json"] = str(catalog_path)
        if instructions_path is not None:
            settings["model_instructions_file"] = str(instructions_path)
        return [self.executable, "--no-daemon"] + [
            part for key, value in settings.items() for part in ("-c", key + "=" + json.dumps(value))
        ]

    @staticmethod
    def global_instructions():
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        for filename in ("AGENTS.override.md", "AGENTS.md"):
            path = home / filename
            if path.is_file():
                return path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
        return ""

    def write_runtime_files(self, cwd):
        catalog = Path(cwd) / "model-catalog.json"
        instructions = Path(cwd) / "instructions.txt"
        catalog.write_text(json.dumps(self.catalog), encoding="utf-8")
        instructions.write_text(INSTRUCTIONS, encoding="utf-8")
        return catalog, instructions

    def preflight(self):
        """No generation. Prove zero tools; fingerprint the user's global rules."""
        env = clean_environment()
        with tempfile.TemporaryDirectory(prefix="rag-codex-check-") as cwd:
            def inspect(args):
                result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, timeout=30)
                if result.returncode:
                    raise CodexError("Codex preflight command failed")
                return result.stdout.decode("utf-8")
            version = inspect([self.executable, "--version"]).strip()
            login = inspect([self.executable, "login", "status"])
            # Login status may be written to stderr by CLI versions; handled below.
            if "ChatGPT" not in login:
                result = subprocess.run([self.executable, "login", "status"], cwd=cwd,
                                        env=env, capture_output=True, timeout=30)
                if result.returncode or b"ChatGPT" not in result.stdout + result.stderr:
                    raise CodexError("ChatGPT subscription login required")
            startup = json.loads(inspect(self.arguments() + ["app-server", "--print-startup-config"]))
            requirements = startup.get("configRequirements", {}).get("requirements", {})
            provider = requirements.get("modelProvider") or "openai"
            if not re.fullmatch(r"[A-Za-z0-9_-]+", provider):
                raise CodexError("Unsupported effective provider identity")
            if provider != "openai":
                from urllib.parse import urlsplit
                info = requirements.get("modelProviders", {}).get(provider, {})
                if (urlsplit(info.get("base_url", "")).hostname != "chatgpt.com"
                        or info.get("requires_openai_auth") is not True or info.get("env_key")):
                    raise CodexError("Provider is not verified for ChatGPT subscription authentication")
            self.overrides["model_provider"] = provider
            # Empty tables merge with existing settings; explicitly disable every server.
            servers = json.loads(inspect([self.executable, "mcp", "list", "--json"]))
            for server in servers:
                name = server["name"]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                    raise CodexError("MCP server name cannot be safely overridden")
                self.overrides["mcp_servers." + name + ".enabled"] = False
                # A complete disabled transport is required even for ignored user config.
                self.overrides["mcp_servers." + name + ".command"] = "codex-evaluation-disabled"
            source_catalog = json.loads(inspect(self.arguments() + ["debug", "models"]))
            available = [m for m in source_catalog["models"] if m.get("visibility", "list") == "list"]
            if not available:
                raise CodexError("No account model available")
            selected = (next((m for m in available if m["slug"] == self.model), None)
                        if self.model else min(available, key=lambda m: m.get("priority", 999)))
            if selected is None:
                raise CodexError("Requested model unavailable; no automatic fallback")
            self.model = selected["slug"]
            self.catalog = {"models": [{**selected, **TOOL_METADATA}]}
            catalog_path, instructions_path = self.write_runtime_files(cwd)
            prompt = json.loads(inspect(self.arguments(catalog_path, instructions_path)
                                        + ["debug", "prompt-input", "EVALUATION_PREFLIGHT"]))
            inherited_tools = [tool.get("name", "unknown") for item in prompt
                               for tool in item.get("tools", [])]
            if inherited_tools:
                raise CodexError("Isolation preflight failed: model-visible tools remain: " + ", ".join(inherited_tools))
            expected_instructions = self.global_instructions()
            rule_blocks = [part["text"] for item in prompt if item.get("role") == "user"
                           for part in item.get("content", []) if part.get("type") == "input_text"
                           and part.get("text", "").startswith("# AGENTS.md instructions")]
            if len(rule_blocks) != bool(expected_instructions):
                raise CodexError("Unexpected inherited instruction blocks")
            if rule_blocks:
                actual = rule_blocks[0].split("<INSTRUCTIONS>\n", 1)[-1].rsplit("</INSTRUCTIONS>", 1)[0]
                if actual.replace("\r\n", "\n").strip() != expected_instructions:
                    raise CodexError("Inherited instructions do not match the user's global rules")
            self.identity = {"adapter": VERSION, "cli_version": version, "model": self.model,
                             "effort": "low", "settings": {**SETTINGS, **self.overrides},
                             "effective_provider": provider,
                             "catalog_sha256": fingerprint(self.catalog),
                             "source_model_sha256": fingerprint(selected),
                             "global_instructions_sha256": fingerprint(expected_instructions),
                             "global_instructions_bytes": len(expected_instructions.encode("utf-8")),
                             "base_instructions_sha256": fingerprint(INSTRUCTIONS),
                             "model_visible_tools": [],
                             "executable_sha256": hashlib.sha256(Path(self.executable).read_bytes()).hexdigest(),
                             "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        return self.identity

    def invoke(self, stage, prompt, schema, output, budget):
        if self.identity is None:
            raise CodexError("Isolation preflight must pass first")
        if (self.identity.get("global_instructions_sha256") != fingerprint(self.global_instructions())
                or self.identity.get("catalog_sha256") != fingerprint(self.catalog)):
            raise CodexError("Isolation configuration changed after preflight")
        binding = {"identity": self.identity, "stage": stage, "prompt": prompt, "schema": schema}
        key = fingerprint(binding)
        path = Path(output) / (key + ".json")
        if path.exists():
            cached = read(path)
            if cached.get("binding") != binding or cached.get("status") != "success":
                raise CodexError("Invalid or failed checkpoint; no automatic retry")
            validate_schema(json.loads(cached["text"]), schema)
            parsed = parse_events("\n".join(json.dumps(e) for e in cached["events"]))
            if any(parsed[k] != cached[k] for k in ("text", "usage", "thread_id", "event_model")):
                raise CodexError("Cached answer differs from raw CLI events")
            return cached
        input_bytes = (len(prompt.encode("utf-8")) + self.identity["global_instructions_bytes"]
                       + len(INSTRUCTIONS.encode("utf-8")))
        attempt = budget.reserve(stage, input_bytes, key)
        started = time.monotonic()
        diagnostic = {}
        try:
            with tempfile.TemporaryDirectory(prefix="rag-codex-task-") as cwd:
                schema_path = Path(cwd) / "output-schema.json"
                schema_path.write_text(json.dumps(schema), encoding="utf-8")
                catalog_path, instructions_path = self.write_runtime_files(cwd)
                args = self.arguments(catalog_path, instructions_path) + ["exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                    "--sandbox", "read-only", "--json", "--color", "never", "--model", self.model,
                    "--output-schema", str(schema_path), "-"]
                result = subprocess.run(args, input=prompt.encode("utf-8"), cwd=cwd,
                    env=clean_environment(), capture_output=True, timeout=budget.config["timeout_seconds"])
                diagnostic = {"exit_code": result.returncode,
                              "stdout": result.stdout.decode("utf-8", errors="replace")[:65536],
                              "stderr": result.stderr.decode("utf-8", errors="replace")[:16384]}
                if result.returncode:
                    raise CodexError("Codex exited unsuccessfully; inspect local CLI authentication or quota")
                if len(result.stdout) > 2 * 1024 * 1024:
                    raise CodexError("Event output exceeds 2 MiB")
                parsed = parse_events(result.stdout.decode("utf-8"))
                if len(parsed["text"].encode("utf-8")) > 16384:
                    raise CodexError("Final output exceeds 16 KiB acceptance limit")
                validate_schema(json.loads(parsed["text"]), schema)
                if parsed["event_model"] and parsed["event_model"] != self.model:
                    raise CodexError("Model changed during task")
                value = {"status": "success", "binding": binding, **parsed,
                         "elapsed_seconds": time.monotonic() - started}
                save(path, value)
                budget.finish(attempt, "success", elapsed_seconds=value["elapsed_seconds"],
                              output_bytes=len(parsed["text"].encode("utf-8")), usage=parsed["usage"])
                return value
        except (Exception, KeyboardInterrupt) as error:
            reason = "timeout" if isinstance(error, subprocess.TimeoutExpired) else type(error).__name__
            save(path, {"status": "failed", "binding": binding, "failure_type": reason,
                        "diagnostic": diagnostic, "error": str(error),
                        "elapsed_seconds": time.monotonic() - started})
            budget.finish(attempt, "failed", failure_type=reason, elapsed_seconds=time.monotonic() - started)
            raise CodexError("Task stopped: " + reason) from None
