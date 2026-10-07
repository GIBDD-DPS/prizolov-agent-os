"""Тесты LLM-слоя (без обращения к сети)."""

from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from prizolov_os.config import Settings
from prizolov_os.llm import (
    AnthropicClient,
    FakeLLMClient,
    LLMError,
    LLMResponse,
    create_client,
    text_response,
    tool_use_response,
)


def make_message(content, stop_reason="end_turn"):
    return BetaMessage.model_validate({
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 3,
            "cache_creation_input_tokens": None,
        },
    })


class StubSDK:
    """Подмена anthropic.Anthropic: запоминает параметры и возвращает заданный ответ."""

    def __init__(self, result):
        self.params = None
        self._result = result
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.params = params
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class TestLLMResponse:
    def test_text_joins_text_blocks(self):
        response = LLMResponse(
            content=[
                {"type": "thinking", "thinking": "", "signature": "s"},
                {"type": "text", "text": "Привет, "},
                {"type": "text", "text": "мир"},
            ],
            stop_reason="end_turn",
            model="m",
        )
        assert response.text == "Привет, мир"
        assert response.tool_calls == []

    def test_tool_calls(self):
        response = tool_use_response("calc", {"expr": "2+2"}, tool_id="t1", text="Считаю")
        assert response.text == "Считаю"
        assert response.stop_reason == "tool_use"
        call = response.tool_calls[0]
        assert (call.id, call.name, call.input) == ("t1", "calc", {"expr": "2+2"})

    def test_refused(self):
        assert LLMResponse(content=[], stop_reason="refusal", model="m").refused
        assert not text_response("ok").refused


class TestFakeClient:
    def test_returns_scripted_responses_in_order(self):
        client = FakeLLMClient(["первый", tool_use_response("calc", {})])
        assert client.complete(system="s", messages=[]).text == "первый"
        assert client.complete(system="s", messages=[]).stop_reason == "tool_use"

    def test_echoes_last_user_message_when_script_ends(self):
        client = FakeLLMClient()
        messages = [
            {"role": "user", "content": "старое"},
            {"role": "assistant", "content": "ответ"},
            {"role": "user", "content": [{"type": "text", "text": "новое"}]},
        ]
        assert client.complete(system="s", messages=messages).text == "[fake] новое"

    def test_records_calls(self):
        client = FakeLLMClient(["ok"])
        tools = [{"name": "calc", "description": "d", "input_schema": {"type": "object"}}]
        client.complete(system="sys", messages=[{"role": "user", "content": "hi"}], tools=tools)
        assert client.calls[0]["system"] == "sys"
        assert client.calls[0]["tools"] == tools


class TestAnthropicClient:
    def test_request_parameters(self):
        sdk = StubSDK(make_message([{"type": "text", "text": "ok"}]))
        client = AnthropicClient(model="claude-sonnet-5-5", effort="low", client=sdk)
        client.complete(system="sys", messages=[{"role": "user", "content": "hi"}])

        assert sdk.params["model"] == "claude-sonnet-5-5"
        assert sdk.params["system"] == "sys"
        assert sdk.params["max_tokens"] == 16000
        assert sdk.params["thinking"] == {"type": "adaptive"}
        assert sdk.params["output_config"] == {"effort": "low"}
        assert sdk.params["cache_control"] == {"type": "ephemeral"}
        assert sdk.params["fallbacks"] == "default"
        assert sdk.params["betas"] == ["server-side-fallback-2026-07-01"]
        assert "tools" not in sdk.params

    def test_passes_tools_and_max_tokens(self):
        sdk = StubSDK(make_message([{"type": "text", "text": "ok"}]))
        tools = [{"name": "calc", "description": "d", "input_schema": {"type": "object"}}]
        AnthropicClient(model="m", client=sdk).complete(
            system="s", messages=[], tools=tools, max_tokens=100
        )
        assert sdk.params["tools"] == tools
        assert sdk.params["max_tokens"] == 100

    def test_converts_response(self):
        sdk = StubSDK(make_message(
            [
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "text", "text": "Считаю"},
                {"type": "tool_use", "id": "t1", "name": "calc", "input": {"expr": "1+1"}},
            ],
            stop_reason="tool_use",
        ))
        response = AnthropicClient(model="m", client=sdk).complete(system="s", messages=[])

        assert response.stop_reason == "tool_use"
        assert response.model == "claude-sonnet-5-5"
        assert response.text == "Считаю"
        assert response.tool_calls[0].input == {"expr": "1+1"}
        assert response.content[0] == {"type": "thinking", "thinking": "", "signature": "sig"}
        assert response.usage.input_tokens == 10
        assert response.usage.cache_read_input_tokens == 3
        assert response.usage.cache_creation_input_tokens == 0

    def test_refusal(self):
        sdk = StubSDK(make_message([], stop_reason="refusal"))
        response = AnthropicClient(model="m", client=sdk).complete(system="s", messages=[])
        assert response.refused
        assert response.text == ""

    def test_wraps_sdk_errors(self):
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        sdk = StubSDK(anthropic.APIConnectionError(request=request))
        with pytest.raises(LLMError, match="Нет соединения"):
            AnthropicClient(model="m", client=sdk).complete(system="s", messages=[])

    def test_create_client_uses_settings(self):
        config = Settings(
            api_key="test-key", model="claude-opus-5-5", effort="high", max_tokens=500
        )
        client = create_client(config)
        assert isinstance(client, AnthropicClient)
        assert (client.model, client.effort, client.max_tokens) == ("claude-opus-5-5", "high", 500)


class TestSettingsLLM:
    def test_defaults(self):
        config = Settings()
        assert config.model == "claude-sonnet-5-5"
        assert config.effort == "medium"

    def test_invalid_effort(self):
        with pytest.raises(ValueError, match="Invalid effort"):
            Settings(effort="extreme").validate()

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
        monkeypatch.setenv("PRIZOLOV_MODEL", "claude-opus-5-5")
        monkeypatch.setenv("PRIZOLOV_EFFORT", "high")
        config = Settings.from_env()
        assert config.api_key == "from-env"
        assert (config.model, config.effort) == ("claude-opus-5-5", "high")


class TestStructuredOutput:
    def test_output_schema_sent_in_output_config(self):
        sdk = StubSDK(make_message([{"type": "text", "text": '{"score": 8}'}]))
        schema = {"type": "object", "properties": {"score": {"type": "integer"}},
                  "required": ["score"], "additionalProperties": False}
        AnthropicClient(model="m", effort="high", client=sdk).complete(
            system="s", messages=[], output_schema=schema
        )
        assert sdk.params["output_config"] == {
            "effort": "high", "format": {"type": "json_schema", "schema": schema}
        }

    def test_fake_records_schema(self):
        client = FakeLLMClient(['{"a": 1}'])
        client.complete(system="s", messages=[], output_schema={"type": "object"})
        assert client.calls[0]["output_schema"] == {"type": "object"}
