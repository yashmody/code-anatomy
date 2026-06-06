"""seed_faqs — parse static aem-banking-faq.html and seed into Postgres/SQLite.

Run as module:
    python -m scripts.seed_faqs
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
import sqlalchemy as sa
from sqlalchemy import select

from app.core import config
from app.core.db import get_session
from app.core.models import FAQCategory, FAQItem


def parse_faq_html(html_path: Path) -> dict:
    """Parse static AEM Banking FAQ HTML and extract categories and items."""
    content = html_path.read_text(encoding="utf-8")
    
    # 1. Parse Category details
    title_match = re.search(r"<h1>(.*?)</h1>", content, re.DOTALL)
    title = title_match.group(1).replace('<span class="x">', '').replace('</span>', '').strip() if title_match else "AEM × Banking"
    
    lede_match = re.search(r'<p class="lede">(.*?)</p>', content, re.DOTALL)
    lede = lede_match.group(1).strip() if lede_match else ""
    
    audience = ""
    audience_match = re.search(r"<b>Audience</b>\s*([^<]+)", content)
    if audience_match:
        audience = audience_match.group(1).strip()
        
    reviewed_at = ""
    reviewed_match = re.search(r"<b>Reviewed</b>\s*([^<]+)", content)
    if reviewed_match:
        reviewed_at = reviewed_match.group(1).strip()
        
    source = ""
    source_match = re.search(r"<b>Source</b>\s*([^<]+)", content)
    if source_match:
        source = source_match.group(1).strip()

    category = {
        "id": "aem-banking",
        "title": title,
        "description": lede,
        "status": "published",
        "audience": audience,
        "source": source,
        "reviewed_at": reviewed_at
    }
    
    # 2. Parse FAQ Q&As
    items = []
    details_pattern = re.compile(
        r'<details class="faq"\s+id="([^"]+)"\s+data-tags="([^"]+)"\s*>(.*?)</details>',
        re.DOTALL
    )
    
    for match in details_pattern.finditer(content):
        qid, tags_str, inner_content = match.groups()
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        
        qnum_match = re.search(r'<span class="q-num">([^<]+)</span>', inner_content)
        q_num = qnum_match.group(1).strip() if qnum_match else ""
        
        qtext_match = re.search(r'<span class="q-text">(.*?)</span>', inner_content, re.DOTALL)
        question = qtext_match.group(1).replace('<mark>', '').replace('</mark>', '').strip() if qtext_match else ""
        
        answer_match = re.search(r'<div class="answer">(.*?)</div>\s*$', inner_content, re.DOTALL)
        if answer_match:
            answer_html = answer_match.group(1).strip()
            # Strip tag chips at the bottom of the answer block
            answer_html = re.sub(r'<div class="q-tags".*?</div>', '', answer_html, flags=re.DOTALL).strip()
        else:
            answer_html = ""
            
        items.append({
            "q_num": q_num,
            "question": question,
            "answer": answer_html,
            "tags": tags
        })
        
    return {"category": category, "items": items}


def seed_database(parsed_data: dict) -> tuple[int, int]:
    """Seed category and items into the DB. Idempotent: re-runs update/re-insert."""
    cat_data = parsed_data["category"]
    item_list = parsed_data["items"]
    
    with get_session() as s:
        # Category
        category = s.get(FAQCategory, cat_data["id"])
        if not category:
            category = FAQCategory(
                id=cat_data["id"],
                title=cat_data["title"],
                description=cat_data["description"],
                status=cat_data["status"],
                audience=cat_data["audience"],
                source=cat_data["source"],
                reviewed_at=cat_data["reviewed_at"]
            )
            s.add(category)
        else:
            category.title = cat_data["title"]
            category.description = cat_data["description"]
            category.status = cat_data["status"]
            category.audience = cat_data["audience"]
            category.source = cat_data["source"]
            category.reviewed_at = cat_data["reviewed_at"]
            
        # Items: clear existing questions for this category and re-insert
        # (This is simpler and cleaner for seeding static content)
        s.execute(
            sa.delete(FAQItem).where(FAQItem.category_id == cat_data["id"])
        )
        
        items_added = 0
        for item in item_list:
            faq_item = FAQItem(
                category_id=cat_data["id"],
                q_num=item["q_num"],
                question=item["question"],
                answer=item["answer"],
                tags=item["tags"]
            )
            s.add(faq_item)
            items_added += 1
            
        s.commit()
        return 1, items_added


def main() -> int:
    html_path = config.BASE_DIR.parent / "content" / "frozen" / "faqs" / "aem-banking-faq.html"
    if not html_path.exists():
        print(f"❌ Static FAQ page not found at {html_path}")
        return 1
        
    print(f"🔍 Parsing static FAQ from {html_path}...")
    try:
        parsed = parse_faq_html(html_path)
    except Exception as exc:
        print(f"❌ Failed to parse FAQ HTML: {exc}")
        return 1
        
    print(f"✅ Parsed category '{parsed['category']['title']}' with {len(parsed['items'])} questions.")
    
    print("🌱 Seeding database...")
    try:
        cats, items = seed_database(parsed)
        print(f"✅ Seeding successful: {cats} category, {items} questions seeded.")
    except Exception as exc:
        print(f"❌ Database seeding failed: {exc}")
        return 1
        
    return 0


if __name__ == "__main__":
    sys.exit(main())
