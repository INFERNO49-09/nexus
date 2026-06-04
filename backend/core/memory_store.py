"""
Persistent memory store - ChromaDB + tiered embeddings

Embedding priority (auto-selected at startup):
  1. Ollama (nomic-embed-text)     - best quality, needs `ollama pull nomic-embed-text`
  2. sentence-transformers          - good quality, ~90MB download (used if already cached)
  3. TF-IDF bag-of-words (offline) - always works, zero deps, zero network

Auto-detects and repairs dimension mismatches from prior runs.
Suppresses ChromaDB cache deserialization warnings.
"""
import json
import logging
import os
import re
import shutil
import uuid
import warnings
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

# Silence upstream noise before any imports
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
warnings.filterwarnings("ignore", message=".*[Cc]ache entry deserialization.*")
warnings.filterwarnings("ignore", message=".*Some weights of the model.*")
warnings.filterwarnings("ignore", category=UserWarning,  module="transformers")
warnings.filterwarnings("ignore", category=FutureWarning, module="transformers")
warnings.filterwarnings("ignore", category=UserWarning,  module="torch")

from core.config import settings

logger = logging.getLogger(__name__)


# -- Embedders -----------------------------------------------------------------

class TFIDFEmbedder:
    """
    Offline TF-IDF bag-of-words embedder.
    Real cosine similarity: 0.3-0.9 for related text, ~0.0 for unrelated.
    No downloads, no network, no GPU.
    """
    DIM = 8192

    @classmethod
    def embed(cls, text: str) -> list[float]:
        tokens = re.findall(r"[a-z]{2,}", text.lower())
        if not tokens:
            return [0.0] * cls.DIM
        counts = Counter(tokens)
        vec = np.zeros(cls.DIM, dtype=np.float32)
        total = len(tokens)
        for tok, cnt in counts.items():
            for seed in (0, 1):                               # two passes reduce collisions
                idx = (hash(tok) ^ (seed * 2654435761)) % cls.DIM
                vec[idx] += cnt / total
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec.tolist()


class OllamaEmbedder:
    """Ollama /api/embeddings - run `ollama pull nomic-embed-text` to activate."""
    MODEL = "nomic-embed-text"
    DIM   = 768
    _available: Optional[bool] = None

    async def probe(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.post(
                    f"{settings.OLLAMA_BASE_URL}/api/embeddings",
                    json={"model": self.MODEL, "prompt": "ping"},
                )
                self._available = r.status_code == 200 and "embedding" in r.json()
        except Exception:
            self._available = False
        return self._available

    async def embed(self, text: str) -> list[float]:
        import httpx
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                f"{settings.OLLAMA_BASE_URL}/api/embeddings",
                json={"model": self.MODEL, "prompt": text},
            )
            r.raise_for_status()
            return r.json()["embedding"]


class SentenceTransformerEmbedder:
    """sentence-transformers - only used when model is already cached locally."""
    DIM   = 384
    _model = None
    _tried = False

    def probe(self) -> bool:
        if self._tried:
            return self._model is not None
        self._tried = True
        try:
            cache = Path.home() / ".cache" / "huggingface" / "hub"
            cached = any(
                "all-MiniLM-L6-v2" in str(p)
                for p in cache.rglob("config.json")
            ) if cache.exists() else False
            if not cached:
                return False
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(
                    settings.EMBEDDING_MODEL, local_files_only=True
                )
            return True
        except Exception:
            return False

    def embed(self, text: str) -> list[float]:
        return self._model.encode(text, normalize_embeddings=True).tolist()


# -- MemoryStore ---------------------------------------------------------------

