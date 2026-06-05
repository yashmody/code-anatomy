# Content Gap Report — Anatomy of Code

**Generated:** 2026-06-04 · branch `ui/three-mode-shell-and-feed`

**Canonical (source of truth):** `https://internal.in.deptagency.com/anatomy-of-code-course.html`
— verified content-equivalent to the repo's `content-system/anatomy-of-code-course.html`
(6,756 lines). Fingerprints checked against the live internal page: Adobe Stack incl. LLMO,
the maturity ladder "0 Flying Blind → 6 Orchestrated Journeys", the ten deployment layers,
BMAD, "Who watches what", the AI-routing section — all present and matching.

**Current (what we compared):** the new app's extracted course —
`content-architecture/course/sections/*.json`, rendered by Manual / Read.

**Scope:** topic-level migration coverage. The canonical course is the full field manual;
the app renders only what has been extracted into section JSON so far.

---

## 1. Headline

| Measure | Value |
|---|---|
| Planned spine (`framework.json`) | **30** addressable nodes (4 CODE · 5 CODER · 14 Anatomy · 5 Adobe · 2 AI) |
| Extracted into the app | **4** nodes — `coder.c`, `coder.d`, `coder.r`, `anatomy.m00` |
| Coverage of the planned spine | **~13%** |
| Canonical content with **no** spine address | LLMO · 4 of 6 Part-III sections · AI-routing/model-selection · BMAD worked example · the nest/review/watch trio |

Two distinct gaps:

1. **Extraction gap** — 26 of 30 planned nodes are not yet built, and two of the four that *are* built are incomplete (see §3).
2. **Plan gap** — the canonical course is **larger than the 30-node spine**. Several real chapters (LLMO, most of Part Three, the cross-cutting review chapters) have no `framework.json` address at all (see §5).

---

## 2. Legend

| Mark | Meaning |
|---|---|
| ✅ | Extracted and faithful to the canonical |
| 🟡 | Partial — extracted but condensed / missing named sub-topics |
| ❌ | Missing — canonical content, nothing extracted |
| ⚠️ | Structural drift / mismatch worth a decision |
| 🚫 | No spine address — canonical content `framework.json` doesn't even plan for |

---

## 3. Coverage matrix (by framework)

### CODE — the engagement · **0 of 4 extracted**

| Address | Chapter | Status | Canonical topics (extraction checklist) |
|---|---|---|---|
| `code.c` | Content | ❌ | Approval-states flow (Draft→…→Archived) · localization workflows (locale-as-market, MT-first-pass, translation memory; AEM MSM/Smartling/Lokalise/Phrase) · IA vs XML sitemap · content source & collection · approval workflow (owners, SLA per gate, audit trail) · DAM — 5 disciplines (structure, taxonomy, metadata IPTC/XMP/Dublin Core, expiry, AI for assets) · content velocity (cycle time, throughput, bottlenecks) |
| `code.o` | Operations & Martech | ❌ | Go-live sign-off chain · project management (DSM 3-questions, Jira/ProofHub, RACI) · campaign management (plan→build→launch→measure→iterate) · stakeholder expectation management (risk patterns) · go-live readiness (**DNS TTL reduction 48h ahead**) · SEO & GEO readiness + expectation setting |
| `code.d` | Design & Data | ❌ | Analytics vocabulary (event, dimension, metric, data layer, tag, report, segment, conversion, funnel) · **GA4 vs Adobe Analytics** · data-layer code example · Adobe Target personalization · segmentation (rule/A-B/MVT/auto) · **Adobe Analytics vs CJA** · the CDP (ingest/identity/unify/activate) · **the maturity ladder levels 0–6** · data lakes side-note |
| `code.e` | Engineering | — | Telescope node only (opens into CODER); no standalone prose to extract |

### CODER — inside engineering · **3 of 5 extracted** (one ✅, one 🟡, one 🟡; two ❌)

