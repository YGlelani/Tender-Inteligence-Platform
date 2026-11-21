"""
The LLM layer.

Wraps the Azure AI deployment (Mistral) in a LangChain `ChatOpenAI` object so
the rest of the app can treat it as a standard chat model.

Azure exposes models under several URL styles depending on how the deployment
was created, and AZURE_AI_ENDPOINT may be given with or without a path:

  - OpenAI-compatible v1:     https://<res>.services.ai.azure.com/openai/v1/
  - Azure AI model inference: https://<res>.services.ai.azure.com/models?api-version=…
  - Serverless (MaaS):        https://<name>.<region>.models.ai.azure.com/v1/
  - Azure OpenAI deployment:  https://<res>.openai.azure.com/openai/deployments/<name>/

Instead of assuming one, `resolve_llm_target()` sends a tiny test request to each
style and keeps the first that answers. `llm_status()` reports what worked, or why
each style failed, for /health.
"""
import logging
import os
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlsplit

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

MODEL_INFERENCE_API_VERSION = os.getenv("AZURE_AI_API_VERSION", "2024-05-01-preview")
AZURE_OPENAI_API_VERSION = "2024-10-21"
RETRY_FAILED_AFTER = 60  # seconds before re-probing a failed connection
PROBE_TIMEOUT = 8        # seconds per URL style tried; a healthy endpoint answers in ~1s


@dataclass(frozen=True)
class Target:
    mode: str
    base_url: str
    query: tuple = ()  # default query params, e.g. (("api-version", "…"),)


@dataclass
class _State:
    target: Target | None = None
    ok: bool = False
    checked_at: float = 0.0
    attempts: list = field(default_factory=list)


_state = _State()
_clients: dict[tuple, ChatOpenAI] = {}


def _configured() -> bool:
    return all([settings.azure_ai_endpoint, settings.azure_ai_deployment, settings.azure_ai_api_key])


def _candidates(endpoint: str | None = None, deployment: str | None = None) -> list[Target]:
    """Every URL style Azure might serve `deployment` under (defaults: the chat model)."""
    deployment = deployment or settings.azure_ai_deployment
    parsed = urlsplit((endpoint or settings.azure_ai_endpoint).strip())
    root = f"{parsed.scheme or 'https'}://{parsed.netloc or parsed.path.split('/')[0]}"
    path = parsed.path.rstrip("/") if parsed.netloc else ""
    for suffix in ("/chat/completions", "/completions"):  # pasted full operation URLs
        if path.endswith(suffix):
            path = path[: -len(suffix)]
    query = dict(parse_qsl(parsed.query))

    out: list[Target] = []
    if path:
        q = dict(query)
        if path.endswith("/models") and "api-version" not in q:
            q["api-version"] = MODEL_INFERENCE_API_VERSION
        out.append(Target("as configured", root + path + "/", tuple(sorted(q.items()))))
    out += [
        Target("openai-v1", root + "/openai/v1/"),
        Target("model-inference", root + "/models/",
               (("api-version", query.get("api-version", MODEL_INFERENCE_API_VERSION)),)),
        Target("serverless-v1", root + "/v1/"),
        Target("serverless", root + "/"),
        Target("azure-openai-deployment", f"{root}/openai/deployments/{deployment}/",
               (("api-version", AZURE_OPENAI_API_VERSION),)),
    ]
    seen, unique = set(), []
    for t in out:
        if (t.base_url, t.query) not in seen:
            seen.add((t.base_url, t.query))
            unique.append(t)
    return unique


def _headers() -> dict:
    # Azure accepts either header depending on the endpoint style; send both.
    return {"api-key": settings.azure_ai_api_key}


