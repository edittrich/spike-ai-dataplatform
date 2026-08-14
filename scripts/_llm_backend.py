#!/usr/bin/env python3
"""
===============================================================================
Shared LLM Backend — switch every component between Ollama and Moonshot Kimi
===============================================================================
One `LLM_PROVIDER` value in `.env` selects the model behind *every* LLM-calling
component in this platform:

    LLM_PROVIDER=ollama     # local gemma4:latest via Ollama    (default)
    LLM_PROVIDER=moonshot   # moonshotai/Kimi-K2.6 via the Moonshot API

Consumers (all of which used to embed their own Ollama HTTP call):
  - scripts/agentic_tool_runner.py     (native tool calling)
  - scripts/llm_judge_evaluator.py     (RAG-Triad LLM judge)
  - scripts/rag_explorer_dashboard.py  (grounded generation)
  - scripts/test_e2e_pipeline.py       (end-to-end smoke test)

The two providers are NOT drop-in compatible. Every difference below was
verified live against both APIs, not inferred from documentation:

  1. Tool-call arguments. Ollama returns `message.tool_calls[].function.
     arguments` as an already-parsed JSON *object*; the OpenAI-compatible
     Moonshot API returns it as a JSON *string*. `ToolCall.arguments` below is
     always a dict, so callers never branch on provider.
  2. Tool results. Ollama accepts a bare `{"role": "tool", "content": ...}`
     message. Moonshot (OpenAI semantics) rejects a tool result that carries no
     `tool_call_id` tying it back to the call that produced it -- hence
     `tool_result_message()` rather than callers hand-building the dict.
  3. Token accounting. Ollama reports `prompt_eval_count`/`eval_count` at the
     top level; Moonshot reports `usage.prompt_tokens`/`usage.completion_tokens`.
  4. Temperature. `kimi-k2.6` rejects every temperature except 1 with
     `HTTP 400 invalid temperature: only 1 is allowed for this model`. The
     deterministic `temperature=0.0` the LLM judge relies on is therefore
     simply not available on that model -- see `_supports_temperature()` and
     the honest note in `LLMResponse.temperature_honored`. This is a real
     behavioural difference between the two providers, not a detail: judge
     scores are reproducible under Ollama and are not under Kimi.

Fails closed on misconfiguration (an unknown provider, or `moonshot` with no
API key) rather than silently falling back to the other provider -- picking a
different model than the operator asked for would invalidate every number the
evaluation harness reports.
===============================================================================
"""

import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("LLMBackend")

OLLAMA = "ollama"
MOONSHOT = "moonshot"
SUPPORTED_PROVIDERS = (OLLAMA, MOONSHOT)

# `kimi-*` models accept only temperature=1 (verified live). Anything else is
# forwarded untouched. Kept as a prefix tuple rather than an exact model list so
# a new kimi-k2.x/k3 release inherits the same handling without a code change.
_FIXED_TEMPERATURE_MODEL_PREFIXES = ("kimi-",)


@dataclass
class ToolCall:
    """One model-requested tool invocation, normalized across providers.

    `arguments` is always a parsed dict. `call_id` is the provider's own
    identifier for this call and is required when returning the result on
    OpenAI-compatible APIs; Ollama doesn't issue one, so it may be empty.
    """
    name: str
    arguments: Dict[str, Any]
    call_id: str = ""


@dataclass
class LLMResponse:
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    model_label: str = ""
    # False when the caller asked for a temperature the model refuses to honor
    # (see the module docstring's point 4). Callers that depend on determinism
    # -- the LLM judge -- surface this rather than quietly reporting scores as
    # if they were reproducible.
    temperature_honored: bool = True
    # The provider's own assistant message, to be appended verbatim to the
    # conversation before any tool results. Both APIs require the assistant
    # turn that requested the tools to stay in the history.
    assistant_message: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMBackendError(RuntimeError):
    """Configuration or transport failure that the caller should surface, not
    paper over with a fallback to a different model."""


class _BaseBackend:
    provider = ""

    def __init__(self, model: str, timeout: float):
        self.model = model
        self.timeout = timeout

    @property
    def model_label(self) -> str:
        """Stable `<provider>/<model>` label used for telemetry, cost lookup
        and every user-facing 'which model answered this' line."""
        return f"{self.provider}/{self.model}"

    def _post_json(self, url: str, body: dict, headers: dict, timeout: float) -> dict:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), method="POST", headers=headers
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))


