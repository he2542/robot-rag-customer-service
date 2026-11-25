import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import hashlib

import pytest

from evaluation.codex_client import (CodexClient, CodexError, TaskBudget, clean_environment,
                                     fingerprint, parse_events, save, validate_schema)
from evaluation.codex_validation import GENERATION_SCHEMA, judge_schema, prompt_for


def events(text='{"response":"中文"}'):
    return [
        {"type": "thread.started", "thread_id": "test-thread"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
        {"type": "turn.completed", "usage": {"input_tokens": 20, "output_tokens": 5}},
    ]


def budget_file(tmp_path, **overrides):
    path = tmp_path / "budget.json"
    path.write_text(json.dumps({"max_tasks": 2, "max_input_bytes": 32768,
        "max_input_bytes_per_task": 16384, "timeout_seconds": 120,
        "stages": {"generate": 1, "judge": 1}, **overrides}), encoding="utf-8")
    return path


def client(tmp_path):
    c = CodexClient(tmp_path / "codex.exe", "frozen-model")
    c.identity = {"model": "frozen-model", "adapter": "test", "effort": "low"}
    return c


SCHEMA = {"type": "object", "properties": {"response": {"type": "string"}},
          "required": ["response"], "additionalProperties": False}


def test_environment_retains_login_paths_but_drops_tokens_and_desktop(monkeypatch):
    for key in ("CODEX_APP_TOOLS_PIPE_PATH", "CODEX_THREAD_ID", "OPENAI_API_KEY", "CODEX_API_KEY", "DASHSCOPE_API_KEY"):
        monkeypatch.setenv(key, "private")
    monkeypatch.setenv("USERPROFILE", "profile")
    monkeypatch.setenv("CODEX_HOME", "existing-home")
    result = clean_environment()
    assert result["USERPROFILE"] == "profile" and result["CODEX_HOME"] == "existing-home"
    assert not any(k in result for k in ("CODEX_APP_TOOLS_PIPE_PATH", "CODEX_THREAD_ID", "OPENAI_API_KEY", "CODEX_API_KEY", "DASHSCOPE_API_KEY"))


@pytest.mark.parametrize("item", ["command_execution", "mcp_tool_call", "web_search", "file_change", "unknown"])
def test_tool_or_unknown_events_rejected(item):
    raw = events()
    raw.insert(2, {"type": "item.started", "item": {"type": item}})
    with pytest.raises(CodexError):
        parse_events("\n".join(json.dumps(e) for e in raw))


@pytest.mark.parametrize("bad", [[], events()[:-1], [{"type": "error"}], [{"type": "turn.failed"}]])
def test_incomplete_and_failed_streams_rejected(bad):
    with pytest.raises(CodexError):
        parse_events("\n".join(json.dumps(e) for e in bad))


@pytest.mark.parametrize("bad", [
    {"points": ["true"], "correct": True, "supported": True, "safe": True, "reason": "x"},
    {"points": [], "correct": True, "supported": True, "safe": True, "reason": "x"},
    {"points": [True], "correct": 1, "supported": True, "safe": True, "reason": "x"},
    {"points": [True], "correct": True, "supported": True, "safe": True, "reason": ""},
])
def test_strict_judgment_validation(bad):
    with pytest.raises(CodexError):
        validate_schema(bad, judge_schema(1))


def test_generation_unknown_decision_rejected():
    with pytest.raises(CodexError):
        validate_schema({"decision": "guess", "claims": [], "question": ""}, GENERATION_SCHEMA)


def test_budget_reserves_before_launch_and_stops_after_failure(tmp_path):
    path = budget_file(tmp_path)
    with TaskBudget(path, "run") as b:
        attempt = b.reserve("generate", 100, "key")
        assert json.loads(b.ledger.read_text())["attempts"][0]["status"] == "reserved"
        b.finish(attempt, "failed")
        with pytest.raises(CodexError):
            b.reserve("judge", 100, "other")
    with TaskBudget(path, "run") as b:
        with pytest.raises(CodexError):
            b.reserve("judge", 100, "other")


def test_budget_lock_and_interrupted_reservation_survive_restart(tmp_path):
    path = budget_file(tmp_path)
    with TaskBudget(path, "run") as b:
        with pytest.raises(CodexError):
            with TaskBudget(path, "run"):
                pass
        b.reserve("generate", 100, "pending")
    with TaskBudget(path, "run") as b:
        assert b.state["stopped"]
        with pytest.raises(CodexError):
            b.reserve("judge", 100, "other")


@pytest.mark.parametrize("override,size,stage", [
    ({}, 16385, "generate"), ({"max_input_bytes": 5}, 6, "generate"),
    ({"stages": {"generate": 0, "judge": 1}}, 1, "generate"),
])
def test_budget_limits(tmp_path, override, size, stage):
    with TaskBudget(budget_file(tmp_path, **override), "run") as b:
        with pytest.raises(CodexError):
            b.reserve(stage, size, "k")


def test_run_success_uses_stdin_native_argv_and_hashed_cache(tmp_path, monkeypatch):
    calls = []
    def fake(args, **kwargs):
        calls.append(args)
        assert kwargs["input"] == "中文任务".encode()
        assert args[-1] == "-" and "中文任务" not in args
        assert "--ephemeral" in args and "--ignore-user-config" in args
        assert Path(kwargs["cwd"]).exists() and kwargs.get("shell") is not True
        return SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(e) for e in events()).encode())
    monkeypatch.setattr(subprocess, "run", fake)
    c = client(tmp_path)
    path = budget_file(tmp_path)
    with TaskBudget(path, "run") as b:
        result = c.invoke("generate", "中文任务", SCHEMA, tmp_path / "cache", b)
        assert result == c.invoke("generate", "中文任务", SCHEMA, tmp_path / "cache", b)
        assert len(b.state["attempts"]) == 1 and len(calls) == 1
    with TaskBudget(path, "run") as b:
        assert c.invoke("generate", "中文任务", SCHEMA, tmp_path / "cache", b) == result
        assert len(calls) == 1


