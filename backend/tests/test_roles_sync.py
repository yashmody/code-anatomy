"""Tests for the Directus -> FastAPI staff-role mirror (04 §7.2).

Covers both halves of the seam:
  - `core.users.sync_staff_roles` — the authoritative, staff-only reconcile.
  - `POST /api/cms/roles-sync` — the loopback-guarded receiver.

The reconcile writes to the real configured database (Postgres in dev — the
`user_roles` join + `auth_audit` don't exist on sqlite), so every test cleans
up the rows it creates for the test email, pass or fail.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.main import app
from app.core import users
from app.core.db import get_session
from app.core.models import AuthAudit, Role, User, UserRole
from app.modules.cms import routes as cms_routes

client = TestClient(app)

TEST_EMAIL = "rolesync.test@deptagency.com"


def _purge(email: str) -> None:
    """Remove all trace of `email` from users / user_roles / auth_audit."""
    with get_session() as s:
        s.execute(delete(UserRole).where(UserRole.user_email == email))
        s.execute(delete(AuthAudit).where(AuthAudit.target_email == email))
        s.execute(delete(User).where(User.email == email))
        s.commit()


@pytest.fixture
def clean_email():
    """Yield a known test email, scrubbed before and after the test."""
    _purge(TEST_EMAIL)
    yield TEST_EMAIL
    _purge(TEST_EMAIL)


def _staff_roles(email: str) -> set:
    return users.roles_for(email) & users.STAFF_ROLE_KEYS


# ── reconcile helper ─────────────────────────────────────────────────────────


def test_grant_on_assign_creates_user_row(clean_email):
    """A staff role for an email with no users row: row is created (mirror
    provider) and the staff role granted."""
    roles = users.sync_staff_roles(clean_email, "content_author")
    assert "content_author" in roles
    assert "learner" in roles  # floor always present
    u = users.get_user(clean_email)
    assert u is not None and u["provider"] == "directus-mirror"


def test_swap_role_revokes_the_old_staff_role(clean_email):
    users.sync_staff_roles(clean_email, "content_author")
    roles = users.sync_staff_roles(clean_email, "quiz_admin")
    assert _staff_roles(clean_email) == {"quiz_admin"}
    assert "content_author" not in roles


def test_none_revokes_all_staff_roles_but_keeps_learner(clean_email):
    users.sync_staff_roles(clean_email, "feed_moderator")
    roles = users.sync_staff_roles(clean_email, None)
    assert _staff_roles(clean_email) == set()
    assert "learner" in roles


def test_never_touches_feed_contributor_or_learner(clean_email):
    """feed_contributor is learner-plane (app-owned) — the mirror must preserve
    it across staff-role grants and revokes."""
    users.upsert_user(clean_email)
    users.grant_role(clean_email, "feed_contributor", granted_by="test")

    after_grant = users.sync_staff_roles(clean_email, "content_author")
    assert {"feed_contributor", "content_author", "learner"} <= after_grant

    after_revoke = users.sync_staff_roles(clean_email, None)
    assert "feed_contributor" in after_revoke   # untouched
    assert "learner" in after_revoke            # floor untouched
    assert _staff_roles(clean_email) == set()   # staff cleared


def test_non_staff_target_is_treated_as_none(clean_email):
    users.sync_staff_roles(clean_email, "content_author")
    # 'learner' is not a staff key -> target None -> staff roles cleared.
    users.sync_staff_roles(clean_email, "learner")
    assert _staff_roles(clean_email) == set()


def test_idempotent_no_op(clean_email):
    first = users.sync_staff_roles(clean_email, "platform_admin")
    second = users.sync_staff_roles(clean_email, "platform_admin")
    assert first == second
    assert _staff_roles(clean_email) == {"platform_admin"}


# ── endpoint ─────────────────────────────────────────────────────────────────


def test_endpoint_rejects_non_loopback():
    """Default TestClient host is non-loopback -> 403 (policy, not credentials)."""
    res = client.post("/api/cms/roles-sync", json={"email": TEST_EMAIL, "role": "content_author"})
    assert res.status_code == 403


def test_endpoint_reconciles_on_loopback(clean_email, monkeypatch):
    monkeypatch.setattr(cms_routes, "_is_loopback", lambda host: True)

    res = client.post("/api/cms/roles-sync", json={"email": clean_email, "role": "quiz_admin"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True and body["email"] == clean_email
    assert "quiz_admin" in body["roles"]
    assert _staff_roles(clean_email) == {"quiz_admin"}

    # role: null clears the staff role.
    res2 = client.post("/api/cms/roles-sync", json={"email": clean_email, "role": None})
    assert res2.status_code == 200
    assert _staff_roles(clean_email) == set()


def test_endpoint_validation(monkeypatch):
    monkeypatch.setattr(cms_routes, "_is_loopback", lambda host: True)
    assert client.post("/api/cms/roles-sync", json={"role": "quiz_admin"}).status_code == 400  # missing email
    assert client.post("/api/cms/roles-sync", json={"email": TEST_EMAIL, "role": 5}).status_code == 400  # bad role type
