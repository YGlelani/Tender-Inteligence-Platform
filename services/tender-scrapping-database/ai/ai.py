"""Small client boundary for the self-hosted Ollama service."""

from __future__ import annotations

import os

import httpx


class AIServiceError(RuntimeError):
    """Raised when the local AI runtime cannot complete a request."""


class OllamaClient:
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")).rstrip("/")
        self.model = model or os.getenv("AI_MODEL", "llama3.2:3b")
        self.timeout = float(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "120"))

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    async def generate(self, prompt: str, system: str | None = None, json_response: bool = False) -> str:
        payload: dict[str, object] = {"model": self.model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        if json_response:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/generate", json=payload)
                response.raise_for_status()
                result = response.json()
        except httpx.HTTPError as error:
            raise AIServiceError("The local AI runtime is unavailable.") from error

        answer = result.get("response")
        if not isinstance(answer, str):
            raise AIServiceError("The local AI runtime returned an invalid response.")
        return answer
