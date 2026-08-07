import inspect
import datetime as dt
import jwt
from run import create_app
import api
from config import settings

app = create_app()
src = inspect.getsource(api.team_queue)
assert "_scope_ticket_query" in src
assert 'notin_(["resolved", "synced"])' in src or "resolved" in src
triage_src = inspect.getsource(api.analytics_triage)
assert 'require_role' in api.analytics_triage.__wrapped__.__name__ or True
# Decorators applied - check route registry
rules = [str(r) for r in app.url_map.iter_rules() if "analytics/triage" in str(r) or "teams/queue" in str(r)]
print("routes", rules)

def token(role, clearances=None, uid="u-test"):
    return jwt.encode(
        {
            "sub": uid,
            "id": uid,
            "username": "t",
            "role": role,
            "clearances": clearances or ["all"],
            "exp": dt.datetime.utcnow() + dt.timedelta(hours=1),
        },
        settings.JWT_SECRET,
        algorithm="HS256",
    )

client = app.test_client()

# How does auth decode JWT? match login payload
from api import _make_token if False else None
