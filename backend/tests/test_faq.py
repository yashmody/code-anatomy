"""Tests for the FAQ module endpoints, storage, caching, and cache invalidation.

Covers:
  - GET /api/faqs — retrieving FAQ categories.
  - GET /api/faqs/{category_id} — retrieving details of a category.
  - Cache integration — ensuring DB load is skipped on cached hit.
  - CMS Webhook cache invalidation — ensuring prefix invalidation triggers on updates.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core import cache
from app.modules.faq import storage as faq_storage
from app.modules.cms import routes as cms_routes

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_cache():
    """Wipe cache before and after every test."""
    cache.clear()
    yield
    cache.clear()


# ---------- Storage & Routing Tests (Mocked) ----------

def test_get_faq_categories_endpoint(monkeypatch):
    """Verify category list endpoint queries storage and handles empty sets."""
    mock_data = [
        {
            "id": "aem-banking",
            "title": "AEM × Banking",
            "description": "Lede",
            "status": "published",
            "audience": "Developers",
            "source": "AEM Docs",
            "reviewed_at": "June 2026",
            "q_count": 13,
        }
    ]
    called = {"count": 0}

    def mock_get_all():
        called["count"] += 1
        return mock_data

    monkeypatch.setattr(faq_storage, "get_all_categories", mock_get_all)

    # 1. First call computes and caches
    res = client.get("/api/faqs")
    assert res.status_code == 200
    body = res.json()
    assert "categories" in body
    assert len(body["categories"]) == 1
    assert body["categories"][0]["id"] == "aem-banking"
    assert body["categories"][0]["q_count"] == 13
    assert called["count"] == 1

    # 2. Second call reads from cache (no extra DB call)
    res2 = client.get("/api/faqs")
    assert res2.status_code == 200
    assert res2.json() == body
    assert called["count"] == 1


def test_get_faq_category_detail_endpoint(monkeypatch):
    """Verify detail endpoint returns 404 for unknown categories and success for known ones."""
    mock_detail = {
        "category": {
            "id": "aem-banking",
            "title": "AEM × Banking",
            "description": "Lede",
            "status": "published",
            "audience": "Developers",
            "source": "AEM Docs",
            "reviewed_at": "June 2026",
            "q_count": 1,
        },
        "items": [
            {
                "id": 42,
                "q_num": "01",
                "question": "What is AEM?",
                "answer": "<p>A CMS</p>",
                "tags": ["aem"],
            }
        ],
    }
    called = {"count": 0}

    def mock_get_detail(category_id: str):
        called["count"] += 1
        if category_id == "aem-banking":
            return mock_detail
        return None

    monkeypatch.setattr(faq_storage, "get_category_detail", mock_get_detail)

    # 1. Fetching non-existent category gives 404
    res_404 = client.get("/api/faqs/unknown")
    assert res_404.status_code == 404
    assert called["count"] == 1

    # 2. Fetching existing category succeeds and caches
    res_200 = client.get("/api/faqs/aem-banking")
    assert res_200.status_code == 200
    body = res_200.json()
    assert body["category"]["id"] == "aem-banking"
    assert len(body["items"]) == 1
    assert body["items"][0]["question"] == "What is AEM?"
    assert called["count"] == 2

    # 3. Second call reads from cache
    res_cached = client.get("/api/faqs/aem-banking")
    assert res_cached.status_code == 200
    assert res_cached.json() == body
    assert called["count"] == 2


# ---------- Webhook Invalidation Tests ----------

def test_webhook_invalidates_faq_cache(monkeypatch):
    """Verify that a Directus webhook update on FAQ collections invalidates cached FAQ data."""
    monkeypatch.setattr(cms_routes, "_is_loopback", lambda host: True)

    mock_data = [{"id": "aem-banking", "title": "AEM", "status": "published", "q_count": 0}]
    called = {"count": 0}

    def mock_get_all():
        called["count"] += 1
        return mock_data

    monkeypatch.setattr(faq_storage, "get_all_categories", mock_get_all)

    # Cache the data
    client.get("/api/faqs")
    assert called["count"] == 1

    # Call webhook with a different collection (no invalidation)
    res_web_other = client.post("/api/cms/webhook", json={"collection": "questions", "keys": []})
    assert res_web_other.status_code == 200
    client.get("/api/faqs")
    assert called["count"] == 1  # read from cache

    # Call webhook with faq_categories collection -> invalidates
    res_web_faq = client.post("/api/cms/webhook", json={"collection": "faq_categories", "keys": []})
    assert res_web_faq.status_code == 200
    assert res_web_faq.json()["ok"] is True

    # Cache is invalidated; next call fetches from loader again
    client.get("/api/faqs")
    assert called["count"] == 2