class OllamaBackend(_BaseBackend):
    provider = OLLAMA

    def __init__(self, model: str, base_url: str, timeout: float):
        super().__init__(model, timeout)
        self.base_url = base_url.rstrip("/")
        self.chat_url = f"{self.base_url}/api/chat"
        self.tags_url = f"{self.base_url}/api/tags"

    def is_available(self) -> Tuple[bool, str]:
        try:
            with urllib.request.urlopen(self.tags_url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, socket.timeout, ValueError, OSError) as e:
            return False, f"Ollama unreachable at {self.tags_url}: {e}"
        names = {m.get("name") for m in data.get("models", [])}
        if self.model not in names:
            return False, f"Ollama is reachable but model '{self.model}' is not pulled (available: {sorted(n for n in names if n)})"
        return True, f"Ollama reachable, model '{self.model}' pulled."

    def chat(self, messages, tools=None, temperature=None, timeout=None) -> LLMResponse:
        body: Dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        if temperature is not None:
            body["options"] = {"temperature": temperature}
        if tools:
            body["tools"] = tools
        start = time.perf_counter()
        try:
            data = self._post_json(
                self.chat_url, body, {"Content-Type": "application/json"},
                timeout if timeout is not None else self.timeout,
            )
        except urllib.error.HTTPError as e:
            raise LLMBackendError(f"Ollama HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from e
        except (urllib.error.URLError, socket.timeout, OSError, ValueError) as e:
            raise LLMBackendError(f"Ollama call to {self.chat_url} failed: {e}") from e
        latency_ms = (time.perf_counter() - start) * 1000

        message = data.get("message") or {}
        calls = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            # Ollama hands back a parsed object; tolerate a string anyway so a
            # future server-side change can't break tool dispatch silently.
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            calls.append(ToolCall(name=fn.get("name", ""), arguments=args or {}, call_id=str(tc.get("id") or "")))

        return LLMResponse(
            content=(message.get("content") or "").strip(),
            tool_calls=calls,
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            completion_tokens=int(data.get("eval_count") or 0),
            latency_ms=round(latency_ms, 2),
            model_label=self.model_label,
            temperature_honored=True,
            assistant_message=message,
        )

    def tool_result_message(self, tool_call: ToolCall, content: str) -> Dict[str, Any]:
        return {"role": "tool", "content": content}


class MoonshotBackend(_BaseBackend):
    """OpenAI-compatible Moonshot AI endpoint (`moonshotai/Kimi-K2.6`).

    Note the base URL matters: keys issued for the global endpoint
    (`api.moonshot.ai`) are rejected with 401 by the mainland endpoint
    (`api.moonshot.cn`) and vice versa -- verified live against both.
    """
    provider = MOONSHOT

    def __init__(self, model: str, base_url: str, api_key: str, timeout: float):
        super().__init__(model, timeout)
        self.base_url = base_url.rstrip("/")
        self.chat_url = f"{self.base_url}/chat/completions"
        self.models_url = f"{self.base_url}/models"
        self.api_key = api_key

    def _headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}

    def _supports_temperature(self) -> bool:
        return not self.model.lower().startswith(_FIXED_TEMPERATURE_MODEL_PREFIXES)

    def is_available(self) -> Tuple[bool, str]:
        if not self.api_key:
            return False, "MOONSHOT_API_KEY is not set."
        req = urllib.request.Request(self.models_url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return False, f"Moonshot API returned HTTP {e.code} for {self.models_url} (check MOONSHOT_API_KEY and MOONSHOT_BASE_URL)."
        except (urllib.error.URLError, socket.timeout, ValueError, OSError) as e:
            return False, f"Moonshot API unreachable at {self.models_url}: {e}"
        ids = {m.get("id") for m in data.get("data", [])}
        if self.model not in ids:
            return False, f"Moonshot API is reachable but model '{self.model}' is not offered (available: {sorted(i for i in ids if i)})"
        return True, f"Moonshot API reachable, model '{self.model}' available."

    def chat(self, messages, tools=None, temperature=None, timeout=None) -> LLMResponse:
        body: Dict[str, Any] = {"model": self.model, "messages": messages}
        honored = True
        if temperature is not None:
            if self._supports_temperature():
                body["temperature"] = temperature
            else:
                # Omit rather than coerce to 1: sending a temperature the model
                # silently reinterprets would misrepresent what was asked for.
                honored = temperature == 1
                if not honored:
                    logger.debug(
                        "Model %s accepts only temperature=1; requested %s is not honored.",
                        self.model, temperature,
                    )
        if tools:
            body["tools"] = tools

        start = time.perf_counter()
        eff_timeout = timeout if timeout is not None else self.timeout
        try:
            data = self._post_json(self.chat_url, body, self._headers(), eff_timeout)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            # Defensive retry: if a future model tightens or loosens the
            # temperature rule, drop the field and try once more rather than
            # failing the whole call over a parameter we don't strictly need.
            if e.code == 400 and "temperature" in detail.lower() and "temperature" in body:
                body.pop("temperature", None)
                honored = False
                try:
                    data = self._post_json(self.chat_url, body, self._headers(), eff_timeout)
                except urllib.error.HTTPError as e2:
                    raise LLMBackendError(
                        f"Moonshot HTTP {e2.code}: {e2.read().decode('utf-8', 'replace')[:300]}"
                    ) from e2
            else:
                raise LLMBackendError(f"Moonshot HTTP {e.code}: {detail[:300]}") from e
        except (urllib.error.URLError, socket.timeout, OSError, ValueError) as e:
            raise LLMBackendError(f"Moonshot call to {self.chat_url} failed: {e}") from e
        latency_ms = (time.perf_counter() - start) * 1000

        choices = data.get("choices") or [{}]
        message = choices[0].get("message") or {}
        calls = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments")
            # OpenAI-compatible APIs serialize arguments as a JSON string.
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args) if raw_args.strip() else {}
                except ValueError:
                    logger.warning("Unparseable tool arguments from %s: %r", self.model, raw_args[:200])
                    args = {}
            else:
                args = raw_args or {}
            calls.append(ToolCall(name=fn.get("name", ""), arguments=args, call_id=str(tc.get("id") or "")))

        usage = data.get("usage") or {}
        return LLMResponse(
            content=(message.get("content") or "").strip(),
            tool_calls=calls,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=round(latency_ms, 2),
            model_label=self.model_label,
            temperature_honored=honored,
            assistant_message=message,
        )

    def tool_result_message(self, tool_call: ToolCall, content: str) -> Dict[str, Any]:
        msg: Dict[str, Any] = {"role": "tool", "content": content}
        if tool_call.call_id:
            msg["tool_call_id"] = tool_call.call_id
        msg["name"] = tool_call.name
        return msg


