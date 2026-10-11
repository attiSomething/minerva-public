"""Bring-your-own-model AI providers.

Minerva never ships with a key. A user who turns on AI-assisted scanning or
organizing picks a provider and pastes their own key, which is kept in the
OS credential store (secrets_store.py). This module knows how to check that
a key works and which models it can reach.
"""

import base64
import json
import urllib.error
import urllib.request

PROVIDERS = {
    "anthropic": {
        "label": "Anthropic (Claude)",
        "needs_key": True,
        "key_hint": "Starts with sk-ant-. Create one at console.anthropic.com.",
        "models": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-haiku-4-5"],
        "default_model": "claude-opus-5-5",
    },
    "openai": {
        "label": "OpenAI",
        "needs_key": True,
        "key_hint": "Starts with sk-. Create one at platform.openai.com.",
        "models": [],
        "default_model": "",
    },
    "gemini": {
        "label": "Google Gemini",
        "needs_key": True,
        "key_hint": "Create one at aistudio.google.com.",
        "models": [],
        "default_model": "",
    },
    "ollama": {
        "label": "Local model (Ollama)",
        "needs_key": False,
        "key_hint": "Runs on this computer. Install Ollama and pull a vision model first.",
        "models": [],
        "default_model": "",
    },
}

# US dollars per million tokens (input, output), from Anthropic's published
# prices in October 2026. Used only for the estimate shown before a scan job;
# other providers show page and token counts without a price.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    # Haiku 5.5 doubles past 100,000 input tokens; Minerva's requests stay
    # well under that
    "claude-haiku-5-5": (0.10, 0.50),
}
# Longest image edge a model reads at full size; larger images are shrunk
# (and cost fewer tokens) on the provider's side.
IMAGE_EDGE = {"claude-haiku-4-5": 1568}

OLLAMA_URL = "http://127.0.0.1:11434"
TIMEOUT = 20
# Reading a page or proofreading an entry takes far longer than listing models.
WORK_TIMEOUT = 300


class ProviderError(Exception):
    user_facing = True


def public_providers():
    return [
        {"id": pid, **{k: v for k, v in p.items()}}
        for pid, p in PROVIDERS.items()
    ]


def clean_key(key):
    """Keys never contain whitespace; pasted ones sometimes pick some up."""
    return "".join((key or "").split())


def _get_json(url, headers=None, body=None, timeout=TIMEOUT):
    headers = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ProviderError("The key was rejected. Check that it was copied correctly.")
        detail = _http_error_detail(e)
        raise ProviderError(f"The provider answered with an error ({e.code})" +
                            (f": {detail}" if detail else "."))
    except urllib.error.URLError as e:
        raise ProviderError(f"Couldn't reach the provider ({e.reason}).")
    except TimeoutError:
        raise ProviderError("The provider took too long to answer.")


def _http_error_detail(e):
    """Pull the provider's own explanation out of an HTTP error body."""
    try:
        body = json.loads(e.read().decode("utf-8"))
    except Exception:
        return ""
    return _message_from_body(body)


def _message_from_body(body):
    if not isinstance(body, dict):
        return ""
    err = body.get("error", body)
    if isinstance(err, dict):
        return str(err.get("message") or "").strip()
    return str(err).strip() if isinstance(err, str) else ""


def _anthropic_call(fn):
    import anthropic

    try:
        return fn()
    except anthropic.AuthenticationError:
        raise ProviderError("The key was rejected. Check that it was copied correctly.")
    except anthropic.PermissionDeniedError as e:
        detail = _message_from_body(e.body)
        raise ProviderError("The key works but isn't allowed to do this" +
                            (f": {detail}" if detail else "."))
    except anthropic.APIStatusError as e:
        detail = _message_from_body(e.body)
        raise ProviderError(f"Anthropic answered with an error ({e.status_code})" +
                            (f": {detail}" if detail else "."))
    except anthropic.APIConnectionError:
        raise ProviderError("Couldn't reach Anthropic. Check your internet connection.")


def _anthropic_models(key):
    import anthropic

    client = anthropic.Anthropic(api_key=key, timeout=TIMEOUT, max_retries=1)
    return _anthropic_call(lambda: [m.id for m in client.models.list(limit=100)])


def list_models(provider, key=None):
    """Return the model ids the given key can use. Raises ProviderError with
    a message meant for the user when the key or connection fails."""
    if provider not in PROVIDERS:
        raise ProviderError("Unknown provider.")
    key = clean_key(key)
    if PROVIDERS[provider]["needs_key"] and not key:
        raise ProviderError("Paste an API key first.")

    if provider == "anthropic":
        return _anthropic_models(key)
    if provider == "openai":
        data = _get_json("https://api.openai.com/v1/models",
                         {"Authorization": f"Bearer {key}"})
        return sorted(m["id"] for m in data.get("data", []))
    if provider == "gemini":
        data = _get_json("https://generativelanguage.googleapis.com/v1beta/models",
                         {"x-goog-api-key": key})
        return sorted(m["name"].split("/", 1)[-1] for m in data.get("models", []))
    if provider == "ollama":
        data = _get_json(f"{OLLAMA_URL}/api/tags")
        return sorted(m["name"] for m in data.get("models", []))
    raise ProviderError("Unknown provider.")


