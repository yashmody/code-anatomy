# CODE-CODER Content Architecture

Two content domains, two journeys, one optional bridge.

```
┌─ COURSE (authored, canonical) ──────────────┐   ┌─ FEED (user-generated) ──────────┐
│  framework.json — the spine                 │   │  feed.json — the UGC stream      │
│  sections/*.json — the prose, in blocks     │   │  posts: fieldnote · card · video │
│                                             │   │         vocab · scenario         │
│  RENDERED BY:                               │   │  RENDERED BY:                    │
│   • Scroll mode (current page, unchanged)   │   │   • Feed mode                    │
│   • Read mode (ebook, paginated)            │   │                                  │
│                                             │   │  Journey: social — recency,      │
│  Journey: the CODE-CODER framework.         │   │  engagement, topics, following.  │
│  Navigated by letter + telescoping.         │   │  NOT framework order.            │
└─────────────────────────────────────────────┘   └──────────────────────────────────┘
                    │                                            │
                    └──────────── frameworkRef ──────────────────┘
                         (optional bridge — a feed post can point at
                          a chapter; a chapter can show related posts)
```

The two domains are independent. The course doesn't need the feed to navigate; the feed doesn't need the framework to navigate. They cross-link through one optional field. This is what keeps navigation clean — neither side is forced into the other's structure.

---

## Domain 1 · COURSE (authored)

The canonical field manual. Framework-navigated, authored by you, version-controlled. **Two modes render it:**

- **Scroll mode** — the current single-page experience, unchanged. Renders every block in framework order, linearly.
- **Read mode** — the ebook. Same content, grouped into turnable pages by the `page` flag, one chapter per framework letter, with the telescope transition generated from `opensInto`.

That's the point of building this domain as data: Scroll and Read are two lenses on one authored content set. Write a chapter once; both modes render it.

### `course/framework.json` — the spine

Defines rings, letters, order, nesting (`nestedUnder`), and telescoping (`opensInto`). The navigation source of truth for Scroll and Read — the Scroll TOC, the Read chapter list, and the Compass map all read from it. 34 addresses across CODE, CODER, Anatomy, Adobe Stack, AI-Native.

### `course/sections/*.json` — the prose, in blocks

One file per chapter (framework letter). A section is an ordered list of typed **blocks**. Scroll renders them all linearly; Read groups them by `page`.

```jsonc
{
  "frameworkAddress": "coder.d",       // mandatory — this IS the navigation
  "title": "Deployment",
  "tag": "Infrastructure 101 for architects",
  "scan": [ "…30-second scan bullets…" ],
  "sections": [
    {
      "id": "coder.d.caching",
      "title": "The Five Caching Tiers",
      "order": 1,
      "blocks": [
        { "type": "lead",    "page": 2, "html": "Caching is the single largest performance lever…" },
        { "type": "prose",   "page": 2, "html": "Every production stack caches in five places…" },
        { "type": "tierlist","page": 2, "items": [ { "n": "1", "label": "Browser cache", "note": "Cache-Control" } ] },
        { "type": "callout", "page": 2, "variant": "why", "html": "If you can't draw the cache topology in 60 seconds…" }
      ]
    }
  ]
}
```

**Block types:** `chapter-open` (drop-cap opener, page 1) · `lead` · `prose` · `heading` · `tierlist` · `diagram` (`render: ascii|mermaid|table|versus` — the three-way diagram rule) · `callout` (`variant: why|tip|pitfall|before-after`) · `code` · `quote` · `architects-review`.

**Block flags:** `page` (int — which Read-mode page) · `collapsed` (bool — render as `<details>` in Scroll). The old `surfaceable` flag is gone — the feed no longer pulls from course content.

**Cardinal migration rule:** re-shell only, never rewrite. The HTML inside a `prose` block is the existing course text, verbatim. Pagination splits *between* blocks, never *within* a paragraph.

---

## Domain 2 · FEED (user-generated)

A social stream. Anyone on the team can post — the same content types that lived in the old feed (field notes, cards, videos, vocab, scenarios), now contributed by users rather than derived from the course. **One mode renders it: Feed mode.**

It has its own journey: ordered by recency, engagement, and topics — not the framework. A reader scrolls the feed the way they scroll Instagram, not the way they walk a syllabus.

### `feed/feed.json` — the stream

In production this is a database collection / API, not a static file. One stream, mixed post types, each carrying the UGC envelope:

```jsonc
{
  "id": "post.7fk2a9",
  "type": "fieldnote",              // fieldnote | card | video | vocab | scenario
  "author": { "userId": "u.sumit", "name": "Sumit M.", "role": "Senior Architect · Mumbai", "initials": "SM", "verified": false },
  "status": "published",            // draft | pending-review | published | flagged | removed
  "topics": ["deployment", "caching"],   // free tags — the feed's own categorisation + filter
  "frameworkRef": "coder.d",        // OPTIONAL — bridge to a course chapter (see below)
  "createdAt": "2026-05-20T09:00:00Z",
  "updatedAt": "2026-05-20T09:00:00Z",
  "engagement": { "upvotes": 28, "comments": 4, "saves": 12 },
  // …type-specific payload…
}
```

**Type-specific payloads:**

| type | fields |
|---|---|
| `fieldnote` | `title`, `body` (≤100 words, validated on submit) |
| `card` | `title`, `teaser`, `linkUrl?` |
| `video` | `title`, `durationSec`, `url`, `thumbnail?`, `hook` |
| `vocab` | `term`, `definition` |
| `scenario` | `prompt`, `options[]`, `correct`, `verdict`, `reveal` |

### The feed's journey (not the framework's)

Ordering signals, rough priority: **recency** (new posts surface), **engagement** (upvotes/saves/comments lift a post), **topic match** (topics the reader follows), **author follow**, **editorial pin** (an optional `featured` flag for official posts). The framework plays no role in feed ordering — `topics` and `frameworkRef` are filters a reader can opt into ("show me the Deployment feed"), not the spine.

### Moderation — built in

The whole feed is UGC, so moderation is first-class:

- New posts enter as `status: "pending-review"`.
- A moderator flips to `published` (or `removed`).
- Readers can flag; `moderation.flagCount` accumulates; a threshold auto-moves a post to `flagged` for re-review.
- `moderation: { flagCount, reviewedBy, reviewedAt }` tracks the trail.

`fieldnote` bodies are validated to ≤100 words on submit — the constraint is the feature.

---

## The bridge · `frameworkRef`

The one connection between domains, loose by design — a reference, not a dependency.

- **Feed → Course.** A post with `frameworkRef: "coder.d"` can show a "Read the chapter" CTA that opens Read mode at Deployment. The post *points at* the course; it isn't *part of* it.
- **Course → Feed.** A course section can optionally query the feed for `frameworkRef == <its address>` and show a small "From the community" strip. Read-only, additive, never affects course navigation.

Either direction can be switched off without breaking the other domain. That's the test of a clean bridge.

---

## What each mode loads

| Mode | Domain | Loads | Navigated by |
|---|---|---|---|
| **Scroll** (current) | Course | `framework.json` + all `sections/*` | framework order, linear |
| **Read** (ebook) | Course | `framework.json` + current chapter | framework letters, paginated, telescoping |
| **Feed** (social) | Feed | `feed.json` stream | recency · engagement · topics · following |

Course progress (% through CODER) belongs to Scroll + Read. The Feed has no framework progress bar — its journey is social discovery, so it gets social navigation instead (topics you follow, trending, recent, your contributions).

---

## The authoring system (where this is heading)

Two authoring surfaces, matching the two domains:

1. **Course authoring** (you / editorial) — writes/edits `sections/*.json` blocks. Framework address mandatory; status gates publish. Structured, deliberate, versioned.
2. **Feed posting** (anyone) — an Instagram-style composer: pick a type, write the payload, add topics, optionally tag a `frameworkRef`, submit. Enters as `pending-review`. Fast, social, moderated.

Because the domains are separate, the two tools are separate and simpler. The feed composer never has to understand the block model; the course editor never has to understand engagement metrics.

---

## Migration plan — chapter by chapter (course only)

The feed is net-new UGC — nothing to migrate; it starts empty and fills as people post. **Migration is purely the course domain.**

1. **Freeze this schema.** Validate against the worked example (`course/sections/coder-d.json`, Deployment) before extracting more.
2. **Extract one letter per pass.** Parse existing HTML, slice into blocks, assign addresses, paginate, write `sections/<ring>-<letter>.json`.
3. **Re-shell only, never rewrite.** Review each extraction as a reader before moving on.
4. **Validate** every file — JSON parses, addresses resolve against `framework.json`.

Extraction order (highest-traffic first): Deployment → Release → Code/Anatomy → External → Quality → CODE letters → Adobe Stack.

---

## Appendix A · Feed types & the shared media model (updated)

The feed has one composer that creates any of these types. Every type carries the common envelope plus a shared `media` array, so **any post can attach an image or a diagram** — not just text posts.

| type | payload | purpose |
|---|---|---|
| `post` | `title?`, `body` (≤100 words, validated) | the text microblog — the "Field Note" |
| `video` | `title`, `hook`, `durationSec`, `url` | short-form video |
| `list` | `title`, `intro?`, `items[]` of `{ text, note? }` | checklists, pointer lists, "6 things" posts |
| `card` | `title`, `teaser`, `linkUrl?` | a single concept callout |
| `vocab` | `term`, `definition` | a community vocab card |
| `scenario` | `prompt`, `options[]`, `correct`, `verdict`, `reveal` | a judgement rep |

