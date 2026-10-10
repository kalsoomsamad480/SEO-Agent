"""Tests for src/llm/client.py. The real API is never called: we fake the HTTP layer."""

import pytest
import requests

from src.llm import client as llm_module
from src.llm.client import LLMClient, LLMError, load_prompt
from src.models.schemas import BlogMetadata


class FakeResponse:
    """Stands in for requests.Response with just the parts our client reads."""

    def __init__(self, status_code: int, content: str = "", headers: dict | None = None):
        self.status_code = status_code
        self.headers = headers or {}
        self._content = content
        self.text = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def make_client() -> LLMClient:
    # fallback_model="" turns off the backup model so each test controls every call.
    return LLMClient(api_key="test-key", base_url="https://fake.example/v1", model="fake-model",
                     fallback_model="")


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    """Skip the real waiting between retries so tests run instantly."""
    monkeypatch.setattr(llm_module.time, "sleep", lambda seconds: None)


def fake_post_returning(monkeypatch, responses: list):
    """Make requests.post return the given responses one by one (or raise them)."""
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(llm_module.requests, "post", fake_post)
    return calls


# --- prompts ------------------------------------------------------------------
def test_load_prompt_fills_placeholders_and_keeps_other_braces():
    text = load_prompt("outline", topic="Coffee", focus_keyword="coffee grinder")
    assert "Topic: Coffee" in text
    assert '"coffee grinder"' in text
    assert "{audience}" in text   # not passed in, so left untouched


def test_load_prompt_missing_file_gives_clear_error():
    with pytest.raises(LLMError, match="Prompt file not found"):
        load_prompt("does_not_exist")


def test_missing_api_key_gives_config_error(monkeypatch):
    import config
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="LLM_API_KEY"):
        LLMClient()


# --- generate_text ------------------------------------------------------------
def test_generate_text_returns_reply_and_sends_system_message(monkeypatch):
    calls = fake_post_returning(monkeypatch, [FakeResponse(200, "Hello!")])
    assert make_client().generate_text("Hi", system="Be nice") == "Hello!"
    messages = calls[0]["json"]["messages"]
    assert messages[0] == {"role": "system", "content": "Be nice"}
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"


def test_rate_limit_is_retried(monkeypatch):
    fake_post_returning(monkeypatch, [FakeResponse(429, "slow down"), FakeResponse(200, "OK")])
    assert make_client().generate_text("Hi") == "OK"


def test_gives_up_after_max_attempts(monkeypatch):
    fake_post_returning(monkeypatch, [FakeResponse(503)] * llm_module.MAX_ATTEMPTS)
    with pytest.raises(LLMError, match=f"after {llm_module.MAX_ATTEMPTS} attempts"):
        make_client().generate_text("Hi")


def test_fallback_model_used_when_main_model_is_overloaded(monkeypatch):
    responses = [FakeResponse(503)] * llm_module.MAX_ATTEMPTS + [FakeResponse(200, "From backup")]
    calls = fake_post_returning(monkeypatch, responses)
    client = LLMClient(api_key="k", base_url="https://fake.example/v1", model="main",
                       fallback_model="backup")
    assert client.generate_text("Hi") == "From backup"
    assert calls[-1]["json"]["model"] == "backup"


def test_bad_key_is_not_retried(monkeypatch):
    fake_post_returning(monkeypatch, [FakeResponse(401, "bad key")])
    with pytest.raises(LLMError, match="rejected your key"):
        make_client().generate_text("Hi")


def test_no_internet_gives_clear_error(monkeypatch):
    fake_post_returning(monkeypatch, [requests.ConnectionError()])
    with pytest.raises(LLMError, match="internet"):
        make_client().generate_text("Hi")


def test_empty_reply_is_an_error(monkeypatch):
    fake_post_returning(monkeypatch, [FakeResponse(200, "   ")])
    with pytest.raises(LLMError, match="empty reply"):
        make_client().generate_text("Hi")


# --- generate_json ------------------------------------------------------------
GOOD_JSON = ('{"title": "T", "meta_description": "M", "slug": "s", '
             '"feature_image_alt": "A"}')


def test_generate_json_parses_reply_inside_code_fence(monkeypatch):
    fake_post_returning(monkeypatch, [FakeResponse(200, f"```json\n{GOOD_JSON}\n```")])
    meta = make_client().generate_json("Give metadata", BlogMetadata)
    assert meta.title == "T"


def test_generate_json_retries_once_on_invalid_json(monkeypatch):
    calls = fake_post_returning(monkeypatch, [FakeResponse(200, "not json"), FakeResponse(200, GOOD_JSON)])
    meta = make_client().generate_json("Give metadata", BlogMetadata)
    assert meta.slug == "s"
    assert "not valid" in calls[1]["json"]["messages"][-1]["content"]


def test_generate_json_fails_after_second_invalid_reply(monkeypatch):
    fake_post_returning(monkeypatch, [FakeResponse(200, "nope"), FakeResponse(200, "{}")])
    with pytest.raises(LLMError, match="valid JSON"):
        make_client().generate_json("Give metadata", BlogMetadata)