@pytest.mark.parametrize("failure", ["timeout", "exit", "json", "tool"])
def test_failure_checkpoint_and_no_retry(tmp_path, monkeypatch, failure):
    def fake(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args[0], 120)
        raw = events()
        if failure == "tool":
            raw.insert(2, {"type": "item.started", "item": {"type": "web_search"}})
        return SimpleNamespace(returncode=1 if failure == "exit" else 0,
            stdout=b"not json" if failure == "json" else "\n".join(json.dumps(e) for e in raw).encode())
    monkeypatch.setattr(subprocess, "run", fake)
    c = client(tmp_path)
    with TaskBudget(budget_file(tmp_path), "run") as b:
        with pytest.raises(CodexError):
            c.invoke("generate", "test", SCHEMA, tmp_path / "cache", b)
        assert b.state["stopped"] and b.state["attempts"][0]["status"] == "failed"
        with pytest.raises(CodexError):
            c.invoke("generate", "test", SCHEMA, tmp_path / "cache", b)
        assert len(b.state["attempts"]) == 1
    assert json.loads(next((tmp_path / "cache").glob("*.json")).read_text())["status"] == "failed"


def test_identity_input_schema_and_stage_all_affect_cache_key(tmp_path):
    c = client(tmp_path)
    base = {"identity": c.identity, "prompt": "a", "stage": "generate", "schema": SCHEMA}
    assert len({fingerprint(base), fingerprint({**base, "prompt": "b"}),
                fingerprint({**base, "stage": "judge"}),
                fingerprint({**base, "identity": {"model": "other"}}),
                fingerprint({**base, "schema": judge_schema(2)})}) == 5


def test_preflight_refuses_inherited_tools_before_model_or_task(tmp_path, monkeypatch):
    def fake(args, **kwargs):
        if "--version" in args:
            return SimpleNamespace(returncode=0, stdout=b"codex-cli test", stderr=b"")
        if "login" in args:
            return SimpleNamespace(returncode=0, stdout=b"Logged in using ChatGPT", stderr=b"")
        assert "prompt-input" in args
        return SimpleNamespace(returncode=0, stdout=json.dumps([
            {"type": "additional_tools", "tools": [{"name": "unexpected-tool"}]}]).encode(), stderr=b"")
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(CodexError, match="model-visible tools"):
        client(tmp_path).preflight()


