"""
Nexus - Local LLM Interface Backend
Production FastAPI server
"""
import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from routers import chat, models, memory, research, skills, agents, search, system
from core.config import settings
from core.logger import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(" Nexus backend starting up...")
    # Startup tasks
    from core.memory_store import memory_store
    await memory_store.init()
    from core.skill_registry import skill_registry
    await skill_registry.load()
    logger.info("[OK] Nexus backend ready")
    yield
    logger.info(" Nexus backend shutting down...")


app = FastAPI(
    title="Nexus LLM Interface",
    description="Production backend for the Nexus local LLM interface",
    version="1.0.0",
    lifespan=lifespan,
)

# Middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(chat.router,     prefix="/api/chat",     tags=["Chat"])
app.include_router(models.router,   prefix="/api/models",   tags=["Models"])
app.include_router(memory.router,   prefix="/api/memory",   tags=["Memory"])
app.include_router(research.router, prefix="/api/research", tags=["Research"])
app.include_router(skills.router,   prefix="/api/skills",   tags=["Skills"])
app.include_router(agents.router,   prefix="/api/agents",   tags=["Agents"])
app.include_router(search.router,   prefix="/api/search",   tags=["Search"])
app.include_router(system.router,   prefix="/api/system",   tags=["System"])

# Serve frontend
import os
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0", "timestamp": time.time()}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=1,
        log_level="info",
        access_log=True,
    )
