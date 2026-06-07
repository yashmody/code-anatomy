---
id: managing-faqs
title: Manage FAQs
sidebar_position: 3
---

# Manage FAQs

The FAQs are a curated, categorised set of questions and answers served to the
SPA and the standalone FAQ page. They are authored entirely in Directus.

## Scan box

- **Two collections, one parent-child shape.** `faq_categories` holds the
  groups; `faq_items` holds the individual questions, each pointing at a
  category via `category_id`.
- **Categories have a status.** `published`, `draft` or `soon` — `soon` renders
  as a "coming soon" placeholder card. Only `published` categories show their
  questions to readers.
- **Items are ordered by `q_num`.** Set it to control the order questions
  appear within a category.
- **`content.write` required.** Held by the `content_author` role.
- **Cached for fifteen minutes; busted on save.** Publishing fires the webhook
  that clears the FAQ cache, so edits appear right away.

## Steps — add a question

1. In Directus, open **Content → faq_categories** and confirm the category you
   want exists and is **published**. If not, create it (see below).
2. Open **Content → faq_items** and create a new item.
3. Fill the fields:
   - `category_id` — the category this question belongs to.
   - `q_num` — sort order within the category (lower shows first).
   - `question` — the question text.
   - `answer` — the answer (rich text / WYSIWYG).
   - `tags` — optional comma-separated tags.
4. Save. The change is live once the webhook clears the cache.

## Steps — add a category

1. In **faq_categories**, create a row.
2. Fill `id`, `title`, `description`, `audience` and `source` as needed.
3. Set `status`:
   - `published` — visible with its questions.
   - `draft` — hidden from readers.
   - `soon` — shows a "coming soon" placeholder, no questions.
4. Save.

## Verify

```bash
curl -s https://internal.in.deptagency.com/api/faqs | head        # all categories + counts
curl -s https://internal.in.deptagency.com/api/faqs/<category_id>  # one category + its items
```

| Thing | Collection | Read endpoint |
|---|---|---|
| Category list (with counts) | `faq_categories` | `GET /api/faqs` |
| Category detail + items | `faq_categories` + `faq_items` | `GET /api/faqs/{category_id}` |

:::caution[Common Pitfall]

A question that "won't appear" is usually parented to a category whose status is
`draft` or `soon`, not `published`. The item can be perfect and still be hidden
because its category is. Check the category first.

:::

:::note[Agency Tip]

Use `q_num` in steps of ten (10, 20, 30…) rather than 1, 2, 3. When you need to
slot a new question between two existing ones later, you can give it `15` without
renumbering the whole category.

:::
