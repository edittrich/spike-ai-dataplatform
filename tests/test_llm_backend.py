"""
Tests for the LLM_PROVIDER switch (scripts/_llm_backend.py).

Covers the provider-selection contract and every normalization the two APIs
force on us. All offline: the HTTP layer is stubbed, so these run in CI with no
Ollama process and no Moonshot API key, exactly like the rest of tests/.

The response fixtures below are the *real* shapes both APIs returned during
implementation, not invented ones -- in particular Moonshot's
`tool_calls[].function.arguments` really is a JSON string while Ollama's is an
object, which is the single most breakage-prone difference between them.
"""

import json

import pytest

from scripts._llm_backend import (
    MOONSHOT,
    OLLAMA,
    LLMBackendError,
    MoonshotBackend,
    OllamaBackend,
    ToolCall,
    get_llm_backend,
)


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------


def test_defaults_to_ollama(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    backend = get_llm_backend()
    assert backend.provider == OLLAMA
    assert backend.model_label.startswith("ollama/")


def test_moonshot_selected_by_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "moonshot")
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-test")
    monkeypatch.setenv("MOONSHOT_MODEL", "kimi-k2.6")
    backend = get_llm_backend()
    assert backend.provider == MOONSHOT
    assert backend.model_label == "moonshot/kimi-k2.6"


def test_provider_name_is_case_and_space_insensitive(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "  MoonShot ")
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-test")
    assert get_llm_backend().provider == MOONSHOT


