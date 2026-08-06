"""Chunk-level access control, enforced inside the vector search.

The rule that matters: a user must never be able to influence what the model *sees*,
only what it is asked. So the ACL becomes a Chroma `where` clause passed into the
query — filtering after retrieval would mean unauthorised text still reached the
prompt, and top-k would silently degrade for restricted users.

Metadata convention (written by rag/chunker.py):
    acl_<role> = True     one key per role permitted to see the chunk
    acl_public = True     readable by any authenticated user
    sensitivity = str     public | internal | confidential | restricted
"""

from __future__ import annotations

from typing import Any

ACL_PREFIX = "acl_"
PUBLIC_KEY = "acl_public"

# A user holding this clearance bypasses filtering entirely.
SUPER_CLEARANCE = "all"

# Sensitivity a role may read up to. [PLACEHOLDER: DOMAIN_SENSITIVITY_MATRIX]
MAX_SENSITIVITY = {
    "admin": "restricted",
    "analyst": "confidential",
    "viewer": "internal",
}
_ORDER = ["public", "internal", "confidential", "restricted"]


def acl_metadata(allowed_roles: list[str]) -> dict[str, bool]:
    """Expand a role list into the flat boolean keys Chroma can filter on.

    Chroma metadata values must be scalars, so a list column is not filterable — one
    key per role is the workaround, and it stays fast because it is an exact match.
    """
    roles = allowed_roles or ["admin"]
    meta: dict[str, bool] = {}
    for role in roles:
        if role in {"all", "public", "*"}:
            meta[PUBLIC_KEY] = True
        else:
            meta[f"{ACL_PREFIX}{role}"] = True
    return meta


def build_where(user: dict, extra: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Compose the query-time filter for this user.

    Returns None for unrestricted users — Chroma treats that as "no filter", which is
    faster than an always-true clause.
    """
    role = (user or {}).get("role", "viewer")
    clearances = (user or {}).get("clearances") or []

    unrestricted = role == "admin" or SUPER_CLEARANCE in clearances
    acl_clause = None

    if not unrestricted:
        keys = {PUBLIC_KEY, f"{ACL_PREFIX}{role}"}
        keys.update(f"{ACL_PREFIX}{c}" for c in clearances)
        clauses = [{key: True} for key in sorted(keys)]
        # Chroma rejects $or with a single operand.
        acl_clause = clauses[0] if len(clauses) == 1 else {"$or": clauses}

    filters: list[dict[str, Any]] = []
    if acl_clause:
        filters.append(acl_clause)

    ceiling = MAX_SENSITIVITY.get(role)
    if ceiling and not unrestricted:
        allowed = _ORDER[: _ORDER.index(ceiling) + 1]
        filters.append({"sensitivity": {"$in": allowed}})

    for key, value in (extra or {}).items():
        filters.append({key: value})

    if not filters:
        return None
    return filters[0] if len(filters) == 1 else {"$and": filters}


def can_read(user: dict, metadata: dict) -> bool:
    """Defence in depth: re-check a chunk the store already filtered.

    Should never return False in normal operation. If it does, the `where` clause and
    this function have drifted apart — which is exactly the bug worth catching.
    """
    role = (user or {}).get("role", "viewer")
    clearances = (user or {}).get("clearances") or []
    if role == "admin" or SUPER_CLEARANCE in clearances:
        return True
    if metadata.get(PUBLIC_KEY):
        return True
    return any(metadata.get(f"{ACL_PREFIX}{r}") for r in [role, *clearances])
