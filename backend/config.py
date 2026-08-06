"""Single source of truth for configuration.

No other module may call os.getenv. Import `settings` from here instead.

Persistent state is split by store, matching the db/ package layout:
    db/sqlite/data/     app.db
    db/vectordb/data/   chroma/, uploads/, seed/
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
SQLITE_DIR = REPO_ROOT / "db" / "sqlite" / "data"
VECTOR_DIR = REPO_ROOT / "db" / "vectordb" / "data"

load_dotenv(BACKEND_DIR / ".env")


def _bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _path(key: str, default: str, base: Path) -> Path:
    p = Path(os.getenv(key, default))
    return p if p.is_absolute() else (base / p).resolve()


class Settings:
    # --- llm ---
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "local").strip().lower()
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "ollama")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.2-3b-it:latest")
    FAST_LLM_MODEL = os.getenv("FAST_LLM_MODEL", LLM_MODEL)
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gte-large:latest")
    # Vision-capable model for images / scanned pages. Empty disables the vision path.
    VISION_MODEL = os.getenv("VISION_MODEL", "").strip()
    LLM_TEMPERATURE = _float("LLM_TEMPERATURE", 0.1)
    LLM_TIMEOUT_SECONDS = _int("LLM_TIMEOUT_SECONDS", 60)
    LLM_MAX_RETRIES = _int("LLM_MAX_RETRIES", 1)

    # Local fallback target, used when a hosted provider fails its startup probe.
    LOCAL_BASE_URL = "http://localhost:11434/v1"
    LOCAL_API_KEY = "ollama"

    # TLS verification. Off by default: local Ollama is plain http, and corporate
    # TLS-inspecting proxies break certificate validation on hosted endpoints.
    DISABLE_SSL_VERIFY = _bool("DISABLE_SSL_VERIFY", True)

    # --- storage: relational (db/sqlite/data/) ---
    SQLITE_PATH = SQLITE_DIR / "app.db"
    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{SQLITE_PATH.as_posix()}")

    # --- storage: vectors and their source documents (db/vectordb/data/) ---
    CHROMA_PERSIST_DIR = _path("CHROMA_PERSIST_DIR", "chroma", VECTOR_DIR)
    CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "knowledge_base")
    UPLOAD_DIR = _path("UPLOAD_DIR", "uploads", VECTOR_DIR)
    SEED_DIR = _path("SEED_DIR", "seed", VECTOR_DIR)

    # --- retrieval ---
    # "vector" = embedding similarity only (the default).
    # "hybrid" = vector + BM25 keyword, fused with RRF, then optionally reranked.
    # Decide on build day: hybrid earns its keep only when the corpus carries exact
    # identifiers (contract/policy/part numbers) that embeddings blur.
    RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "vector").strip().lower()
    CHUNK_SIZE = _int("CHUNK_SIZE", 900)
    CHUNK_OVERLAP = _int("CHUNK_OVERLAP", 150)
    RETRIEVE_TOP_K = _int("RETRIEVE_TOP_K", 20)
    FINAL_TOP_K = _int("FINAL_TOP_K", 6)
    RRF_K = _int("RRF_K", 60)
    RERANK_ENABLED = _bool("RERANK_ENABLED", False)
    RERANK_MODEL = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

    # --- auth ---
    JWT_SECRET = os.getenv("JWT_SECRET", "change-me-before-demo")
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRY_HOURS = _int("JWT_EXPIRY_HOURS", 12)

    # --- limits ---
    RATE_LIMIT_PER_MINUTE = _int("RATE_LIMIT_PER_MINUTE", 60)
    MAX_PARALLEL_WORKERS = _int("MAX_PARALLEL_WORKERS", 4)
    MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 25)

    # --- app ---
    # One host for both tiers, so there is no CORS story at all. Flask serves the
    # built frontend from frontend/dist; in dev, Vite proxies /api to this port.
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = _int("PORT", 5000)
    FLASK_DEBUG = _bool("FLASK_DEBUG", True)
    FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

    # --- domain (filled by the guide-me blueprint) ---
    DOMAIN = os.getenv("DOMAIN", "[DOMAIN]")
    ROLES = ["admin", "analyst", "viewer"]  # [PLACEHOLDER: DOMAIN_ROLES]

    def ensure_dirs(self) -> None:
        for d in (SQLITE_DIR, VECTOR_DIR, self.CHROMA_PERSIST_DIR, self.UPLOAD_DIR, self.SEED_DIR):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