async def _probe(client: httpx.AsyncClient, target: Target) -> dict:
    try:
        resp = await client.post(
            target.base_url + "chat/completions",
            params=dict(target.query),
            headers={**_headers(), "Authorization": f"Bearer {settings.azure_ai_api_key}"},
            json={
                "model": settings.azure_ai_deployment,
                "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                "max_tokens": 5,
                "temperature": 0,
            },
        )
    except httpx.HTTPError as e:
        return {"mode": target.mode, "ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
    if resp.status_code == 200:
        return {"mode": target.mode, "ok": True, "status": 200}
    try:
        err = resp.json().get("error", resp.text)
        err = err.get("message") or err.get("code") if isinstance(err, dict) else err
    except ValueError:
        err = resp.text
    return {"mode": target.mode, "ok": False, "status": resp.status_code, "error": str(err)[:200]}


async def resolve_llm_target(force: bool = False) -> bool:
    """Find the URL style that works for this Azure deployment. Returns True when connected."""
    if not _configured():
        _state.attempts = [{"ok": False, "error": "AZURE_AI_ENDPOINT, AZURE_AI_DEPLOYMENT or AZURE_AI_API_KEY is not set"}]
        _state.checked_at = time.time()
        return False
    if not force and _state.ok:
        return True
    if not force and _state.checked_at and time.time() - _state.checked_at < RETRY_FAILED_AFTER:
        return False

    attempts = []
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
        for target in _candidates():
            result = await _probe(client, target)
            attempts.append(result)
            if result["ok"]:
                _state.target, _state.ok = target, True
                break
    _state.attempts, _state.checked_at = attempts, time.time()

    if _state.ok:
        logger.info("Azure AI connected: deployment=%s mode=%s base_url=%s",
                    settings.azure_ai_deployment, _state.target.mode, _state.target.base_url)
    else:
        logger.error("Azure AI unreachable for deployment %s. Tried: %s",
                     settings.azure_ai_deployment,
                     "; ".join(f"{a['mode']} -> {a.get('status', '')} {a.get('error', '')}".strip() for a in attempts))
    return _state.ok


def current_target() -> Target:
    return _state.target or _candidates()[0]


def azure_base_url() -> str:
    return current_target().base_url


def client_kwargs() -> dict:
    """Connection settings for any OpenAI-compatible client (LangChain or the openai SDK)."""
    target = current_target()
    return {
        "base_url": target.base_url,
        "api_key": settings.azure_ai_api_key,
        "default_headers": _headers(),
        "default_query": dict(target.query) or None,
    }


def _client(deployment: str, temperature: float, timeout: float | None = None) -> ChatOpenAI:
    if not _configured():
        raise RuntimeError("Missing AZURE_AI_ENDPOINT, AZURE_AI_DEPLOYMENT, or AZURE_AI_API_KEY environment variables.")
    timeout = timeout or settings.llm_timeout
    key = (current_target(), deployment, temperature, timeout)
    if key not in _clients:
        # disable_streaming: replies are returned whole, and streamed tool calls through
        # Azure endpoints are a common source of "No generation chunks were returned".
        # Short timeout + one retry: a hung chat request fails in ~1 min instead of ~4.5 min.
        _clients[key] = ChatOpenAI(model=deployment, temperature=temperature, max_retries=1,
                                   timeout=timeout,
                                   disable_streaming=True, **client_kwargs())
    return _clients[key]


# Reading a whole document runs in the background and legitimately takes longer than a chat reply.
DOCUMENT_TIMEOUT = 90


def get_llm(timeout: float | None = None) -> ChatOpenAI:
    """ChatOpenAI pointed at the Azure deployment (reused across requests)."""
    return _client(settings.azure_ai_deployment, settings.azure_ai_temperature, timeout)


def get_vision_llm() -> ChatOpenAI:
    """Model used for scanned PDFs and photos of documents."""
    return _client(settings.azure_ai_vision_deployment, 0, DOCUMENT_TIMEOUT)


async def llm_status() -> dict:
    """Connection report for /health (no secrets)."""
    await resolve_llm_target()
    target = _state.target
    return {
        "ok": _state.ok,
        "deployment": settings.azure_ai_deployment or None,
        "endpoint_host": urlsplit(settings.azure_ai_endpoint).netloc or None,
        "mode": target.mode if _state.ok else None,
        "attempts": [] if _state.ok else _state.attempts,
    }


async def is_azure_available() -> bool:
    return await resolve_llm_target()


async def generate(prompt: str, system: str | None = None) -> str:
    """One-shot generation: send a prompt, get text back."""
    await resolve_llm_target()
    messages = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=prompt))
    response = await get_llm().ainvoke(messages)
    return response.content
