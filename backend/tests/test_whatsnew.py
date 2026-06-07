"""Tests for the What's New endpoint (GET /api/whatsnew).

Covers the auth gate, the response shape, and that an inserted item surfaces in
its product group. Runs against the real configured DB (the whats_new_items
table). The inserted row is torn down.
"""
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_session
from app.core.deps import require_authenticated
from app.core.models import WhatsNewItem

client = TestClient(app)


@pytest.fixture
def as_signed_in_user():
    app.dependency_overrides[require_authenticated] = lambda: {"email": "wn-test@deptagency.com"}
    yield
    app.dependency_overrides.pop(require_authenticated, None)


@pytest.fixture
def whatsnew_item():
    created = []

    def _factory(product="Test Product", title="Test update"):
        item_id = f"wn-test-{uuid.uuid4()}"
        with get_session() as s:
            s.add(WhatsNewItem(
                id=item_id, source="aem",
                source_url=f"https://experienceleague.adobe.com/test#{item_id}",
                product=product, title=title, summary="A test summary.",
                related_chapter="adobe-cm.json", published_at=datetime.utcnow(), status="new",
            ))
            s.commit()
        created.append(item_id)
        return item_id

    yield _factory

    with get_session() as s:
        for iid in created:
            row = s.get(WhatsNewItem, iid)
            if row:
                s.delete(row)
        s.commit()


def test_whatsnew_requires_authentication():
    assert client.get("/api/whatsnew").status_code == 401


def test_whatsnew_returns_envelope(as_signed_in_user):
    res = client.get("/api/whatsnew")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body.get("items"), list)
    assert isinstance(body.get("groups"), list)


def test_whatsnew_lists_inserted_item_in_group(as_signed_in_user, whatsnew_item):
    item_id = whatsnew_item(product="Zzz Unique Product", title="Distinct test headline")
    res = client.get("/api/whatsnew")
    assert res.status_code == 200
    body = res.json()
    assert any(i["id"] == item_id for i in body["items"]), "item missing from flat list"
    grp = next((g for g in body["groups"] if g["product"] == "Zzz Unique Product"), None)
    assert grp is not None and any(i["id"] == item_id for i in grp["items"]), "item missing from its group"
