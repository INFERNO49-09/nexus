"""
Models router - manage Ollama models (list, pull, delete, info, running)
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.ollama_client import ollama

logger = logging.getLogger(__name__)
router = APIRouter()

# Curated catalog with hardware metadata
MODEL_CATALOG = [
    {"name": "mistral", "display": "Mistral-7B-Instruct-v0.3", "provider": "Mistral AI",
     "params": "7B", "ctx": "32k", "size_gb": 4.1, "tags": ["GPU", "FAST", "REC"],
     "category": "chat", "desc": "Best all-round chat model. Fast on consumer GPUs. Excellent instruction following."},
    {"name": "llama3.1:8b", "display": "Llama-3.1-8B-Instruct", "provider": "Meta",
     "params": "8B", "ctx": "128k", "size_gb": 4.7, "tags": ["GPU", "REC"],
     "category": "chat", "desc": "Meta flagship 8B. Long context, strong reasoning, open weights."},
    {"name": "qwen2.5-coder:7b", "display": "Qwen2.5-Coder-7B-Instruct", "provider": "Alibaba",
     "params": "7B", "ctx": "128k", "size_gb": 4.3, "tags": ["GPU", "CODE"],
     "category": "code", "desc": "Top-tier code model. Beats Codellama 34B on many benchmarks."},
    {"name": "phi3.5", "display": "Phi-3.5-Mini-Instruct", "provider": "Microsoft",
     "params": "3.8B", "ctx": "128k", "size_gb": 2.2, "tags": ["CPU", "FAST"],
     "category": "chat", "desc": "Runs on CPU. Surprisingly capable for its tiny size."},
    {"name": "deepseek-r1:7b", "display": "DeepSeek-R1-Distill-7B", "provider": "DeepSeek",
     "params": "7B", "ctx": "32k", "size_gb": 4.5, "tags": ["GPU", "REASON"],
     "category": "reasoning", "desc": "Distilled reasoning model with chain-of-thought."},
    {"name": "llava:7b", "display": "LLaVA-1.6-Mistral-7B", "provider": "LLaVA Team",
     "params": "7B", "ctx": "4k", "size_gb": 5.1, "tags": ["GPU", "VISION"],
     "category": "vision", "desc": "Multimodal: chat about images and documents."},
    {"name": "codellama:13b", "display": "CodeLlama-13B-Instruct", "provider": "Meta",
     "params": "13B", "ctx": "16k", "size_gb": 7.8, "tags": ["GPU", "CODE"],
     "category": "code", "desc": "Strong code completion and generation in 80+ languages."},
    {"name": "gemma2:9b", "display": "Gemma-2-9B-Instruct", "provider": "Google",
     "params": "9B", "ctx": "8k", "size_gb": 5.4, "tags": ["GPU"],
     "category": "chat", "desc": "Google latest open model. Excellent knowledge and clean outputs."},
    {"name": "qwen2.5:14b", "display": "Qwen2.5-14B-Instruct", "provider": "Alibaba",
     "params": "14B", "ctx": "128k", "size_gb": 8.9, "tags": ["GPU", "REASON"],
     "category": "reasoning", "desc": "High capability with strong multilingual and reasoning skills."},
    {"name": "mixtral:8x7b", "display": "Mixtral-8x7B-Instruct", "provider": "Mistral AI",
     "params": "46.7B MoE", "ctx": "32k", "size_gb": 26.0, "tags": ["GPU"],
     "category": "chat", "desc": "Mixture of Experts. Near-GPT-4 quality on consumer hardware."},
    {"name": "tinyllama", "display": "TinyLlama-1.1B-Chat", "provider": "Community",
     "params": "1.1B", "ctx": "2k", "size_gb": 0.6, "tags": ["CPU", "FAST"],
     "category": "chat", "desc": "Runs on anything including Raspberry Pi and old laptops."},
    {"name": "llama3.1:70b", "display": "Llama-3.1-70B-Instruct", "provider": "Meta",
     "params": "70B", "ctx": "128k", "size_gb": 39.0, "tags": ["GPU"],
     "category": "chat", "desc": "Near-frontier quality. Requires multi-GPU or high VRAM setup."},
    {"name": "deepseek-r1:14b", "display": "DeepSeek-R1-14B", "provider": "DeepSeek",
     "params": "14B", "ctx": "32k", "size_gb": 9.0, "tags": ["GPU", "REASON"],
     "category": "reasoning", "desc": "Larger reasoning model with improved chain-of-thought."},
    {"name": "nomic-embed-text", "display": "Nomic Embed Text", "provider": "Nomic AI",
     "params": "137M", "ctx": "8k", "size_gb": 0.3, "tags": ["CPU", "EMBED"],
     "category": "embedding", "desc": "Fast text embeddings for RAG and semantic search."},
    {"name": "neural-chat:7b", "display": "Neural Chat 7B", "provider": "Intel",
     "params": "7B", "ctx": "8k", "size_gb": 4.1, "tags": ["GPU"],
     "category": "chat", "desc": "Intel fine-tuned Mistral. Optimized for conversational AI."},
]


class PullRequest(BaseModel):
    model_name: str


class DeleteRequest(BaseModel):
    model_name: str


@router.get("")
async def list_models():
    """List all locally installed models plus catalog."""
    installed = await ollama.list_models()
    installed_names = {m["name"].split(":")[0] for m in installed}

    # Merge catalog with installed status
    catalog = []
    for m in MODEL_CATALOG:
        base = m["name"].split(":")[0]
        installed_match = next(
            (i for i in installed if i["name"].split(":")[0] == base), None
        )
        catalog.append({
            **m,
            "installed": installed_match is not None,
            "installed_size": installed_match["size_gb"] if installed_match else None,
        })

    # Add any installed models not in catalog
    for inst in installed:
        base = inst["name"].split(":")[0]
        if not any(m["name"].split(":")[0] == base for m in MODEL_CATALOG):
            catalog.append({
                "name": inst["name"],
                "display": inst["name"],
                "provider": "Unknown",
                "params": "?",
                "ctx": "?",
                "size_gb": inst["size_gb"],
                "tags": [],
                "category": "chat",
                "desc": "Locally installed model",
                "installed": True,
            })

    return {
        "catalog": catalog,
        "installed": installed,
        "total_catalog": len(catalog),
        "total_installed": len(installed),
    }


@router.get("/running")
async def running_models():
    return {"models": await ollama.running_models()}


@router.get("/info/{model_name}")
async def model_info(model_name: str):
    info = await ollama.model_info(model_name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")
    return info


@router.post("/pull")
async def pull_model(req: PullRequest):
    """Stream model download progress via SSE."""
    async def stream_pull():
        try:
            async for progress in ollama.pull_model(req.model_name):
                yield f"data: {json.dumps(progress)}\n\n"
            yield f"data: {json.dumps({'status': 'success', 'model': req.model_name})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(stream_pull(), media_type="text/event-stream")


@router.delete("/{model_name}")
async def delete_model(model_name: str):
    success = await ollama.delete_model(model_name)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to delete '{model_name}'")
    return {"deleted": True, "model": model_name}


@router.get("/status")
async def ollama_status():
    available = await ollama.is_available()
    models = await ollama.list_models() if available else []
    return {
        "ollama_available": available,
        "model_count": len(models),
        "ollama_url": ollama.base_url,
    }
