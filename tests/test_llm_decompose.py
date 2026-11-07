"""LLM API 通信設定とレスポンス変換のテスト。"""

from __future__ import annotations

import os
import sys
import types
from importlib import import_module

import pytest
from dotenv import load_dotenv

decompose_module = import_module("taqumi2026s_teame.llm.decompose")


def test_groq_response_is_converted_to_tasks(monkeypatch, caplog):
    """Groq の OpenAI 互換レスポンスが Task に変換される。"""

    captured: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs: object) -> object:
            captured.update(kwargs)
            message = types.SimpleNamespace(
                content='{"tasks": [{"id": "T001", "title": "APIを実装", "role": "code_gen"}]}'
            )
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=message)]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)

    with caplog.at_level("INFO", logger=decompose_module.logger.name):
        tasks = decompose_module._llm_decompose(
            "要求", decompose_module.DEFAULT_GROQ_MODEL
        )

    assert tasks[0].title == "APIを実装"
    assert 'LLM response: {"tasks":' in caplog.text
    assert captured["api_key"] == "test-groq-key"
    assert captured["base_url"] == decompose_module.GROQ_BASE_URL
    assert captured["model"] == decompose_module.DEFAULT_GROQ_MODEL


def test_decompose_request_uses_groq_defaults(monkeypatch):
    """GROQ_API_KEY がある場合に GPT-OSS 120B が既定選択される。"""

    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)

    def fake_decompose(
        request: str, model: str, context: str | None = None
    ) -> list[object]:
        assert model == decompose_module.DEFAULT_GROQ_MODEL
        return [object()]

    monkeypatch.setattr(decompose_module, "_llm_decompose", fake_decompose)
    result = decompose_module.decompose_request("要求", use_llm=True)

    assert result.used_llm is True
    assert result.message.startswith("LLM（openai/gpt-oss-120b）")


def test_groq_api_returns_task_response():
    """Groq API が実際に応答し、タスクへ変換できることを確認する。"""

    load_dotenv()
    if not os.getenv("GROQ_API_KEY") or os.getenv("RUN_GROQ_LIVE_TESTS") != "1":
        pytest.skip("GROQ_API_KEY と RUN_GROQ_LIVE_TESTS=1 が必要な実 API テスト")

    result = decompose_module.decompose_request(
        "小規模な読書記録 Web アプリを作る",
        use_llm=True,
    )

    assert result.used_llm is True, result.message
    assert result.tasks, result.message
    assert all(task.id and task.title for task in result.tasks)
