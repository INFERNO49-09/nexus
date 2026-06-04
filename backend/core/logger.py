"""
Structured logging for Nexus
"""
import logging
import sys
from pathlib import Path
from core.config import settings


def setup_logging():
    log_dir = Path(settings.DATA_DIR) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_dir / "nexus.log", encoding="utf-8"),
    ]

    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format=fmt,
        datefmt=datefmt,
        handlers=handlers,
    )

    # Quiet noisy libraries
    for lib in ["httpx", "httpcore", "chromadb", "sentence_transformers"]:
        logging.getLogger(lib).setLevel(logging.WARNING)
