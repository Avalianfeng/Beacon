from math_agent.llm_worker import _to_litellm_kwargs, _worker_main


class _ClosingConnection:
    def __init__(self):
        self.messages = []
        self._requests = [
            {
                "type": "req",
                "payload": {
                    "model": "test",
                    "messages": [{"role": "user", "content": "x"}],
                },
            }
        ]

    def send(self, payload):
        if payload.get("type") == "ready":
            self.messages.append(payload)
            return
        raise BrokenPipeError("parent closed")

    def recv(self):
        return self._requests.pop(0)


def test_to_litellm_kwargs_disables_thinking_for_structured_output():
    kw = _to_litellm_kwargs({
        "model": "openai/deepseek-v4-pro",
        "messages": [{"role": "user", "content": "x"}],
        "response_format": {"type": "json_object"},
        "extra": {"max_tokens": 8000, "timeout": 120},
    })
    assert kw["response_format"] == {"type": "json_object"}
    assert kw["max_tokens"] == 8000
    assert kw["extra_body"] == {
        "thinking": {"type": "disabled"},
        "reasoning_effort": "none",
    }
    assert "reasoning_effort" not in kw


def test_to_litellm_kwargs_preserves_existing_extra_body():
    kw = _to_litellm_kwargs({
        "model": "m",
        "messages": [],
        "response_format": {"type": "json_object"},
        "extra": {"extra_body": {"foo": 1}},
    })
    assert kw["extra_body"] == {"foo": 1, "thinking": {"type": "disabled"}, "reasoning_effort": "none"}


def test_to_litellm_kwargs_no_thinking_override_without_schema():
    kw = _to_litellm_kwargs({
        "model": "m",
        "messages": [],
        "extra": {"max_tokens": 100},
    })
    assert "extra_body" not in kw
    assert "reasoning_effort" not in kw


class _RecordingConnection:
    def __init__(self, requests):
        self._requests = list(requests)
        self.messages = []

    def send(self, payload):
        self.messages.append(payload)

    def recv(self):
        if self._requests:
            return self._requests.pop(0)
        return {"type": "stop"}


def _ok_response(content="ok"):
    class Message:
        def __init__(self):
            self.content = content

    class Choice:
        def __init__(self):
            self.message = Message()

    class Usage:
        prompt_tokens = 1
        completion_tokens = 1

    class Response:
        def __init__(self):
            self.choices = [Choice()]
            self.usage = Usage()

    return Response()


def test_worker_retries_with_alternate_thinking_off(monkeypatch):
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        extra_body = kwargs.get("extra_body") or {}
        if extra_body.get("thinking") or "thinking" in kwargs:
            raise TypeError(
                "AsyncCompletions.create() got an unexpected keyword argument 'thinking'"
            )
        return _ok_response('{"ok":true}')

    monkeypatch.setattr("math_agent.llm_worker.litellm.completion", fake_completion)
    connection = _RecordingConnection([
        {
            "type": "req",
            "payload": {
                "model": "openai/deepseek-v4-pro",
                "messages": [{"role": "user", "content": "x"}],
                "response_format": {"type": "json_object"},
                "extra": {"max_tokens": 8000},
            },
        }
    ])
    _worker_main(connection)

    assert len(calls) == 2
    assert calls[0]["extra_body"]["thinking"] == {"type": "disabled"}
    assert calls[0]["extra_body"]["reasoning_effort"] == "none"
    assert "reasoning_effort" not in calls[0]
    assert calls[1]["extra_body"].get("enable_thinking") is False
    assert "thinking" not in calls[1]
    ok = [msg for msg in connection.messages if msg.get("type") == "ok"]
    assert ok[-1]["payload"]["content"] == '{"ok":true}'
    assert ok[-1]["payload"]["thinking_off"] == (
        "extra_body.enable_thinking=false+reasoning_effort=none"
    )
    assert ok[-1]["payload"]["reasoning_content"] == ""


def test_worker_forwards_reasoning_content(monkeypatch):
    def fake_completion(**kwargs):
        response = _ok_response('{"ok":true}')
        response.choices[0].message.reasoning_content = "hidden chain"
        return response

    monkeypatch.setattr("math_agent.llm_worker.litellm.completion", fake_completion)
    connection = _RecordingConnection([
        {
            "type": "req",
            "payload": {
                "model": "m",
                "messages": [{"role": "user", "content": "x"}],
                "response_format": {"type": "json_object"},
            },
        }
    ])
    _worker_main(connection)
    ok = [msg for msg in connection.messages if msg.get("type") == "ok"]
    assert ok[-1]["payload"]["content"] == '{"ok":true}'
    assert ok[-1]["payload"]["reasoning_content"] == "hidden chain"
    assert ok[-1]["payload"]["thinking_off"] == (
        "extra_body.thinking=disabled+reasoning_effort=none"
    )


def test_worker_drops_thinking_only_after_all_disable_variants_fail(monkeypatch):
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        extra_body = kwargs.get("extra_body") or {}
        if extra_body.get("thinking") or extra_body.get("enable_thinking") is False:
            raise TypeError("unknown parameter: thinking")
        chat = extra_body.get("chat_template_kwargs") or {}
        if isinstance(chat, dict) and "enable_thinking" in chat:
            raise TypeError("unknown parameter: thinking")
        return _ok_response('{"ok":true}')

    monkeypatch.setattr("math_agent.llm_worker.litellm.completion", fake_completion)
    connection = _RecordingConnection([
        {
            "type": "req",
            "payload": {
                "model": "m",
                "messages": [{"role": "user", "content": "x"}],
                "response_format": {"type": "json_object"},
            },
        }
    ])
    _worker_main(connection)
    assert len(calls) == 4
    last_body = calls[-1].get("extra_body") or {}
    assert "thinking" not in last_body
    assert "enable_thinking" not in last_body
    assert "reasoning_effort" not in last_body
    assert "reasoning_effort" not in calls[-1]
    ok = [msg for msg in connection.messages if msg.get("type") == "ok"]
    assert ok[-1]["payload"]["thinking_off"] == "removed_after_reject"


def test_worker_does_not_retry_unrelated_completion_errors(monkeypatch):
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("provider failed")

    monkeypatch.setattr("math_agent.llm_worker.litellm.completion", fake_completion)
    connection = _RecordingConnection([
        {
            "type": "req",
            "payload": {
                "model": "m",
                "messages": [{"role": "user", "content": "x"}],
                "response_format": {"type": "json_object"},
            },
        }
    ])
    _worker_main(connection)

    assert len(calls) == 1
    err = [msg for msg in connection.messages if msg.get("type") == "err"]
    assert err and "provider failed" in err[0]["error"]["msg"]


def test_worker_exits_quietly_when_parent_closes_pipe(monkeypatch):
    monkeypatch.setattr(
        "math_agent.llm_worker.litellm.completion",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("provider failed")),
    )
    connection = _ClosingConnection()
    _worker_main(connection)
    assert connection.messages == [{"type": "ready"}]