# --------------------------------------------------------------------------
# Asking a model to do work
# --------------------------------------------------------------------------

def complete(provider, model, key, system, prompt, images=(), max_tokens=8000, usage=None):
    """Send one request and return the model's text reply.

    images is a sequence of (media_type, bytes) pairs shown to the model
    before the prompt. If usage is a dict, the tokens the provider reports
    are put in it as "input" and "output". Raises ProviderError with a
    message for the user."""
    if usage is None:
        usage = {}
    if provider not in PROVIDERS:
        raise ProviderError("Unknown provider.")
    key = clean_key(key)
    if PROVIDERS[provider]["needs_key"] and not key:
        raise ProviderError("No API key is saved for this provider. Add one in Settings.")
    model = model or PROVIDERS[provider]["default_model"]
    if not model:
        raise ProviderError("Choose a model in Settings first.")
    encoded = [(mt, base64.standard_b64encode(data).decode("ascii")) for mt, data in images]

    if provider == "anthropic":
        return _anthropic_complete(model, key, system, prompt, encoded, max_tokens, usage)
    if provider == "openai":
        content = [{"type": "image_url", "image_url": {"url": f"data:{mt};base64,{b64}"}}
                   for mt, b64 in encoded] + [{"type": "text", "text": prompt}]
        data = _get_json("https://api.openai.com/v1/chat/completions",
                         {"Authorization": f"Bearer {key}"},
                         {"model": model, "max_completion_tokens": max_tokens,
                          "messages": [{"role": "system", "content": system},
                                       {"role": "user", "content": content}]},
                         timeout=WORK_TIMEOUT)
        _note_usage(usage, data.get("usage"), "prompt_tokens", "completion_tokens")
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ProviderError("OpenAI sent back an answer Minerva couldn't read.")
    if provider == "gemini":
        parts = [{"inline_data": {"mime_type": mt, "data": b64}} for mt, b64 in encoded]
        parts.append({"text": prompt})
        data = _get_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            {"x-goog-api-key": key},
            {"system_instruction": {"parts": [{"text": system}]},
             "contents": [{"role": "user", "parts": parts}],
             "generationConfig": {"maxOutputTokens": max_tokens}},
            timeout=WORK_TIMEOUT)
        meta = data.get("usageMetadata") or {}
        _note_usage(usage, {"in": meta.get("promptTokenCount"),
                            "out": (meta.get("candidatesTokenCount") or 0) + (meta.get("thoughtsTokenCount") or 0)},
                    "in", "out")
        try:
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Gemini sent back an answer Minerva couldn't read.")
    if provider == "ollama":
        msg = {"role": "user", "content": prompt}
        if encoded:
            msg["images"] = [b64 for _mt, b64 in encoded]
        data = _get_json(f"{OLLAMA_URL}/api/chat", None,
                         {"model": model, "stream": False,
                          "messages": [{"role": "system", "content": system}, msg]},
                         timeout=WORK_TIMEOUT)
        _note_usage(usage, data, "prompt_eval_count", "eval_count")
        try:
            return data["message"]["content"]
        except (KeyError, TypeError):
            raise ProviderError("Ollama sent back an answer Minerva couldn't read.")
    raise ProviderError("Unknown provider.")


def _note_usage(usage, data, in_key, out_key):
    if isinstance(data, dict) and isinstance(data.get(in_key), int) and isinstance(data.get(out_key), int):
        usage.update({"input": data[in_key], "output": data[out_key]})


def _anthropic_complete(model, key, system, prompt, encoded, max_tokens, usage):
    import anthropic

    content = [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}}
               for mt, b64 in encoded]
    content.append({"type": "text", "text": prompt})
    client = anthropic.Anthropic(api_key=key, timeout=WORK_TIMEOUT, max_retries=3)

    def run():
        # Streamed so long answers don't hit request timeouts.
        with client.messages.stream(model=model, max_tokens=max_tokens, system=system,
                                    messages=[{"role": "user", "content": content}]) as stream:
            return stream.get_final_message()

    message = _anthropic_call(run)
    if message.usage:
        usage.update({"input": message.usage.input_tokens, "output": message.usage.output_tokens})
    if message.stop_reason == "refusal":
        raise ProviderError("The model declined to work on this.")
    return "".join(b.text for b in message.content if b.type == "text")
