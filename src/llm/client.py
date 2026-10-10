"""The ONE place that talks to the LLM (AI model) API.

Why one place? If you switch provider (Gemini -> Groq -> OpenAI), only
.env changes, and nothing else in the project needs to know.

We use the "OpenAI-compatible" chat API, which many providers offer:
we POST a list of messages to {LLM_BASE_URL}/chat/completions and get text back.
We call it with plain `requests` instead of a provider's SDK, so there is
nothing provider-specific to install.

Main functions:
    load_prompt("write_blog", topic="...")   -> prompt text from prompts/write_blog.txt
    client.generate_text(prompt, system)     -> str
    client.generate_json(prompt, Schema)     -> a validated Pydantic object
"""

import json
import re
import time

import requests
from pydantic import BaseModel, ValidationError

import config
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_ATTEMPTS = 5            # for rate limits and temporary server errors
FIRST_WAIT_SECONDS = 5      # then 10, 20, 40 (each wait doubles)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}   # 429 = "too many requests"


class LLMError(Exception):
    """Any problem talking to the LLM, with a message a human can act on."""


class LLMBusyError(LLMError):
    """The model stayed overloaded or rate-limited through every retry."""


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
def load_prompt(name: str, **values: object) -> str:
    """Read prompts/<name>.txt and fill in {placeholders} with the given values.

    We replace only the names you pass in (instead of str.format), so prompts
    may safely contain other curly braces, like JSON examples.
    """
    path = config.PROMPTS_DIR / f"{name}.txt"
    if not path.is_file():
        raise LLMError(f"Prompt file not found: {path}")
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def _extract_json(reply: str) -> str:
    """Pull the JSON object out of a reply that may be wrapped in ```json fences or chatter."""
    reply = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply.strip())
    start, end = reply.find("{"), reply.rfind("}")
    if start == -1 or end == -1:
        return reply
    return reply[start:end + 1]


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------
class LLMClient:
    """Sends prompts to the configured LLM and returns its replies."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, timeout: int | None = None,
                 fallback_model: str | None = None) -> None:
        # require_setting raises a friendly ConfigError if the key is missing.
        self.api_key = api_key or config.require_setting("LLM_API_KEY")
        self.base_url = (base_url or config.LLM_BASE_URL).rstrip("/")
        self.model = model or config.LLM_MODEL
        self.timeout = timeout or config.LLM_TIMEOUT_SECONDS
        # Backup model for when the main one is overloaded. Pass "" to turn it off.
        self.fallback_model = config.LLM_FALLBACK_MODEL if fallback_model is None else fallback_model

    def generate_text(self, prompt: str, system: str | None = None,
                      temperature: float = 0.7) -> str:
        """Send one prompt and return the model's text reply."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self._send(messages, temperature)

    def generate_json(self, prompt: str, schema: type[BaseModel],
                      system: str | None = None) -> BaseModel:
        """Ask for JSON matching a Pydantic schema and return the validated object.

        Models sometimes return broken JSON. If that happens we tell the model
        exactly what was wrong and try ONE more time, then give up with a clear error.
        """
        json_instructions = (
            "\n\nReply with ONLY one JSON object (no Markdown, no explanation) "
            f"that matches this JSON schema:\n{json.dumps(schema.model_json_schema())}"
        )
        full_prompt = prompt + json_instructions
        # Low temperature = more predictable output, which helps with strict formats.
        reply = self.generate_text(full_prompt, system, temperature=0.3)
        try:
            return schema.model_validate_json(_extract_json(reply))
        except ValidationError as error:
            logger.warning("LLM returned invalid JSON, retrying once (%s)", error.error_count())
            retry_prompt = (
                f"{full_prompt}\n\nYour previous reply was not valid. Problems:\n{error}\n"
                "Reply again with ONLY the corrected JSON object."
            )
            reply = self.generate_text(retry_prompt, system, temperature=0.2)
        try:
            return schema.model_validate_json(_extract_json(reply))
        except ValidationError as error:
            raise LLMError(f"The model did not return valid JSON for {schema.__name__} "
                           f"after a retry: {error}") from error

    # -- the actual HTTP call ------------------------------------------------
    def _send(self, messages: list[dict], temperature: float) -> str:
        """Send to the main model; if it stays overloaded, try the fallback model once."""
        try:
            return self._send_to_model(self.model, messages, temperature)
        except LLMBusyError:
            if not self.fallback_model or self.fallback_model == self.model:
                raise
            logger.warning("Model '%s' is overloaded. Trying fallback model '%s'...",
                           self.model, self.fallback_model)
            return self._send_to_model(self.fallback_model, messages, temperature)

    def _send_to_model(self, model: str, messages: list[dict], temperature: float) -> str:
        """POST the messages to the API, retrying on rate limits and server hiccups."""
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": messages, "temperature": temperature}

        for attempt in range(1, MAX_ATTEMPTS + 1):
            logger.debug("LLM request attempt %s to %s (%s)", attempt, model, url)
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            except requests.Timeout:
                problem = f"no reply within {self.timeout} seconds"
                wait = FIRST_WAIT_SECONDS
            except requests.ConnectionError:
                raise LLMError("Could not connect to the LLM API. Check your internet "
                               f"connection and LLM_BASE_URL ({self.base_url}).") from None
            else:
                if response.status_code == 200:
                    return self._read_reply(response)
                if response.status_code in (401, 403):
                    raise LLMError("The LLM API rejected your key (HTTP "
                                   f"{response.status_code}). Check LLM_API_KEY in .env.")
                if response.status_code not in RETRYABLE_STATUS:
                    raise LLMError(f"LLM API error {response.status_code}: {response.text[:300]}")
                problem = f"HTTP {response.status_code}"
                # Servers sometimes tell us how long to wait. If so, respect it.
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    wait = int(retry_after)
                else:
                    wait = FIRST_WAIT_SECONDS * 2 ** (attempt - 1)

            if attempt == MAX_ATTEMPTS:
                break
            logger.warning("LLM busy or slow (%s). Waiting %s s, then retrying (%s/%s)...",
                           problem, wait, attempt, MAX_ATTEMPTS)
            time.sleep(wait)

        raise LLMBusyError(f"The LLM API failed after {MAX_ATTEMPTS} attempts with model '{model}' "
                           f"({problem}). The service may be overloaded or you hit the free-tier "
                           "limit; wait a few minutes and try again.")

    @staticmethod
    def _read_reply(response: requests.Response) -> str:
        """Get the text out of an OpenAI-style JSON response."""
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError(f"Unexpected reply format from the LLM API: {response.text[:300]}") from None
        if not content or not content.strip():
            raise LLMError("The LLM returned an empty reply (it may have been blocked by a safety filter).")
        return content.strip()


_default_client: LLMClient | None = None


def get_client() -> LLMClient:
    """Return one shared LLMClient (created the first time it's needed)."""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client


def generate_text(prompt: str, system: str | None = None) -> str:
    """Shortcut: generate text with the shared client."""
    return get_client().generate_text(prompt, system)


def generate_json(prompt: str, schema: type[BaseModel]) -> BaseModel:
    """Shortcut: generate validated JSON with the shared client."""
    return get_client().generate_json(prompt, schema)
