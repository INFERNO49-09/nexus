"""
Ollama client - wraps the Ollama REST API with streaming, retries, and model management
"""
import asyncio
import json
import logging
from typing import AsyncGenerator, Optional
import httpx
from core.config import settings

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.timeout = settings.OLLAMA_TIMEOUT

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
        )

    # -- Chat ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict],
        model: str = None,
        temperature: float = None,
        max_tokens: int = None,
        system: str = None,
        stream: bool = False,
    ) -> dict | AsyncGenerator:
        model = model or settings.DEFAULT_MODEL
        temperature = temperature if temperature is not None else settings.DEFAULT_TEMPERATURE
        max_tokens = max_tokens or settings.DEFAULT_MAX_TOKENS

        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system

        if stream:
            return self._stream_chat(payload)
        else:
            return await self._blocking_chat(payload)

    async def _blocking_chat(self, payload: dict) -> dict:
        async with self._client() as client:
            try:
                resp = await client.post("/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return {
                    "content": data["message"]["content"],
                    "model": data.get("model", payload["model"]),
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
                    "duration_ms": round(data.get("total_duration", 0) / 1e6, 1),
                    "tokens_per_sec": round(
                        data.get("eval_count", 0)
                        / max(data.get("eval_duration", 1) / 1e9, 0.001),
                        1,
                    ),
                }
            except httpx.ConnectError:
                raise RuntimeError("Cannot connect to Ollama. Is it running? Try: ollama serve")
            except httpx.HTTPStatusError as e:
                raise RuntimeError(f"Ollama error {e.response.status_code}: {e.response.text}")

    async def _stream_chat(self, payload: dict) -> AsyncGenerator[str, None]:
        async with self._client() as client:
            try:
                async with client.stream("POST", "/api/chat", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                yield token
                            if chunk.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue
            except httpx.ConnectError:
                yield "\n\n Cannot connect to Ollama. Run: `ollama serve`"

    # -- Generate (single prompt, no history) ---------------------------------

    async def generate(self, prompt: str, model: str = None, stream: bool = False) -> str:
        result = await self.chat(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            stream=False,
        )
        return result["content"]

    # -- Models ----------------------------------------------------------------

    async def list_models(self) -> list[dict]:
        async with self._client() as client:
            try:
                resp = await client.get("/api/tags")
                resp.raise_for_status()
                models = resp.json().get("models", [])
                return [
                    {
                        "name": m["name"],
                        "size_gb": round(m.get("size", 0) / 1e9, 1),
                        "modified_at": m.get("modified_at", ""),
                        "digest": m.get("digest", "")[:12],
                    }
                    for m in models
                ]
            except httpx.ConnectError:
                return []

    async def pull_model(self, model_name: str) -> AsyncGenerator[str, None]:
        payload = {"name": model_name, "stream": True}
        async with self._client() as client:
            async with client.stream("POST", "/api/pull", json=payload,
                                     timeout=httpx.Timeout(3600)) as resp:
                async for line in resp.aiter_lines():
                    if line.strip():
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            pass

    async def delete_model(self, model_name: str) -> bool:
        async with self._client() as client:
            resp = await client.request("DELETE", "/api/delete",
                                        json={"name": model_name})
            return resp.status_code == 200

    async def model_info(self, model_name: str) -> dict:
        async with self._client() as client:
            try:
                resp = await client.post("/api/show", json={"name": model_name})
                resp.raise_for_status()
                return resp.json()
            except Exception:
                return {}

    async def is_available(self) -> bool:
        try:
            async with self._client() as client:
                resp = await client.get("/api/tags", timeout=3)
                return resp.status_code == 200
        except Exception:
            return False

    async def running_models(self) -> list[dict]:
        async with self._client() as client:
            try:
                resp = await client.get("/api/ps")
                resp.raise_for_status()
                return resp.json().get("models", [])
            except Exception:
                return []


ollama = OllamaClient()
