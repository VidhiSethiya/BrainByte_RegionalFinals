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

# override=True: this project's .env is the single source of truth (see module
# docstring). Without it, python-dotenv leaves any pre-existing OS/session-level
# env var in place — on this machine an unrelated OPENAI_API_KEY was already set
# at the user level, silently shadowing the key configured here for the TCS
# genailab proxy and causing every hosted call to 401 with the wrong token.
load_dotenv(BACKEND_DIR / ".env", override=True)


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
    LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.2-3b-it:latest")       # standard tier
    FAST_LLM_MODEL = os.getenv("FAST_LLM_MODEL", LLM_MODEL)
    # Hosted embedding default — changing this invalidates Chroma; reseed after swap.
    EMBEDDING_MODEL = os.getenv(
        "EMBEDDING_MODEL", "azure/genailab-maas-text-embedding-3-large"
    )
    # Vision-capable model for images / scanned pages. Empty disables the vision path.
    VISION_MODEL = os.getenv("VISION_MODEL", "").strip()
    REASONING_MODEL = os.getenv("REASONING_MODEL", "").strip()
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "").strip()
    # What ai/llm.py actually requests for every tier once resolve_provider() has
    # fallen back to local — LLM_MODEL/FAST_LLM_MODEL/REASONING_MODEL/EMBEDDING_MODEL
    # above may hold hosted-only ids (azure/genailab-maas-...) that don't exist on a
    # local Ollama daemon and would 404 rather than gracefully degrade.
    LOCAL_CHAT_MODEL = os.getenv("LOCAL_CHAT_MODEL", "llama-3.2-3b-it:latest")
    LOCAL_EMBEDDING_MODEL = os.getenv("LOCAL_EMBEDDING_MODEL", "gte-large:latest")
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
    # TicketSphere: hybrid is the earned default — INC/error codes need BM25.
    # "vector" remains available for A/B; set winner in .env after eval.
    RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "hybrid").strip().lower()
    TICKET_SOURCE = os.getenv("TICKET_SOURCE", "synthetic").strip().lower()
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

    # --- domain (TicketSphere) ---
    DOMAIN = os.getenv("DOMAIN", "TicketSphere")
    ROLES = ["admin", "manager", "engineer", "viewer"]
    TEAMS = ["ops", "azure", "aws", "gcp"]

    # --- ticket source: Jira integration (backend/integrations/) ---
    # "synthetic" (default) reads db/vectordb/data/seed/tickets/*.json and never
    # calls out anywhere — the safe default and the offline fallback. "jira"
    # requires the four JIRA_* values below. Poll-based sync is primary; see
    # backend/integrations/jira.py's module docstring for why.
    JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
    JIRA_EMAIL = os.getenv("JIRA_EMAIL", "").strip()
    JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "").strip()
    JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "SCRUM").strip()
    JIRA_POLL_SECONDS = _int("JIRA_POLL_SECONDS", 30)
    # Per-site custom field ids (customfield_10xxx) — cannot be guessed from
    # documentation. Empty means "don't write that field" rather than a wrong
    # guess landing quietly in the wrong place. Confirm the real ids against the
    # board (Project settings -> Fields, or GET /rest/api/3/issue/<key>?expand=names)
    # and set these once you have access.
    JIRA_FIELD_SEVERITY = os.getenv("JIRA_FIELD_SEVERITY", "").strip()
    JIRA_FIELD_PRIORITY_SCORE = os.getenv("JIRA_FIELD_PRIORITY_SCORE", "").strip()
    JIRA_FIELD_ROUTED_TEAM = os.getenv("JIRA_FIELD_ROUTED_TEAM", "").strip()
    JIRA_FIELD_AI_CONFIDENCE = os.getenv("JIRA_FIELD_AI_CONFIDENCE", "").strip()

    def ensure_dirs(self) -> None:
        for d in (SQLITE_DIR, VECTOR_DIR, self.CHROMA_PERSIST_DIR, self.UPLOAD_DIR, self.SEED_DIR):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
