"""Smoke-test chatbot HTTP APIs (sessions, memory, greetings, tickets).

Prereq: backend running on :5000
  cd backend
  .\\.venv\\Scripts\\activate
  python run.py

Usage:
  python smoke_chatbot_apis.py
  python smoke_chatbot_apis.py --base http://127.0.0.1:5000
  python smoke_chatbot_apis.py --allow-blocked

Exit 0 = all passed; 1 = failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:5000"
USER = "admin"
PASSWORD = "admin123"
TIMEOUT_S = 180


class Failed(Exception):
    pass


def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = TIMEOUT_S,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") or "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"error": {"message": raw}}
        return exc.code, payload
    except urllib.error.URLError as exc:
        raise Failed(f"connection error for {method} {url}: {exc}") from exc


def expect_ok(name: str, status: int, payload: dict) -> Any:
    if status >= 400 or "error" in payload:
        err = payload.get("error") or payload
        raise Failed(f"{name}: HTTP {status} -> {err}")
    if "data" not in payload:
        raise Failed(f"{name}: missing 'data' envelope: {payload}")
    print(f"  PASS  {name}")
    return payload["data"]


def expect_status(name: str, status: int, payload: dict, want: int) -> Any:
    if status != want:
        raise Failed(f"{name}: expected HTTP {want}, got {status} -> {payload}")
    print(f"  PASS  {name}")
    return payload.get("data")


def assert_chat_ok(name: str, data: dict, *, allow_blocked: bool) -> None:
    if not data.get("session_id"):
        raise Failed(f"{name}: missing session_id")
    if not data.get("answer"):
        raise Failed(f"{name}: empty answer: {data}")
    if data.get("blocked") and not allow_blocked:
        raise Failed(
            f"{name}: blocked ({data.get('blocked_reason')}) answer={data.get('answer')!r}. "
            "Check OPENAI_API_KEY / Ollama, or re-run with --allow-blocked."
        )
    preview = (data.get("answer") or "").replace("\n", " ")[:140]
    print(f"         answer: {preview}")
    if data.get("blocked"):
        print(f"         warn: blocked={data.get('blocked_reason')}")


def run(base: str, allow_blocked: bool) -> None:
    base = base.rstrip("/")
    print(f"\nChatbot API smoke test -> {base}\n")
    failures: list[str] = []

    def check(label: str, fn):
        try:
            fn()
        except Failed as exc:
            print(f"  FAIL  {label}: {exc}")
            failures.append(str(exc))
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {label}: unexpected {exc}")
            failures.append(f"{label}: {exc}")

    # --- health / login -----------------------------------------------------
    def t_health():
        status, payload = _request("GET", f"{base}/api/health", timeout=10)
        data = expect_ok("GET /api/health", status, payload)
        if data.get("status") != "ok":
            raise Failed(f"health status not ok: {data}")
        print(f"         provider={data.get('provider')} chunks={data.get('indexed_chunks')}")

    check("health", t_health)

    token_holder: dict[str, str] = {}

    def t_login():
        status, payload = _request(
            "POST",
            f"{base}/api/auth/login",
            body={"username": USER, "password": PASSWORD},
            timeout=15,
        )
        data = expect_ok("POST /api/auth/login", status, payload)
        token = data.get("token")
        if not token:
            raise Failed(f"login returned no token: {data}")
        token_holder["token"] = token

    check("login", t_login)
    token = token_holder.get("token")
    if not token:
        print("\nAborting: no auth token.")
        sys.exit(1)

    # Reset drawer so greeting/memory tests are clean
    def t_reset():
        status, payload = _request(
            "DELETE", f"{base}/api/chatbot/history", token=token, timeout=15
        )
        expect_ok("DELETE /api/chatbot/history (setup)", status, payload)

    check("reset chatbot", t_reset)

    bot_session: dict[str, str] = {}

    # --- LLM greeting (flexible, not hardcoded) -----------------------------
    def t_greeting():
        status, payload = _request(
            "POST",
            f"{base}/api/chatbot",
            token=token,
            body={
                "message": "Hey there! Hope you are doing great today",
                "session_id": "client-should-be-ignored",
            },
        )
        data = expect_ok("POST /api/chatbot (flexible greeting)", status, payload)
        if data.get("session_id") == "client-should-be-ignored":
            raise Failed("chatbot used client session_id instead of pinned session")
        assert_chat_ok("greeting", data, allow_blocked=allow_blocked)
        # Must not be the old hardcoded template
        ans = (data.get("answer") or "").lower()
        if "hello, admin! i'm your ticketsphere assistant. ask me about tickets, slas, outages, or runbooks." in ans:
            raise Failed("got hardcoded greeting template — expected LLM reply")
        bot_session["id"] = data["session_id"]

    check("LLM greeting", t_greeting)

    # --- session memory recall ----------------------------------------------
    def t_memory():
        status, payload = _request(
            "POST",
            f"{base}/api/chatbot",
            token=token,
            body={"message": "What did I ask in my previous message?"},
        )
        data = expect_ok("POST /api/chatbot (memory recall)", status, payload)
        pinned = bot_session.get("id")
        if pinned and data.get("session_id") != pinned:
            raise Failed(f"pinned session changed: {pinned} -> {data.get('session_id')}")
        assert_chat_ok("memory", data, allow_blocked=allow_blocked)
        ans = (data.get("answer") or "").lower()
        # Should reference the prior greeting somehow
        if not any(w in ans for w in ("hey", "hope", "great", "greet", "previous", "asked", "said", "doing")):
            print("         note: memory answer may be weak — review manually")

    check("session memory", t_memory)

    # --- ticket DB question -------------------------------------------------
    def t_tickets():
        status, payload = _request(
            "POST",
            f"{base}/api/chatbot",
            token=token,
            body={"message": "How many open tickets are assigned to Azure?"},
        )
        data = expect_ok("POST /api/chatbot (ticket DB)", status, payload)
        assert_chat_ok("ticket query", data, allow_blocked=allow_blocked)

    check("ticket DB query", t_tickets)

    # --- history ------------------------------------------------------------
    def t_history():
        status, payload = _request(
            "GET", f"{base}/api/chatbot/history", token=token, timeout=15
        )
        data = expect_ok("GET /api/chatbot/history", status, payload)
        if not isinstance(data, list) or len(data) < 4:
            raise Failed(f"expected >=4 history messages after 3 turns, got {len(data) if isinstance(data, list) else data}")
        print(f"         messages={len(data)}")

    check("chatbot history", t_history)

    # --- multi-session /chat ------------------------------------------------
    chat_a: dict[str, str] = {}
    chat_b: dict[str, str] = {}

    def t_chat_a():
        status, payload = _request(
            "POST",
            f"{base}/api/chat",
            token=token,
            body={"message": "hi"},
        )
        data = expect_ok("POST /api/chat (session A greeting)", status, payload)
        assert_chat_ok("chat A", data, allow_blocked=allow_blocked)
        chat_a["id"] = data["session_id"]

    check("chat session A", t_chat_a)

    def t_chat_a_followup():
        sid = chat_a.get("id")
        if not sid:
            raise Failed("skipped: no session A")
        status, payload = _request(
            "POST",
            f"{base}/api/chat",
            token=token,
            body={"message": "What did I just say?", "session_id": sid},
        )
        data = expect_ok("POST /api/chat (session A memory)", status, payload)
        if data.get("session_id") != sid:
            raise Failed(f"session A id drifted: {sid} -> {data.get('session_id')}")
        assert_chat_ok("chat A memory", data, allow_blocked=allow_blocked)

    check("chat session A memory", t_chat_a_followup)

    def t_chat_b():
        status, payload = _request(
            "POST",
            f"{base}/api/chat",
            token=token,
            body={"message": "hello"},
        )
        data = expect_ok("POST /api/chat (session B)", status, payload)
        assert_chat_ok("chat B", data, allow_blocked=allow_blocked)
        chat_b["id"] = data["session_id"]
        if chat_a.get("id") and chat_b["id"] == chat_a["id"]:
            raise Failed("session B reused session A id - isolation broken")

    check("chat session B isolation", t_chat_b)

    # --- list / delete ------------------------------------------------------
    def t_list_sessions():
        status, payload = _request(
            "GET",
            f"{base}/api/sessions?page=1&page_size=5",
            token=token,
            timeout=15,
        )
        data = expect_ok("GET /api/sessions", status, payload)
        if not isinstance(data, list):
            raise Failed("sessions data should be a list")
        meta = payload.get("meta") or {}
        if "total" not in meta:
            raise Failed(f"sessions meta missing total: {meta}")
        print(f"         total={meta.get('total')}")

    check("list sessions", t_list_sessions)

    def t_list_messages():
        sid = chat_a.get("id")
        if not sid:
            raise Failed("skipped: no session A")
        status, payload = _request(
            "GET",
            f"{base}/api/sessions/{sid}/messages?page=1&page_size=5",
            token=token,
            timeout=15,
        )
        data = expect_ok("GET /api/sessions/{id}/messages", status, payload)
        if not isinstance(data, list) or len(data) < 1:
            raise Failed("expected messages in session A")
        print(f"         page_size_returned={len(data)}")

    check("list messages", t_list_messages)

    def t_delete_session():
        sid = chat_b.get("id")
        if not sid:
            raise Failed("skipped: no session B")
        status, payload = _request(
            "DELETE", f"{base}/api/sessions/{sid}", token=token, timeout=15
        )
        data = expect_ok("DELETE /api/sessions/{id}", status, payload)
        if data.get("deleted") != sid:
            raise Failed(f"unexpected delete payload: {data}")
        status2, payload2 = _request(
            "GET",
            f"{base}/api/sessions/{sid}/messages?page=1&page_size=5",
            token=token,
            timeout=15,
        )
        expect_status("GET messages after delete -> 404", status2, payload2, 404)

    check("delete session", t_delete_session)

    def t_final_reset():
        status, payload = _request(
            "DELETE", f"{base}/api/chatbot/history", token=token, timeout=15
        )
        data = expect_ok("DELETE /api/chatbot/history", status, payload)
        if not data.get("session_id"):
            raise Failed(f"reset missing session_id: {data}")
        status2, payload2 = _request(
            "GET", f"{base}/api/chatbot/history", token=token, timeout=15
        )
        hist = expect_ok("GET /api/chatbot/history after reset", status2, payload2)
        if hist:
            raise Failed(f"history not empty after reset: {len(hist)} messages")

    check("final reset", t_final_reset)

    print()
    if failures:
        print(f"FAILED - {len(failures)} check(s) failed:")
        for item in failures:
            print(f"  - {item}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Smoke-test chatbot HTTP APIs")
    parser.add_argument("--base", default=DEFAULT_BASE, help="Backend base URL")
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Accept blocked chat answers (API envelope only)",
    )
    args = parser.parse_args()
    run(args.base, allow_blocked=args.allow_blocked)


if __name__ == "__main__":
    main()
