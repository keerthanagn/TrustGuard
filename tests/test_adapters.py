from config.settings import load_settings
from core.errors import LLMUnavailableError
from llm.adapters import OpenAICompatClient, build_llm
from llm.base import FailingLLM, ScriptedLLM
from llm.ollama_client import OllamaClient


def test_build_ollama_default():
    s = load_settings()
    assert isinstance(build_llm(s), OllamaClient)


def test_build_openai_compat():
    s = load_settings().with_overrides({"llm": {"provider": "openai"}})
    client = build_llm(s)
    assert isinstance(client, OpenAICompatClient)


def test_build_scripted_and_failing():
    assert isinstance(build_llm(load_settings().with_overrides({"llm": {"provider": "scripted"}})), ScriptedLLM)
    assert isinstance(build_llm(load_settings().with_overrides({"llm": {"provider": "failing"}})), FailingLLM)


def test_unknown_provider_raises():
    import pytest
    with pytest.raises(LLMUnavailableError):
        build_llm(load_settings().with_overrides({"llm": {"provider": "nope"}}))


def test_openai_client_unreachable_fails_cleanly():
    import pytest
    c = OpenAICompatClient(base_url="http://127.0.0.1:59999/v1", model="x", connect_timeout_s=0.2,
                           read_timeout_s=0.2, technical_retries=0)
    with pytest.raises(LLMUnavailableError):
        c.generate("sys", "prompt")
