"""
Chat router - streaming chat with memory injection, tool use, and conversation history
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.ollama_client import ollama
from core.memory_store import memory_store
from core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory conversation store (production: use Redis or SQLite)
_conversations: dict[str, list[dict]] = {}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: bool = True
    use_memory: bool = True
    use_web_search: bool = False
    system_prompt: Optional[str] = None


class ConversationRequest(BaseModel):
    conversation_id: str


# -- Stream chat ---------------------------------------------------------------

@router.post("/stream")
async def chat_stream(req: ChatRequest):
    """SSE streaming chat endpoint."""
    conv_id = req.conversation_id or str(uuid.uuid4())
    if conv_id not in _conversations:
        _conversations[conv_id] = []

    history = _conversations[conv_id]

    async def generate():
        # Memory injection
        memory_context = ""
        if req.use_memory:
            memories = await memory_store.search(req.message)
            if memories:
                memory_context = "Relevant memories:\n" + "\n".join(
                    [f"- [{m['type']}] {m['text']}" for m in memories]
                )

        # Web search injection
        search_context = ""
        if req.use_web_search:
            yield f"data: {json.dumps({'type': 'searching', 'message': 'Searching the web'})}\n\n"
            from core.search_engine import search_engine
            results = await search_engine.search(req.message, n=5)
            if results:
                search_context = "Web search results:\n" + "\n".join([
                    f"[{i+1}] {r['title']}: {r['snippet']}"
                    for i, r in enumerate(results[:5])
                ])

        # Build system prompt
        system_parts = []
        if req.system_prompt:
            system_parts.append(req.system_prompt)
        else:
            system_parts.append(
                "You are Nexus, a helpful local AI assistant. "
                "Be concise, accurate, and helpful."
            )
        if memory_context:
            system_parts.append(memory_context)
        if search_context:
            system_parts.append(search_context)
        system = "\n\n".join(system_parts)

        # Build messages
        messages = list(history) + [{"role": "user", "content": req.message}]

        # Send metadata
        yield f"data: {json.dumps({'type': 'meta', 'conversation_id': conv_id, 'model': req.model or settings.DEFAULT_MODEL})}\n\n"

        # Stream tokens
        full_response = ""
        start = time.time()
        token_count = 0

        try:
            stream_gen = await ollama.chat(
                messages=messages,
                model=req.model,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                system=system,
                stream=True,
            )
            async for token in stream_gen:
                full_response += token
                token_count += 1
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

        except Exception as e:
            error_msg = str(e)
            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
            return

        elapsed = round(time.time() - start, 2)
        tps = round(token_count / max(elapsed, 0.01), 1)

        # Update history
        history.append({"role": "user", "content": req.message})
        history.append({"role": "assistant", "content": full_response})

        # Keep last 20 turns
        if len(history) > 40:
            _conversations[conv_id] = history[-40:]

        # Auto-memorize in background
        if req.use_memory and full_response:
            asyncio.create_task(
                memory_store.extract_and_store(req.message, full_response)
            )

        # Done event
        yield f"data: {json.dumps({'type': 'done', 'tokens': token_count, 'elapsed_s': elapsed, 'tps': tps, 'conversation_id': conv_id})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# -- Non-streaming chat --------------------------------------------------------

@router.post("")
async def chat(req: ChatRequest):
    """Non-streaming chat - returns complete response."""
    conv_id = req.conversation_id or str(uuid.uuid4())
    if conv_id not in _conversations:
        _conversations[conv_id] = []

    history = _conversations[conv_id]
    memories = []
    if req.use_memory:
        memories = await memory_store.search(req.message)

    system = req.system_prompt or "You are Nexus, a helpful local AI assistant."
    if memories:
        system += "\n\nRelevant memories:\n" + "\n".join(
            [f"- [{m['type']}] {m['text']}" for m in memories]
        )

    messages = list(history) + [{"role": "user", "content": req.message}]

    try:
        result = await ollama.chat(
            messages=messages,
            model=req.model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            system=system,
            stream=False,
        )
        content = result["content"]

        history.append({"role": "user", "content": req.message})
        history.append({"role": "assistant", "content": content})
        if len(history) > 40:
            _conversations[conv_id] = history[-40:]

        if req.use_memory:
            asyncio.create_task(
                memory_store.extract_and_store(req.message, content)
            )

        return {
            "content": content,
            "conversation_id": conv_id,
            "model": result["model"],
            "tokens": result.get("completion_tokens", 0),
            "elapsed_s": result.get("duration_ms", 0) / 1000,
            "tps": result.get("tokens_per_sec", 0),
            "memories_used": len(memories),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


# -- Conversation management ---------------------------------------------------

@router.get("/conversations")
async def list_conversations():
    return {
        "conversations": [
            {
                "id": cid,
                "turns": len(h) // 2,
                "last_message": h[-2]["content"][:80] if len(h) >= 2 else "",
            }
            for cid, h in _conversations.items()
        ]
    }


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    if conv_id not in _conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation_id": conv_id, "messages": _conversations[conv_id]}


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    _conversations.pop(conv_id, None)
    return {"deleted": True}
