"""
System router - hardware info, Ollama status, settings management
"""
import logging
import os
import platform
import time
from fastapi import APIRouter
from core.ollama_client import ollama
from core.memory_store import memory_store
from core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()
_start_time = time.time()


@router.get("/status")
async def system_status():
    """Full system status - Ollama, memory, hardware."""
    ollama_ok = await ollama.is_available()
    mem_stats = await memory_store.stats()
    installed_models = await ollama.list_models() if ollama_ok else []
    running = await ollama.running_models() if ollama_ok else []

    return {
        "uptime_s": round(time.time() - _start_time),
        "version": "1.0.0",
        "ollama": {
            "available": ollama_ok,
            "url": settings.OLLAMA_BASE_URL,
            "models_installed": len(installed_models),
            "models_running": len(running),
            "running": running,
        },
        "memory": mem_stats,
        "settings": {
            "default_model": settings.DEFAULT_MODEL,
            "web_search": bool(settings.BRAVE_API_KEY or settings.SEARX_URL),
            "searx_url": settings.SEARX_URL,
            "brave_configured": bool(settings.BRAVE_API_KEY),
        },
        "platform": {
            "os": platform.system(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
    }


@router.get("/hardware")
async def hardware_info():
    """Detect GPU and recommend models."""
    info = {
        "cpu": {"count": os.cpu_count(), "model": platform.processor()},
        "gpu": [],
        "recommendations": [],
    }

    # Try nvidia-smi
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    total_mb = int(parts[1])
                    free_mb = int(parts[2])
                    info["gpu"].append({
                        "name": parts[0],
                        "vram_total_gb": round(total_mb / 1024, 1),
                        "vram_free_gb": round(free_mb / 1024, 1),
                        "vram_used_gb": round((total_mb - free_mb) / 1024, 1),
                        "vendor": "nvidia",
                    })
    except Exception:
        pass

    # Try rocm-smi (AMD)
    if not info["gpu"]:
        try:
            import subprocess
            result = subprocess.run(["rocm-smi", "--showmeminfo", "vram"],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                info["gpu"].append({"vendor": "amd", "raw": result.stdout[:200]})
        except Exception:
            pass

    # Model recommendations based on VRAM
    vram_gb = info["gpu"][0]["vram_free_gb"] if info["gpu"] else 0
    if vram_gb >= 24:
        info["recommendations"] = ["mixtral:8x7b", "llama3.1:70b", "qwen2.5:14b"]
    elif vram_gb >= 10:
        info["recommendations"] = ["mistral", "llama3.1:8b", "qwen2.5-coder:7b"]
    elif vram_gb >= 6:
        info["recommendations"] = ["mistral", "phi3.5", "tinyllama"]
    else:
        info["recommendations"] = ["tinyllama", "phi3.5"]

    return info


@router.get("/settings")
async def get_settings():
    return {
        "ollama_url": settings.OLLAMA_BASE_URL,
        "default_model": settings.DEFAULT_MODEL,
        "default_temperature": settings.DEFAULT_TEMPERATURE,
        "max_tokens": settings.DEFAULT_MAX_TOKENS,
        "searx_url": settings.SEARX_URL,
        "brave_configured": bool(settings.BRAVE_API_KEY),
        "memory_enabled": True,
        "embedding_model": settings.EMBEDDING_MODEL,
        "data_dir": settings.DATA_DIR,
    }
