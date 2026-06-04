"""
Nexus Configuration - reads from .env or environment variables
"""
import os
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"

    # Ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_TIMEOUT: int = 120
    DEFAULT_MODEL: str = "mistral"
    DEFAULT_TEMPERATURE: float = 0.7
    DEFAULT_MAX_TOKENS: int = 2048

    # Memory
    DATA_DIR: str = str(Path.home() / ".nexus")
    MEMORY_COLLECTION: str = "nexus_memory"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    MAX_MEMORY_RESULTS: int = 5
    MEMORY_RELEVANCE_THRESHOLD: float = 0.25   # lower for hash embedder

    # Web Search
    SEARX_URL: str = "http://localhost:8080"
    BRAVE_API_KEY: str = ""
    JINA_BASE_URL: str = "https://r.jina.ai"
    MAX_SEARCH_RESULTS: int = 8
    SEARCH_TIMEOUT: int = 10

    # Research
    DEFAULT_RESEARCH_DEPTH: int = 15
    MAX_RESEARCH_SOURCES: int = 40

    # Agents
    MAX_AGENT_STEPS: int = 20
    AGENT_TIMEOUT: int = 300

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 60


settings = Settings()

# Ensure data directories exist
for subdir in ["memory", "skills", "research", "uploads", "logs"]:
    Path(settings.DATA_DIR).joinpath(subdir).mkdir(parents=True, exist_ok=True)