| Address | Chapter | Status | Notes |
|---|---|---|---|
| `coder.c` | Code | 🟡 | **Extracted = the Stalwart reference only** (8 files init/model/biz/api/render + config/state/events; naive-vs-Stalwart prompt; CI enforcement; architect-as-reviewer). The *real* `coder.c` telescopes into the 13 Anatomy modules — those live in the `anatomy` ring (12 of 13 missing, §Anatomy). ⚠️ Stalwart is also the spine's `anatomy.m12` → **double-addressed** (see §5). |
| `coder.o` | Optimization & Quality | ❌ | **Testing** (pyramid unit/integration/E2E, AAA vs Given-When-Then, coverage floor + mutation testing, AEM test layers io.wcm/HTL/CM/JMeter, CI <10 min) · **Page Speed** (Core Web Vitals LCP/INP/CLS, lab-vs-field Lighthouse/CrUX, critical rendering path, image formats AVIF>WebP, **JS budget 170/250KB**, fonts, AEM levers) · **Accessibility** (WCAG 2.2 AA, **POUR**, the **seven 80%-wins**, ARIA discipline, axe/NVDA/VoiceOver) |
| `coder.d` | Deployment | 🟡 | **Significantly condensed — see §4.1.** Extracted: 5 caching tiers · invalidation (TTL/purge/versioned) · observability (logs/metrics/traces, SLO/error budget, RED vs USE) · architect's review. **Missing from extraction:** the enumerated **ten layers** (the scan/opener promise "draw all ten" but only the 5 caching tiers are listed), cloud providers (AWS/Azure/GCP), **service models IaaS/PaaS/FaaS/SaaS**, autoscaling, log-file reading, plus the *deep* caching detail (stale-while-revalidate, surrogate keys, cache-aside/write-through/write-behind, eviction LRU/LFU, hot-key) and *deep* observability (SLI/SLA, distributed tracing/OpenTelemetry, synthetic-vs-RUM, burn-rate alerts) |
| `coder.e` | External Integrations | ❌ | Server-vs-client · API-gateway mediator · **auth menu** (API key/Basic/HMAC/OAuth 2.0/JWT/mTLS) · **OAuth four flows** (Auth-Code+PKCE, Client-Credentials, Device, Implicit-deprecated) · JWT (`alg:none` attack, RS256 vs HS256) · SSO (SAML/OIDC/SCIM/JIT) · worked examples (Google Maps, Google OAuth + the email/`sub` trap, WhatsApp Business API) · **payment gateways** (Stripe PaymentIntent vs Razorpay Order, PCI scope, idempotency, webhook-for-truth; Stripe/Razorpay/Adyen/PayU) · 3PL (Shiprocket/Delhivery/EasyPost) · webhooks (5 receiver rules) · failure modes (timeout/retry+backoff/circuit-breaker/bulkhead, Pact) |
| `coder.r` | Release Management | ✅ | **Near-complete.** Extracted 11 sub-sections track the canonical closely: branching (trunk/GitHub Flow/GitFlow) · commit hygiene + Conventional Commits · PRs **<400 lines** · branch protection (CODEOWNERS, signed commits, linear history) · promotion (**build once, promote many**) · deploy patterns (blue-green/canary/feature-flag) · merge-vs-rebase · versioning (**SemVer vs CalVer**) · hypercare & rollback · architect's review. Includes the gitGraph diagram and the worked commit example. |

### ANATOMY (telescoped under `coder.c`) · **1 of 14 extracted**

| Address | Module | Status | Canonical topics |
|---|---|---|---|
| `anatomy.m00` | The Mental Model | ✅ | Near-complete — every line answers When/Where/What/How/Who → Event/Function/Logic/Variable/Model; the 7-row question→home map; MVC seed |
| `anatomy.m01` | Design Patterns 101 | ❌ | Observer / Dispatcher / Strategy / Producer-Consumer on a sync×async × single×multi grid |
| `anatomy.m01b` | Patterns 201 | ❌ | Factory · Adapter · Facade · Repository · MVC · Event-Driven · State Machine · Chain of Responsibility (with AEM/EDS context) |
| `anatomy.m02` | The Primitives | ❌ | 5 primitives · **3 storage shapes** (simple/grouped/attached) · 3 storage lifetimes as a PII boundary |
| `anatomy.m02b` | Components | ❌ | 4 dimensions (state/events/render/config) · presentational-vs-container · "each component is a tiny Stalwart" |
| `anatomy.m03` | Functions · 3 Types | ❌ | Logical / Render / Feature-Helper · lifecycle helpers (initialize, go) |
| `anatomy.m04` | Events & Dispatcher | ❌ | Emit + receive sides · bus-element pattern · **`domain:entity:action` naming** · 3-step wiring · events.registry.js |
| `anatomy.m05` | State | ❌ | **state + event = new state** · 5 state kinds · single source of truth · model (shape) vs state (value) |
| `anatomy.m06` | Collections | ❌ | Strategy for sort & filter · manager indirection · AND-vs-OR composition · client-vs-server sort |
| `anatomy.m07` | Jobs & Queues | ❌ | Producer/Consumer · retries/throttling · **exponential backoff with jitter** |
| `anatomy.m08` | Configuration | ❌ | Code-vs-config boundary · flags/thresholds/endpoints/policies · "does this change with business/env/user?" |
| `anatomy.m09` | Code Structuring | ❌ | **Model / Function / Controller split** · folder enforcement |
| `anatomy.m10` | Contracts · Bridge | ❌ | **Four contracts** (API/Event/Data/Component) · the bridge to AI-generated code |
| `anatomy.m12` | Stalwart | ✅* | *Covered via `coder.c`* (the extracted Stalwart reference). ⚠️ No `anatomy-m12.json`; it lives in `coder-c.json`. Double-addressed — decide its home. |

