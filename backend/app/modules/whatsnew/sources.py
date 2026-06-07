"""Adobe source registry + egress allow-list for the content-refresh sync.

The fetcher will ONLY retrieve URLs whose host is in ALLOWED_HOSTS (SSRF guard).
Each source maps to the course chapter it relates to (for the bounded Phase-2
course refresh) and to a `What's New` group label. URLs are the canonical
Experience League release-note pages (server-rendered; verified fetchable).
"""

ALLOWED_HOSTS = frozenset({"experienceleague.adobe.com"})

# key      → stable id stored on each item
# product  → display label
# url      → release-notes page (host must be in ALLOWED_HOSTS)
# chapter  → related course chapter filename (Phase-2 target), or None
SOURCES = [
    {
        "key": "aem",
        "product": "Adobe Experience Manager as a Cloud Service",
        "url": "https://experienceleague.adobe.com/en/docs/experience-manager-cloud-service/content/release-notes/release-notes/release-notes-current",
        "chapter": "adobe-cm.json",
    },
    {
        "key": "commerce",
        "product": "Adobe Commerce",
        "url": "https://experienceleague.adobe.com/en/docs/commerce-operations/release/notes/adobe-commerce/overview",
        "chapter": "adobe-csc.json",
    },
    {
        "key": "ajo",
        "product": "Adobe Journey Optimizer",
        "url": "https://experienceleague.adobe.com/en/docs/journey-optimizer/using/whats-new/release-notes",
        "chapter": "adobe-ajo.json",
    },
    {
        "key": "cja",
        "product": "Customer Journey Analytics",
        "url": "https://experienceleague.adobe.com/en/docs/analytics-platform/using/releases/latest",
        "chapter": "adobe-cja.json",
    },
    {
        "key": "target",
        "product": "Adobe Target",
        "url": "https://experienceleague.adobe.com/en/docs/target/using/release-notes/release-notes",
        "chapter": "adobe-ab.json",
    },
    {
        "key": "campaign",
        "product": "Adobe Campaign",
        "url": "https://experienceleague.adobe.com/en/docs/campaign-web/v8/release-notes/release-notes",
        "chapter": "adobe-camp.json",
    },
]


def host_allowed(url: str) -> bool:
    """True iff `url`'s host is in the allow-list (egress / SSRF guard)."""
    from urllib.parse import urlsplit
    try:
        return (urlsplit(url).hostname or "").lower() in ALLOWED_HOSTS
    except (ValueError, TypeError):
        return False