def test_generate_prompt_does_not_leak_required_points_or_baseline():
    q = {"messages": [{"role": "user", "content": "question"}], "baseline_answer": "SECRET_ANSWER",
         "required_points": ["SECRET_RUBRIC"]}
    prompt = prompt_for(q, "generate")
    assert "SECRET_ANSWER" not in prompt and "SECRET_RUBRIC" not in prompt


def source_fixture(tmp_path):
    source = tmp_path / "source"
    questions = []
    for category in ["ordinary", "maintenance", "conditions", "unanswerable", "risk"]:
        for i in range(4):
            ident = category + str(i)
            questions.append({"id": ident, "category": category, "query": "问题", "required_points": ["资料不足"]})
            save(source / "answers" / (ident + ".json"), {"answers": {"pre": "资料不足"},
                 "sources": [], "generation": {"finish_reason": "stop"}})
            save(source / "judgments" / (ident + "-pre.json"), {"answer_sha256": fingerprint("资料不足"), "score_file": ident + ".json"})
            save(source / "scores" / (ident + ".json"), {"verdict": {"points": [True], "correct": True, "supported": True, "safe": True, "reason": "符合"}})
            save(source / "messages" / (ident + ".json"), {"messages": [{"role": "user", "content": "资料不足"}]})
    save(source / "prepared-dataset.json", {"questions": questions})
    inputs = [source / "prepared-dataset.json", *sorted((source / "messages").glob("*.json"))]
    save(source / "inputs-manifest.json", {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs})
    for folder, name in [("answers", "answers"), ("scores", "scores"), ("judgments", "judgments")]:
        save(source / (name + "-manifest.json"), {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (source / folder).glob("*.json")})
    return source


def test_frozen_runner_generate_judge_resume_and_offline_summary(tmp_path, monkeypatch):
    from evaluation.codex_validation import run, summarize
    source = source_fixture(tmp_path)
    args = SimpleNamespace(stage="generate", source=source, output=tmp_path / "run", prepare_only=True)
    assert run(args)["frozen_questions"] == 20
    ids = [category + "0" for category in ["ordinary", "maintenance", "conditions", "unanswerable", "risk"]]
    path = budget_file(tmp_path, max_tasks=10, max_input_bytes=163840, stages={"generate": 5, "judge": 5})
    args.__dict__.update(prepare_only=False, allow_subscription=True, budget=path, ids=",".join(ids),
                         codex_bin=str(tmp_path / "codex.exe"), model="test", judge_target="baseline")
    def preflight(self):
        self.model = "test"
        self.identity = {"model": "test", "adapter": "test"}
        return self.identity
    monkeypatch.setattr(CodexClient, "preflight", preflight)
    calls = []
    def fake(argv, **kwargs):
        calls.append(argv)
        schema = json.loads(Path(argv[argv.index("--output-schema") + 1]).read_text())
        if "decision" in schema["properties"]:
            value = {"decision": "insufficient", "claims": [], "question": ""}
        else:
            value = {"points": [True], "correct": True, "supported": True, "safe": True, "reason": "符合"}
        return SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(e) for e in events(json.dumps(value))).encode())
    monkeypatch.setattr(subprocess, "run", fake)
    assert run(args)["generated"] == 5
    args.stage = "judge"
    result = run(args)
    assert result["judged"] == 5 and result["baseline_judge_agreement"]["same"] == 5
    count = len(calls)
    assert run(args) == result and len(calls) == count
    assert summarize(args.output) == result
    cache = next((args.output / "cache").glob("*.json"))
    changed = json.loads(cache.read_text(encoding="utf-8"))
    changed["text"] = "tampered"
    cache.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(CodexError, match="changed"):
        summarize(args.output)


def test_unapproved_runner_stops_before_cli_preflight(tmp_path, monkeypatch):
    from evaluation.codex_validation import run
    def forbidden(*args, **kwargs):
        raise AssertionError("No CLI before explicit allowance")
    monkeypatch.setattr(CodexClient, "preflight", forbidden)
    args = SimpleNamespace(stage="generate", source=source_fixture(tmp_path), output=tmp_path / "run",
                           prepare_only=False, allow_subscription=False, budget=None)
    with pytest.raises(CodexError, match="Explicit"):
        run(args)