def get_llm_backend(provider: Optional[str] = None):
    """Builds the backend selected by `LLM_PROVIDER` (or the explicit override).

    Read at call time, not import time, so a test can flip the environment
    without re-importing the module -- deliberately unlike the `_neo4j_conn`/
    `_openmetadata_client` helpers, whose import-time reads are a documented
    footgun in CLAUDE.md's Secrets convention section.
    """
    name = (provider or os.getenv("LLM_PROVIDER", OLLAMA)).strip().lower()
    if name not in SUPPORTED_PROVIDERS:
        raise LLMBackendError(
            f"Unknown LLM_PROVIDER {name!r}. Supported: {', '.join(SUPPORTED_PROVIDERS)}. "
            "Refusing to guess -- set LLM_PROVIDER in .env."
        )

    if name == OLLAMA:
        return OllamaBackend(
            model=os.getenv("OLLAMA_MODEL", "gemma4:latest"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
        )

    api_key = os.getenv("MOONSHOT_API_KEY", "")
    if not api_key:
        raise LLMBackendError(
            "LLM_PROVIDER=moonshot but MOONSHOT_API_KEY is not set in .env. Refusing to "
            "fall back to Ollama -- that would silently answer with a different model "
            "than the one configured."
        )
    return MoonshotBackend(
        model=os.getenv("MOONSHOT_MODEL", "kimi-k2.6"),
        base_url=os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1"),
        api_key=api_key,
        timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
    )


def active_provider() -> str:
    return (os.getenv("LLM_PROVIDER", OLLAMA)).strip().lower()