### Adobe Stack (Part Two) · **0 of 5 extracted** + 1 unaddressed

| Address | Tool | Status | Canonical topics (count) |
|---|---|---|---|
| `adobe.cm` | Cloud Manager | ❌ | Pipeline stages (9) · quality gates · web-tier config · canary/blue-green in AEMaaCS · failure triage · SAST/CVE scanning · rollback (7 topics) |
| `adobe.aa` | Adobe Analytics | ❌ | Data-layer→variable mapping · report-suite strategy · processing rules · VISTA · eVar/prop allocation · classifications (SAINT) · data feeds · AA→CJA migration (8) |
| `adobe.cja` | CJA | ❌ | AEP→CJA connection · data-view governance · cross-channel stitching · calculated-metric governance · real-time personalisation · AA parity · latency (7) |
| `adobe.ajo` | AJO | ❌ | Stack position · journey types · XDM schema governance · channel governance · frequency capping · AEM integration · offer decisioning · testing/preview (8) |
| `adobe.camp` | Adobe Campaign | ❌ | Classic/Standard/v8 · delivery (IP pool, SPF/DKIM/DMARC) · IP warming · segmentation · frequency capping · AEM integration · bounce/unsubscribe · MID-sourcing (8) |
| 🚫 LLMO | LLM Optimisation | 🚫 | **Canonical chapter with no spine node.** Generative-search optimisation (answer-first, JSON-LD, **llms.txt**) · inference-cost architecture · prompt caching · multi-model orchestration · LLM personalisation · latency SLAs · content audit (7) |

### AI-Native (Part Three) · **0 of 2 extracted** + spine under-captures

| Address | Chapter | Status | Canonical |
|---|---|---|---|
| `ai.bmad` | BMAD | ❌ | 5-phase loop · hypothesis template · component inventory · **ADR format** · artefact dependency map · **worked example (product filter)** · the 6 BMAD artefacts |
| `ai.gov` | AI Governance | ❌ | AI-generates-vs-humans-govern · the **three things only humans own** |
| 🚫 | Prompt Architecture (III.1) | 🚫 | The five layers of a governed prompt (Identity/Contract/Rules/Output/Examples) — no spine node |
| 🚫 | Event Vocabulary (III.2) | 🚫 | What architects govern; the event registry — no spine node |
| 🚫 | Contract-Driven Dev (III.3) | 🚫 | Flow + the 4 contracts mapped to Stalwart files — no spine node |
| 🚫 | **AI Routing / Model Selection** (III.5) | 🚫 | The **17-row "don't route to AI" table** + the **7-tier model-selection table** (Haiku 4.5 / Sonnet 4.6 / Sonnet 4.7 / Opus 4.7–4.8 / Web Search / Manual tool use / CLI) + the 6-question decision rule — no spine node |
| 🚫 | The Horizon (III.6) | 🚫 | Selection-driven generator — no spine node |

### Cross-cutting · **unaddressed in spine**