### The shared `media` array

Hangs on the envelope; available to every type:

```jsonc
"media": [
  { "kind": "image",   "url": "https://…", "alt": "…", "caption": "…", "width": 1200, "height": 800 },
  { "kind": "diagram", "render": "mermaid", "source": "graph TD; A-->B", "alt": "…" },
  { "kind": "diagram", "render": "image",  "url": "https://…", "alt": "…" }
]
```

`post + image/diagram` is just a `post` with one media item. A diagram can be inline source (`render: mermaid|ascii`) or an uploaded image (`render: image`). Uploaded images go to blob storage (or a Postgres large object) and the row stores the URL — never the bytes inline.

### Extensibility — how to add a new type

The pattern is fixed, so growth never restructures anything: a new type = a new `type` value + its payload fields + (optionally) media. The envelope, the composer's shared fields (author, topics, frameworkRef, status), the moderation flow, and the renderers' dispatch-by-type all stay the same. The same applies to course **block types** — add a `type` to the block-renderer registry; nothing else changes.

## Appendix B · Course block types (updated)

Added to cover layouts present in the field manual:

| type | renders as |
|---|---|
| `cardgrid` | N-column card layout (`columns`, `cards[]` of `{eyebrow, title, body}`) — the CODE block, auth menu, IaaS ladder, Logs/Metrics/Traces pillars |
| `chips` | a row of small tag chips (`items[]`) — deliverable lists like "Content Inventory · Taxonomy · …" |

---

## Appendix C · Storage decision — JSON files now, Postgres later (and which part, when)

**Decision: stay on JSON files for this phase. Design Postgres-ready. Move the *feed* to Postgres when it goes multi-user; keep the *course* on files indefinitely.**

The two domains have opposite storage profiles, so they get different answers.

**Course → files, long-term.** Authored, versioned, low-write, read-mostly. Git is the version control; the UI fetches the JSON directly. This is *correct* as files, not a temporary compromise. Move it to a database only if/when you need non-technical editors (a CMS) or full-text/semantic search across all chapters — neither is true now.

**Feed → Postgres, but not yet.** UGC is the opposite: high-write, concurrent, unbounded growth, atomic engagement counters, a moderation state machine, and sorting by recency × engagement × topic. That is a database workload — you cannot run a real feed off a JSON file. **But it isn't live yet.** Until there's a real composer and real users, there's nothing to store. So the feed stays JSON *for defining shapes during this restructuring*, and moves to Postgres as part of the separate feed-backend build (composer + API + moderation queue) — the next major effort after this one.

**Why not do Postgres now:** the current task is HTML componentization + course extraction. Neither needs a database. Adding Postgres now means a backend service, migrations, an ORM, hosting, and connection management — real scope that delivers nothing for the work in front of us. Defer it to when the feed actually goes multi-user.

**Postgres-readiness (so the later migration is mechanical).** Because every item is already a clean JSON object with a stable envelope, it maps to one row with promoted columns for indexing and a JSONB column for the rest — the "indexable unstructured schema":

```sql
CREATE TABLE feed_item (
  id            text PRIMARY KEY,
  type          text NOT NULL,
  status        text NOT NULL,
  author_id     text NOT NULL,
  framework_ref text,                       -- the optional bridge
  topics        text[] NOT NULL DEFAULT '{}',
  created_at    timestamptz NOT NULL,
  updated_at    timestamptz NOT NULL,
  data          jsonb NOT NULL,             -- payload + media + engagement + moderation
  search        tsvector GENERATED ALWAYS AS (to_tsvector('english', data->>'title' || ' ' || coalesce(data->>'body',''))) STORED,
  embedding     vector(1536)                -- pgvector, for semantic search/recs (later)
);
CREATE INDEX ON feed_item (status, created_at DESC);   -- feed ordering
CREATE INDEX ON feed_item USING gin (topics);          -- topic filter
CREATE INDEX ON feed_item USING gin (data jsonb_path_ops); -- containment queries
CREATE INDEX ON feed_item USING gin (search);          -- full-text
-- CREATE INDEX ON feed_item USING hnsw (embedding vector_cosine_ops); -- when pgvector is added
```

Plugins, when the time comes: **pgvector** (embeddings → semantic search and "related posts"), **pg_trgm** (fuzzy text match), and built-in **tsvector** full-text. Course content *could* later adopt the same JSONB-per-block pattern for cross-course search — but only when search is actually a requirement.

**The trigger to flip:** feed → Postgres at the multi-user composer build; course → Postgres only if a CMS or global search is ever needed. Until then, the envelope-stable JSON *is* the migration plan.
