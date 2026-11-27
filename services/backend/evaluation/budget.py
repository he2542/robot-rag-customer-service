"""Per-run, fail-closed budget at the synchronous evaluation HTTP boundary."""
from contextlib import ExitStack
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
from threading import Lock
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx
import requests
import aiohttp
from urllib3.util.retry import Retry


class BudgetError(Exception):
    """A paid evaluation is disabled, unsupported, exhausted or already used."""


_active = None


def require_budget():
    if _active is None:
        raise BudgetError("Paid evaluation disabled; explicit --allow-paid and --budget are required")


def add_budget_arguments(parser):
    parser.add_argument("--allow-paid", action="store_true", help="Use only after approving this run's budget")
    parser.add_argument("--budget", type=Path, help="Single-use JSON budget; creates a sibling .usage.json ledger")


def budget_from_args(args):
    if not args.allow_paid or args.budget is None:
        raise BudgetError("Paid evaluation disabled; explicit --allow-paid and --budget are required")
    return EvaluationBudget(args.budget)


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise BudgetError(f"Invalid budget integer: {name}")
    return value


def _amount(value, name):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BudgetError(f"Invalid budget amount: {name}") from None
    if not result.is_finite() or result < 0:
        raise BudgetError(f"Invalid budget amount: {name}")
    return result