| Item | Status | Canonical |
|---|---|---|
| 🚫 "How it all nests" (`#nest`) | 🚫 | The telescope explainer (CODE → E → CODER → C → Anatomy) |
| 🚫 "Executive Review Model" (`#review`) | 🚫 | 8 cards × 3 questions (one per CODE-CODER letter) |
| 🚫 "Who watches what" (`#watch`) | 🚫 | Architect-vs-PM oversight table for all 8 nodes |
| Recurring blocks (Architect's Review ×28, Scan Box ×33, Why/Tip/Pitfall/Before-After) | ✅ | The block **vocabulary is faithful** — the extracted sections use exactly these four callout variants + scan-box + architects-review; no fifth type introduced |

---

## 4. Drift & structural findings

**4.1 `coder.d` is the highest-priority partial.** The extracted Deployment chapter delivers ~half its own promise: the scan and the drop-cap opener both say "ten layers… an architect should be able to draw all ten," but the blocks only enumerate the **five caching tiers**. The canonical chapter is far richer — the full ten-layer request path, cloud-provider mapping, the IaaS/PaaS/FaaS/SaaS responsibility ladder, autoscaling, and a much deeper caching + observability treatment. **Finishing `coder.d` should rank above starting new chapters** — it currently reads as incomplete against its own framing.

**4.2 Stalwart is double-addressed.** The extracted `coder.c` *is* the Stalwart reference; the spine also lists Stalwart as `anatomy.m12`. Pick one canonical home (recommended: keep the Stalwart reference at `anatomy.m12` and let `coder.c` be the thin telescope into the Anatomy ring), or document the intentional overlap.

**4.3 `coder.c` carries the wrong altitude.** `coder.c` is a telescope node — its substance is the 13 Anatomy modules. The extracted `coder-c.json` carries Stalwart, not the module vocabulary; only `anatomy.m00` of those 13 exists. The conceptual core of the course (m01–m10) is the single largest missing cluster.

**4.4 The spine is smaller than the course.** `framework.json` plans 30 nodes, but the canonical has more: **LLMO**, four of Part Three's six sections, the **AI-routing/model-selection** content, the BMAD worked example, and the nest/review/watch trio all lack an address. The plan needs widening before "100% coverage" can mean "the whole course" (see §5).

**4.5 Spine numbering quirk.** `anatomy` jumps `m10 → m12` (no `m11`); `m01b`/`m02b` are sub-lettered. Mechanical, but relevant when matching IDs one-to-one.

---

## 5. `framework.json` corrections the canonical implies

- **Add `adobe.llmo`** — LLMO is a full canonical chapter with no node.
- **Widen the `ai` ring** — it has `bmad` + `gov`, but Part Three is six sections. Add nodes (or sub-addresses) for Prompt Architecture, Event Vocabulary, Contract-Driven Dev, **AI Routing / Model Selection**, and The Horizon.
- **Resolve Stalwart's home** — `coder.c` vs `anatomy.m12` (currently both).
- **Decide on the cross-cutting chapters** — `#nest`, `#review`, `#watch` are real authored content with no address; either give them addresses or record that they're chrome, not chapters.

---

## 6. Suggested extraction order (close the gap)

1. **Finish `coder.d`** — add the ten layers, service models, autoscaling, and the deep caching + observability detail. It already promises this content.
2. **Extract Anatomy `m01`–`m10`** — the conceptual core; `coder.c` telescopes into them; only `m00` is done.
3. **Extract `coder.o` + `coder.e`** — the two missing CODER letters (Optimization & Quality; External Integrations).
4. **Extract the CODE ring** — `code.c` / `code.o` / `code.d` (the outer engagement; `code.d` carries the maturity ladder).
5. **Adobe Stack** — `adobe.cm/aa/cja/ajo/camp`, and add `adobe.llmo`.
6. **Part Three** — extract `ai.bmad` + `ai.gov`, and widen the ring to cover Prompt Architecture, Event Vocabulary, Contract-Driven Dev, AI Routing/Model Selection, The Horizon.
7. **Cross-cutting** — `#nest` / `#review` / `#watch`.

---

## 7. Provenance & method

- Canonical outline extracted from `content-system/anatomy-of-code-course.html` (the repo's copy), and **verified content-equivalent** to the live `internal.in.deptagency.com/anatomy-of-code-course.html` via targeted fetches against distinctive fingerprints (Adobe Stack incl. LLMO, the maturity ladder 0–6, the ten deployment layers, BMAD, Who-Watches-What, AI routing).
- Extracted inventory read directly from `content-architecture/course/sections/*.json` + `framework.json`.
- "Coverage" counts the planned spine (30 nodes). True coverage of the *whole course* is lower, because the canonical exceeds the spine (§4.4).
- Read-only analysis — no course content was modified to produce this report.