class MemoryStore:

    def __init__(self):
        self._client     = None
        self._collection = None
        self._ready      = False
        self._mode       = "none"
        self._dim        = 0
        self._ollama     = OllamaEmbedder()
        self._st         = SentenceTransformerEmbedder()
        self._db_path    = str(Path(settings.DATA_DIR) / "memory")

    # -- Init ------------------------------------------------------------------

    async def init(self):
        # Pick embedder first so we know the target dimension
        if await self._ollama.probe():
            self._mode = "ollama"
            self._dim  = OllamaEmbedder.DIM
            logger.info("[OK] Memory embedder: Ollama nomic-embed-text (dim=%d)", self._dim)
        elif self._st.probe():
            self._mode = "sentence-transformers"
            self._dim  = SentenceTransformerEmbedder.DIM
            logger.info("[OK] Memory embedder: sentence-transformers (dim=%d)", self._dim)
        else:
            self._mode = "tfidf"
            self._dim  = TFIDFEmbedder.DIM
            logger.info("[OK] Memory embedder: offline TF-IDF (dim=%d)", self._dim)

        await self._open_db()

    async def _open_db(self, retry: bool = True):
        """Open ChromaDB; auto-repair dimension mismatch by resetting the store."""
        try:
            import chromadb
            from chromadb.config import Settings as CS

            for lib in ("chromadb", "chromadb.segment", "chromadb.db",
                        "chromadb.telemetry", "hnswlib"):
                logging.getLogger(lib).setLevel(logging.ERROR)

            Path(self._db_path).mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=self._db_path,
                settings=CS(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name=settings.MEMORY_COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )

            # Dimension probe - write one entry and read it back
            probe_id = "__dim_probe__"
            probe_emb = await self._embed("probe")
            existing = self._collection.get(ids=[probe_id])
            if not existing["ids"]:
                self._collection.add(
                    ids=[probe_id],
                    embeddings=[probe_emb],
                    documents=["probe"],
                    metadatas=[{"type": "system"}],
                )
            else:
                # Verify existing dim matches
                try:
                    self._collection.query(
                        query_embeddings=[probe_emb], n_results=1
                    )
                except Exception as e:
                    if "dimension" in str(e).lower() and retry:
                        logger.warning(
                            "Embedding dimension mismatch detected - resetting memory store. "
                            "Old memories will be lost (they were built with a different model)."
                        )
                        shutil.rmtree(self._db_path, ignore_errors=True)
                        return await self._open_db(retry=False)
                    raise

            self._ready = True
            real_count = max(0, self._collection.count() - 1)  # exclude probe
            logger.info("Memory store ready - %d entries [%s]", real_count, self._mode)

        except Exception as e:
            logger.warning("Memory store unavailable: %s", e)
            self._ready = False

    # -- Embed -----------------------------------------------------------------

    async def _embed(self, text: str) -> list[float]:
        if self._mode == "ollama":
            try:
                return await self._ollama.embed(text)
            except Exception as e:
                logger.warning("Ollama embed failed, falling back to tfidf: %s", e)
                self._mode = "tfidf"
                self._dim  = TFIDFEmbedder.DIM

        if self._mode == "sentence-transformers":
            try:
                return self._st.embed(text)
            except Exception as e:
                logger.warning("ST embed failed, falling back to tfidf: %s", e)
                self._mode = "tfidf"
                self._dim  = TFIDFEmbedder.DIM

        return TFIDFEmbedder.embed(text)

    # -- Public API ------------------------------------------------------------

    async def add(
        self,
        text: str,
        memory_type: str = "ctx",
        source: str = "conversation",
        metadata: dict = None,
    ) -> str:
        if not self._ready:
            return ""
        try:
            entry_id = str(uuid.uuid4())
            meta = {
                "type":      memory_type,
                "source":    source,
                "timestamp": datetime.utcnow().isoformat(),
                "text":      text[:500],
                **(metadata or {}),
            }
            self._collection.add(
                ids=[entry_id],
                embeddings=[await self._embed(text)],
                documents=[text],
                metadatas=[meta],
            )
            return entry_id
        except Exception as e:
            logger.error("Memory add error: %s", e)
            return ""

    async def search(
        self,
        query: str,
        n_results: int = None,
        memory_type: str = None,
    ) -> list[dict]:
        if not self._ready:
            return []
        # Subtract 1 for the probe entry
        real_count = max(0, self._collection.count() - 1)
        if real_count == 0:
            return []
        try:
            n     = min(n_results or settings.MAX_MEMORY_RESULTS, real_count)
            where = {"type": memory_type} if memory_type else {"type": {"$ne": "system"}}
            results = self._collection.query(
                query_embeddings=[await self._embed(query)],
                n_results=max(1, n),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            memories = []
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                if meta.get("type") == "system":
                    continue
                relevance = round(1.0 - float(dist), 3)
                if relevance >= settings.MEMORY_RELEVANCE_THRESHOLD:
                    memories.append({
                        "text":      doc,
                        "type":      meta.get("type", "ctx"),
                        "source":    meta.get("source", ""),
                        "timestamp": meta.get("timestamp", ""),
                        "relevance": relevance,
                    })
            return sorted(memories, key=lambda x: x["relevance"], reverse=True)
        except Exception as e:
            logger.error("Memory search error: %s", e)
            return []

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[dict]:
        if not self._ready:
            return []
        try:
            results = self._collection.get(
                limit=limit + 1, offset=offset,
                include=["documents", "metadatas"],
            )
            entries = []
            for doc, meta in zip(results["documents"], results["metadatas"]):
                if meta.get("type") == "system":
                    continue
                entries.append({
                    "text":      doc,
                    "type":      meta.get("type", "ctx"),
                    "source":    meta.get("source", ""),
                    "timestamp": meta.get("timestamp", ""),
                })
            return sorted(entries, key=lambda x: x["timestamp"], reverse=True)[:limit]
        except Exception as e:
            logger.error("Memory list error: %s", e)
            return []

    async def delete(self, entry_id: str) -> bool:
        if not self._ready:
            return False
        try:
            self._collection.delete(ids=[entry_id])
            return True
        except Exception:
            return False

    async def count(self) -> int:
        if not self._ready:
            return 0
        return max(0, self._collection.count() - 1)

    async def stats(self) -> dict:
        if not self._ready:
            return {"available": False, "count": 0, "embedder": "none"}
        entries = await self.list_all(limit=2000)
        by_type: dict[str, int] = {}
        for e in entries:
            t = e["type"]
            by_type[t] = by_type.get(t, 0) + 1
        return {
            "available": True,
            "count":     len(entries),
            "by_type":   by_type,
            "embedder":  self._mode,
        }

    async def extract_and_store(self, user_msg: str, assistant_msg: str) -> list[str]:
        """Ask the LLM to extract memorable items from a conversation turn."""
        if not self._ready:
            return []
        try:
            from core.ollama_client import ollama
            prompt = (
                "Extract memorable facts, preferences, or context from this conversation.\n"
                "Return a JSON array of objects with keys:\n"
                '  "text"  - one sentence to remember\n'
                '  "type"  - one of: fact | pref | ctx | skill\n'
                "Max 3 items. Return [] if nothing worth remembering.\n\n"
                f"User: {user_msg[:400]}\n"
                f"Assistant: {assistant_msg[:400]}\n\n"
                "JSON array only:"
            )
            raw = await ollama.generate(prompt)
            text = raw.strip()
            s, e = text.find("["), text.rfind("]") + 1
            if s < 0 or e <= s:
                return []
            items = json.loads(text[s:e])
            ids = []
            for item in items[:3]:
                if isinstance(item, dict) and "text" in item:
                    eid = await self.add(
                        text=item["text"],
                        memory_type=item.get("type", "ctx"),
                        source="auto-extracted",
                    )
                    if eid:
                        ids.append(eid)
            return ids
        except Exception as e:
            logger.debug("Memory auto-extraction skipped: %s", e)
            return []


memory_store = MemoryStore()
