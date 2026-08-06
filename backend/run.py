"""Entrypoint: python run.py

Serves the API and the built frontend from one origin, so there is no CORS
configuration anywhere in this project. In development, Vite proxies /api to this
same port — also same-origin from the browser's point of view.
"""

import sys
from pathlib import Path

# The db/ package lives at the repo root, one level above backend/. Put the root on
# the import path before anything else so `db.sqlite` and `db.vectordb` resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, jsonify, send_from_directory  # noqa: E402

from api import api_bp, fail  # noqa: E402
from config import settings  # noqa: E402
from db.sqlite.models import init_db  # noqa: E402
from observability.telemetry import log  # noqa: E402


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = settings.MAX_UPLOAD_MB * 1024 * 1024

    init_db()
    app.register_blueprint(api_bp, url_prefix="/api")

    dist = settings.FRONTEND_DIST

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def spa(path: str):
        """Serve the built SPA. Unknown paths fall through to index.html so client
        routes (/dashboard, /chat, …) survive a hard refresh."""
        if not dist.is_dir():
            return jsonify(
                {
                    "message": "API is running. Frontend not built.",
                    "hint": "cd frontend && npm run dev  (or npm run build to serve it here)",
                }
            )
        candidate = dist / path
        if path and candidate.is_file():
            return send_from_directory(dist, path)
        return send_from_directory(dist, "index.html")

    @app.errorhandler(413)
    def too_large(_):
        return fail("payload_too_large", f"Upload exceeds {settings.MAX_UPLOAD_MB}MB", 413)

    # Resolve the LLM provider once, at boot, so a bad hosted key surfaces here
    # rather than mid-demo.
    from ai.llm import resolve_provider

    provider = resolve_provider()
    log.info(
        "provider=%s chat=%s embed=%s retrieval=%s",
        provider["name"],
        settings.LLM_MODEL,
        settings.EMBEDDING_MODEL,
        settings.RETRIEVAL_MODE,
    )
    return app


if __name__ == "__main__":
    log.info("http://%s:%s", settings.HOST, settings.PORT)
    create_app().run(
        host=settings.HOST,
        port=settings.PORT,
        debug=settings.FLASK_DEBUG,
        use_reloader=False,
    )