def test_unknown_provider_fails_closed(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(LLMBackendError) as exc:
        get_llm_backend()
    assert "Unknown LLM_PROVIDER" in str(exc.value)


def test_moonshot_without_api_key_fails_closed_rather_than_falling_back(monkeypatch):
    # The important half: a missing key must NOT quietly answer with Ollama.
    monkeypatch.setenv("LLM_PROVIDER", "moonshot")
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    with pytest.raises(LLMBackendError) as exc:
        get_llm_backend()
    assert "MOONSHOT_API_KEY" in str(exc.value)


# ---------------------------------------------------------------------------
# Response normalization -- the real wire shapes of both providers
# ---------------------------------------------------------------------------

OLLAMA_TOOL_RESPONSE = {
    "message": {
        "role": "assistant",
        "content": "",
        # Ollama: arguments is an OBJECT
        "tool_calls": [
            {"function": {"name": "query_financial_database",
                          "arguments": {"sql_query": "SELECT count(*) FROM financial.party;"}}}
        ],
    },
    "prompt_eval_count": 93,
    "eval_count": 165,
}

MOONSHOT_TOOL_RESPONSE = {
    "choices": [{
        "finish_reason": "tool_calls",
        "message": {
            "role": "assistant",
            "content": None,
            # Moonshot/OpenAI: arguments is a JSON STRING
            "tool_calls": [
                {"id": "query_financial_database_0", "type": "function",
                 "function": {"name": "query_financial_database",
                              "arguments": '{"sql_query": "SELECT count(*) FROM financial.party;"}'}}
            ],
        },
    }],
    "usage": {"prompt_tokens": 93, "completion_tokens": 165, "total_tokens": 258},
}


def _stub(backend, payload):
    backend._post_json = lambda url, body, headers, timeout: payload


def test_ollama_tool_arguments_normalized_to_dict():
    backend = OllamaBackend("gemma4:latest", "http://127.0.0.1:11434", 30)
    _stub(backend, OLLAMA_TOOL_RESPONSE)
    result = backend.chat([{"role": "user", "content": "hi"}])
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert isinstance(call.arguments, dict)
    assert call.arguments["sql_query"].startswith("SELECT count(*)")
    assert result.prompt_tokens == 93 and result.completion_tokens == 165


def test_moonshot_json_string_arguments_are_parsed_to_dict():
    # Without parsing, dispatch_tool would receive a str and every
    # `args.get(...)` in the agentic runner would raise AttributeError.
    backend = MoonshotBackend("kimi-k2.6", "https://api.moonshot.ai/v1", "sk-test", 30)
    _stub(backend, MOONSHOT_TOOL_RESPONSE)
    result = backend.chat([{"role": "user", "content": "hi"}])
    call = result.tool_calls[0]
    assert isinstance(call.arguments, dict), "Moonshot arguments must be parsed from JSON string"
    assert call.arguments["sql_query"].startswith("SELECT count(*)")
    assert call.call_id == "query_financial_database_0"


def test_both_providers_produce_the_same_normalized_tool_call():
    ollama = OllamaBackend("gemma4:latest", "http://127.0.0.1:11434", 30)
    moonshot = MoonshotBackend("kimi-k2.6", "https://api.moonshot.ai/v1", "sk-test", 30)
    _stub(ollama, OLLAMA_TOOL_RESPONSE)
    _stub(moonshot, MOONSHOT_TOOL_RESPONSE)
    a = ollama.chat([{"role": "user", "content": "x"}]).tool_calls[0]
    b = moonshot.chat([{"role": "user", "content": "x"}]).tool_calls[0]
    assert (a.name, a.arguments) == (b.name, b.arguments)


def test_token_accounting_normalized_across_providers():
    ollama = OllamaBackend("gemma4:latest", "http://127.0.0.1:11434", 30)
    moonshot = MoonshotBackend("kimi-k2.6", "https://api.moonshot.ai/v1", "sk-test", 30)
    _stub(ollama, OLLAMA_TOOL_RESPONSE)
    _stub(moonshot, MOONSHOT_TOOL_RESPONSE)
    a = ollama.chat([{"role": "user", "content": "x"}])
    b = moonshot.chat([{"role": "user", "content": "x"}])
    assert (a.prompt_tokens, a.completion_tokens) == (b.prompt_tokens, b.completion_tokens) == (93, 165)
    assert a.total_tokens == b.total_tokens == 258


def test_moonshot_unparseable_arguments_degrade_to_empty_dict_not_crash():
    backend = MoonshotBackend("kimi-k2.6", "https://api.moonshot.ai/v1", "sk-test", 30)
    broken = json.loads(json.dumps(MOONSHOT_TOOL_RESPONSE))
    broken["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{not json"
    _stub(backend, broken)
    result = backend.chat([{"role": "user", "content": "x"}])
    assert result.tool_calls[0].arguments == {}


def test_content_none_normalizes_to_empty_string():
    # Moonshot sends content: null alongside tool_calls; `.strip()` on None
    # would raise.
    backend = MoonshotBackend("kimi-k2.6", "https://api.moonshot.ai/v1", "sk-test", 30)
    _stub(backend, MOONSHOT_TOOL_RESPONSE)
    assert backend.chat([{"role": "user", "content": "x"}]).content == ""


# ---------------------------------------------------------------------------
# Tool-result envelope -- Moonshot rejects a result with no tool_call_id
# ---------------------------------------------------------------------------


def test_moonshot_tool_result_carries_tool_call_id():
    backend = MoonshotBackend("kimi-k2.6", "https://api.moonshot.ai/v1", "sk-test", 30)
    call = ToolCall(name="check_data_quality", arguments={}, call_id="check_data_quality_0")
    msg = backend.tool_result_message(call, "OK")
    assert msg["role"] == "tool"
    assert msg["tool_call_id"] == "check_data_quality_0"


def test_ollama_tool_result_has_no_tool_call_id():
    backend = OllamaBackend("gemma4:latest", "http://127.0.0.1:11434", 30)
    call = ToolCall(name="check_data_quality", arguments={}, call_id="")
    msg = backend.tool_result_message(call, "OK")
    assert msg == {"role": "tool", "content": "OK"}


# ---------------------------------------------------------------------------
# Temperature: kimi-* accepts only 1 (verified live against the real API)
# ---------------------------------------------------------------------------


def test_kimi_omits_unsupported_temperature_and_flags_it():
    backend = MoonshotBackend("kimi-k2.6", "https://api.moonshot.ai/v1", "sk-test", 30)
    sent = {}

    def capture(url, body, headers, timeout):
        sent.update(body)
        return MOONSHOT_TOOL_RESPONSE

    backend._post_json = capture
    result = backend.chat([{"role": "user", "content": "x"}], temperature=0.0)
    assert "temperature" not in sent, "kimi-* rejects any temperature but 1; it must not be sent"
    assert result.temperature_honored is False, "a refused temperature must be reported, not hidden"


def test_non_kimi_moonshot_model_forwards_temperature():
    backend = MoonshotBackend("moonshot-v1-128k", "https://api.moonshot.ai/v1", "sk-test", 30)
    sent = {}

    def capture(url, body, headers, timeout):
        sent.update(body)
        return MOONSHOT_TOOL_RESPONSE

    backend._post_json = capture
    result = backend.chat([{"role": "user", "content": "x"}], temperature=0.2)
    assert sent["temperature"] == 0.2
    assert result.temperature_honored is True


def test_ollama_always_honors_temperature():
    backend = OllamaBackend("gemma4:latest", "http://127.0.0.1:11434", 30)
    sent = {}

    def capture(url, body, headers, timeout):
        sent.update(body)
        return OLLAMA_TOOL_RESPONSE

    backend._post_json = capture
    result = backend.chat([{"role": "user", "content": "x"}], temperature=0.0)
    assert sent["options"] == {"temperature": 0.0}
    assert result.temperature_honored is True


# ---------------------------------------------------------------------------
# Cost accounting follows the provider
# ---------------------------------------------------------------------------


def test_moonshot_model_label_is_priced_from_configured_rate(monkeypatch):
    from scripts.llmops_telemetry import LLMOpsTelemetry
    monkeypatch.setenv("MOONSHOT_PRICE_INPUT_PER_1K", "0.5")
    monkeypatch.setenv("MOONSHOT_PRICE_OUTPUT_PER_1K", "2.0")
    t = LLMOpsTelemetry()
    assert t.calculate_cost("moonshot/kimi-k2.6", 1000, 1000) == pytest.approx(2.5)
    # A model too new to be listed still bills at the configured rate, not $0.
    assert t.calculate_cost("moonshot/kimi-k9", 1000, 0) == pytest.approx(0.5)


def test_moonshot_cost_is_zero_when_rates_are_unset(monkeypatch):
    # Honest default: no fabricated price estimate.
    from scripts.llmops_telemetry import LLMOpsTelemetry
    monkeypatch.delenv("MOONSHOT_PRICE_INPUT_PER_1K", raising=False)
    monkeypatch.delenv("MOONSHOT_PRICE_OUTPUT_PER_1K", raising=False)
    assert LLMOpsTelemetry().calculate_cost("moonshot/kimi-k2.6", 5000, 5000) == 0.0


def test_local_ollama_model_is_free():
    from scripts.llmops_telemetry import LLMOpsTelemetry
    assert LLMOpsTelemetry().calculate_cost("ollama/gemma4:latest", 10_000, 10_000) == 0.0