class EvaluationBudget:
    """Reserve full request bounds before sending; failed calls are not refunded.

    Input uses serialized UTF-8 bytes plus protocol allowance as a conservative
    billing proxy. Optional validated usage receipts reconcile successful task
    money reservations; attempt, input and output limits remain cumulative.
    Amounts use user-supplied prices and are estimates rather than a bill.
    """
    def __init__(self, path):
        self.path = Path(path)
        try:
            raw = self.path.read_bytes()
        except OSError:
            raise BudgetError("Budget file cannot be read") from None
        try:
            cfg = json.loads(raw)
            self.settle_usage = cfg.get("settle_successful_usage", False)
            if type(self.settle_usage) is not bool:
                raise BudgetError("Usage settlement must be a boolean")
            self.calls_limit = _integer(cfg["max_calls"], "max_calls", 1)
            self.input_limit = _integer(cfg["max_input_bytes"], "max_input_bytes", 1)
            self.output_limit = _integer(cfg["max_output_tokens"], "max_output_tokens")
            self.per_output_limit = _integer(cfg["max_output_tokens_per_call"], "max_output_tokens_per_call")
            self.money_limit = _amount(cfg["max_estimated_cost_cny"], "max_estimated_cost_cny")
            self.rates = {model: (_amount(v["input_per_million_cny"], "input rate"),
                                  _amount(v["output_per_million_cny"], "output rate"))
                          for model, v in cfg["models"].items()}
            if not self.rates or any(not isinstance(m, str) or not m or i <= 0 for m, (i, _) in self.rates.items()):
                raise BudgetError("Models require a positive input price")
        except (KeyError, TypeError, ValueError, AttributeError):
            raise BudgetError("Invalid budget JSON") from None
        self.ledger = self.path.with_name(self.path.name + ".usage.json")
        self.config_hash = hashlib.sha256(raw).hexdigest()
        self.calls = self.input_bytes = self.output_tokens = 0
        self.cost = Decimal(0)
        self.stopped = False
        self.lock = Lock()
        self.events = []
        self.adapters = {}

    def _save(self):
        value = {"budget_sha256": self.config_hash, "calls_reserved":self.calls,
                 "input_bytes_reserved":self.input_bytes, "output_tokens_reserved":self.output_tokens,
                 "estimated_cost_cny_reserved":str(self.cost), "stopped":self.stopped,
                 "events":self.events}
        if self.settle_usage:
            value["estimated_cost_cny_exposure"] = str(self.cost)
            value["estimated_cost_cny_reservation_sum"] = str(sum(
                (Decimal(e["estimated_cost_cny"]) for e in self.events), Decimal(0)))
            value["estimated_cost_cny_settled"] = str(sum(
                (Decimal(e["estimated_usage_cost_cny"]) for e in self.events if e.get("settled")), Decimal(0)))
            value["settle_successful_usage"] = True
        temporary = self.ledger.with_name(self.ledger.name + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.ledger)

    def reserve(self, url, method, raw):
        with self.lock:
            if self.stopped:
                raise BudgetError("Evaluation budget stopped")
            try:
                parts = urlsplit(str(url))
                if (parts.scheme != "https" or parts.hostname != "dashscope.aliyuncs.com"
                        or parts.port not in (None,443) or parts.username or parts.password
                        or parts.query or parts.fragment or method.upper() != "POST"
                        or not parts.path.startswith("/api/v1/services/")):
                    raise BudgetError("Unsupported evaluation endpoint")
                body = json.loads(raw)
                model, inputs = body["model"], body["input"]
                if model not in self.rates or not isinstance(inputs, dict):
                    raise BudgetError("Model or input is not covered by this budget")
                if self.settle_usage and "messages" not in inputs:
                    raise BudgetError("Usage settlement supports text generation only")
                params = body.get("parameters", {})
                if not isinstance(params, dict) or any(k in params for k in ("tools","functions")):
                    raise BudgetError("Unsupported evaluation parameters")
                if "messages" in inputs:
                    if not isinstance(inputs["messages"], list) or not inputs["messages"]:
                        raise BudgetError("Unsupported message input")
                    if (set(inputs) != {"messages"}
                            or any(not isinstance(m, dict) or m.get("role") not in {"system","user","assistant"}
                            or not isinstance(m.get("content"), str) for m in inputs["messages"])
                            or params.get("enable_thinking") is True
                            or params.get("n",1) != 1 or params.get("best_of",1) != 1):
                        raise BudgetError("Only single text-only non-thinking completions are supported")
                    if self.rates[model][1] <= 0:
                        raise BudgetError("Generation requires a positive output price")
                    output = _integer(params.get("max_tokens"), "request max_tokens", 1)
                    if output > self.per_output_limit:
                        raise BudgetError("Per-call output token limit exceeded")
                    allowance = 256 * len(inputs["messages"])
                elif (set(inputs) == {"texts"} and isinstance(inputs["texts"], list)
                      and all(isinstance(t, str) for t in inputs["texts"])):
                    output, allowance = 0, 256
                elif (set(inputs) == {"query","documents"} and isinstance(inputs["query"],str)
                      and isinstance(inputs["documents"],list) and all(isinstance(t,str) for t in inputs["documents"])):
                    output, allowance = 0, 256
                    allowance += len(inputs["query"].encode("utf-8")) * max(0,len(inputs["documents"])-1)
                else:
                    raise BudgetError("Unsupported evaluation input")
                size = len(json.dumps(body, ensure_ascii=False).encode("utf-8")) + allowance
                rate_in, rate_out = self.rates[model]
                cost = (size * rate_in + output * rate_out) / 1_000_000
                if (self.calls + 1 > self.calls_limit or self.input_bytes + size > self.input_limit
                        or self.output_tokens + output > self.output_limit or self.cost + cost > self.money_limit):
                    raise BudgetError("Evaluation call, input, output or estimated cost limit exhausted")
            except (KeyError, TypeError, ValueError, UnicodeError):
                self.stopped = True
                self._save()
                raise BudgetError("Unsupported evaluation request") from None
            except BudgetError:
                self.stopped = True
                self._save()
                raise
            self.calls += 1
            self.input_bytes += size
            self.output_tokens += output
            self.cost += cost
            self.events.append({"attempt":self.calls,"model":model,"input_bytes":size,
                                "output_tokens":output,"estimated_cost_cny":str(cost)})
            if self.settle_usage:
                self.events[-1]["input_sha256"] = hashlib.sha256(
                    json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            self._save()
            return self.calls

    def settle_successful_result(self, result):
        """Release unused money only after a validated successful task.

        Calls, bytes and output ceilings remain cumulative; failures retain
        their full reservation. Prices ignore discounts and are not a bill.
        """
        if not self.settle_usage:
            return
        with self.lock:
            try:
                ticket = _integer(result.get("budget_attempt"), "receipt attempt", 1)
                if ticket > len(self.events):
                    raise BudgetError("Unknown usage receipt")
                event = self.events[ticket - 1]
                if event.get("settled") or result.get("input_sha256") != event["input_sha256"]:
                    raise BudgetError("Duplicate or mismatched usage receipt")
                usage = result["usage"]
                input_tokens = _integer(usage["input_tokens"], "receipt input tokens")
                output_tokens = _integer(usage["output_tokens"], "receipt output tokens")
                if input_tokens > event["input_bytes"] or output_tokens > event["output_tokens"]:
                    raise BudgetError("Usage exceeds reserved request bounds")
                rate_in, rate_out = self.rates[event["model"]]
                actual = (input_tokens * rate_in + output_tokens * rate_out) / 1_000_000
                reserved = Decimal(event["estimated_cost_cny"])
                if actual > reserved or result.get("finish_reason") != "stop":
                    raise BudgetError("Only complete valid responses can settle")
                self.cost += actual - reserved
                event.update({"settled": True, "input_tokens": input_tokens,
                              "actual_output_tokens": output_tokens,
                              "estimated_usage_cost_cny": str(actual)})
                self._save()
            except (KeyError, TypeError, ValueError, AttributeError, BudgetError):
                self.stopped = True
                self._save()
                raise BudgetError("Invalid usage receipt; retained reservation and stopped") from None

    def __enter__(self):
        global _active
        if _active is not None:
            raise BudgetError("Nested paid evaluation runs are unsupported")
        # Exclusive creation also prevents two processes from sharing/resetting a budget.
        try:
            with self.ledger.open("x", encoding="utf-8") as handle:
                handle.write("{}")
        except FileExistsError:
            raise BudgetError("Budget already used; preserve its ledger and approve a new run") from None
        self._save()
        self.stack = ExitStack()
        original_httpx = httpx.Client.send
        original_requests = requests.Session.send
        budget = self

        def httpx_send(client, request, **kwargs):
            transport = client._transport_for_url(request.url)
            if not isinstance(transport, (httpx.HTTPTransport, httpx.MockTransport)):
                raise BudgetError("Unsupported evaluation HTTP transport")
            pool = getattr(transport, "_pool", None)
            if getattr(pool, "_retries", 0):
                raise BudgetError("HTTP transport retries must be disabled")
            ticket = budget.reserve(request.url, request.method, request.content)
            response = original_httpx(client, request, **kwargs)
            if budget.settle_usage:
                response.extensions["evaluation_budget_attempt"] = ticket
            return response

        def requests_send(session, request, **kwargs):
            # SDK-level retries pass this boundary again; transport retries are off.
            adapter = session.get_adapter(request.url)
            with budget.lock:
                budget.adapters.setdefault(id(adapter), (adapter, getattr(adapter, "max_retries", None)))
                adapter.max_retries = Retry(total=0, connect=0, read=0, redirect=0, status=0)
            budget.reserve(request.url, request.method, request.body)
            return original_requests(session, request, **kwargs)

        async def reject_async(*args, **kwargs):
            raise BudgetError("Async evaluation is unsupported by this budget guard")

        self.stack.enter_context(patch.object(httpx.Client,"send",httpx_send))
        self.stack.enter_context(patch.object(requests.Session,"send",requests_send))
        self.stack.enter_context(patch.object(httpx.AsyncClient,"send",reject_async))
        self.stack.enter_context(patch.object(aiohttp.ClientSession,"_request",reject_async))
        _active = self
        return self

    def __exit__(self, *exc):
        global _active
        try:
            self.stack.close()
        finally:
            for adapter, retries in self.adapters.values():
                if retries is None:
                    del adapter.max_retries
                else:
                    adapter.max_retries = retries
            _active = None
        return False
