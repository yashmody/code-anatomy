# AEM → React Native · agent-coded sample

A worked example showing how to turn an AEM Content Fragment model into
a typed, cached, branded React Native app — built with agentic coding
against a fixed architectural contract.

This is the same pattern as **Stalwart** (DEPT®'s internal feature
framework for AI-generated code), applied to AEM-headless mobile work.
The point isn't the app — it's the prompt sequence in `prompts/` that
generates the app. Read those first.

---

## What this sample teaches

1. **AEM CFM → typed TypeScript is a one-shot generation.** When the
   Content Fragment model is well-defined and the persisted GraphQL
   queries match it, a single prompt generates `model.ts` correctly.

2. **Persisted GraphQL queries are the contract.** The app calls a URL,
   never a query body. The wire shape is stable, CDN-cacheable, and
   reviewed once on the AEM side.

3. **Stale-while-revalidate is the right caching pattern for
   AEM-headless mobile.** Editors publish often; users open often;
   users hit network glitches. SWR makes "cached wins, fresh wins
   shortly after" the default behaviour.

4. **A small architectural contract yields short prompts everywhere
   else.** Once layers are defined (LAYER 1: types, LAYER 2: HTTP,
   LAYER 3: persistence, LAYER 4: components, LAYER 5: composition,
   LAYER 6: app shell), every later prompt is two paragraphs.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  AEM (Author + Publish)                                      │
│                                                              │
│   ┌─────────────────────┐    ┌──────────────────────────┐    │
│   │ CF Model            │    │ Persisted GraphQL Query  │    │
│   │ article-model.json  │───▶│ persisted-queries.graphql│    │
│   │ (the schema)        │    │ (the read contract)      │    │
│   └─────────────────────┘    └────────────┬─────────────┘    │
│                                           │                  │
└───────────────────────────────────────────┼──────────────────┘
                                            │
                              GET /graphql/execute.json/
                              dept-sample/list-articles?...
                                            │
                                            ▼
┌──────────────────────────────────────────────────────────────┐
│  React Native (Expo)                                         │
│                                                              │
│   ┌──────────────────────────────────────────────────────┐   │
│   │  LAYER 1 · model.ts                                  │   │
│   │  Typed mirror of CF models. No HTTP. No persistence. │   │
│   └─────────┬────────────────────────────────────────────┘   │
│             ▲                                                │
│             │ types only                                     │
│   ┌─────────┴────────────────────────────────────────────┐   │
│   │  LAYER 2 · api.ts                                    │   │
│   │  Only file that knows fetch() exists.                │   │
│   │  Calls persisted queries by name.                    │   │
│   └─────────┬────────────────────────────────────────────┘   │
│             ▲                                                │
│             │ typed functions                                │
│   ┌─────────┴────────────────────────────────────────────┐   │
│   │  LAYER 3 · cache.ts                                  │   │
│   │  Only file that touches AsyncStorage.                │   │
│   │  Stale-while-revalidate wrapper.                     │   │
│   └─────────┬────────────────────────────────────────────┘   │
│             ▲                                                │
│             │ swr(key, fetcher, onUpdate)                    │
│   ┌─────────┴────────────────────────────────────────────┐   │
│   │  LAYER 5 · screens/                                  │   │
│   │  Composition. useState + swr() + components.         │   │
│   │  Home · ArticleDetail · Category                     │   │
│   └─────────┬────────────────────────────────────────────┘   │
│             │ uses                                           │
│   ┌─────────┴────────────────────────────────────────────┐   │
│   │  LAYER 4 · components/                               │   │
│   │  Pure presentational. ArticleCard, HeroImage,        │   │
│   │  AuthorChip, CategoryPill, EmptyState.               │   │
│   └──────────────────────────────────────────────────────┘   │
│                                                              │
│   ┌──────────────────────────────────────────────────────┐   │
│   │  LAYER 6 · App.tsx                                   │   │
│   │  Root + tiny route reducer. Mounts one screen.       │   │
│   └──────────────────────────────────────────────────────┘   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

Each box has rules in `prompts/00-architecture-prompt.md` — what it
must do, what it must not do. The AI obeys the layering because the
prompt enforces it before generating any file.

---

## Folder layout

```
aem-rn-sample/
├── aem-side/
│   ├── article-model.json         · CF model definition (authoring side)
│   └── persisted-queries.graphql  · the three queries the app calls
│
├── rn-app/
│   ├── App.tsx                    · root, route state, AEM client config
│   ├── app.config.ts              · Expo config (env wiring)
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── lib/
│       │   ├── model.ts           · LAYER 1 · typed CF shapes
│       │   ├── api.ts             · LAYER 2 · persisted GraphQL client
│       │   └── cache.ts           · LAYER 3 · SWR over AsyncStorage
│       ├── components/            · LAYER 4 · presentational
│       │   ├── ArticleCard.tsx
│       │   ├── HeroImage.tsx
│       │   ├── AuthorChip.tsx
│       │   ├── CategoryPill.tsx
│       │   └── EmptyState.tsx
│       └── screens/               · LAYER 5 · composition
│           ├── HomeScreen.tsx
│           ├── ArticleDetailScreen.tsx
│           └── CategoryScreen.tsx
│
└── prompts/                       · the agent-coding sequence
    ├── 00-architecture-prompt.md
    ├── 01-model-prompt.md
    ├── 02-api-prompt.md
    ├── 03-cache-prompt.md
    └── 04-screens-prompts.md
```

---

## AEM setup

1. **Install the Content Fragment models.** Create
   `/conf/dept-sample/settings/dam/cfm/models/article` matching the
   shape in `aem-side/article-model.json`. The sibling `author` model
   is referenced from `Article` and must exist first.

2. **Author content.** Create a folder
   `/content/dam/dept-sample/articles/` and publish a few articles
   using the model. Tag one or two as `isFeatured`.

3. **Install the persisted queries.** From AEM, run for each query in
   `aem-side/persisted-queries.graphql`:

   ```bash
   curl -X PUT \
     "$AEM/graphql/persist.json/dept-sample/list-articles" \
     --data-binary @list-articles.graphql
   ```

   (Equivalent for `article-by-slug` and `featured-articles`.)

4. **Verify the endpoints.** Hit
   `https://<your-publish>/graphql/execute.json/dept-sample/list-articles`
   in a browser. JSON should come back.

## Running the app

```bash
cd rn-app
npm install

# Set AEM endpoint
export AEM_BASE_URL=https://publish-p123-e456.adobeaemcloud.com
export AEM_NAMESPACE=dept-sample
# Optional, only if your endpoints are protected:
# export AEM_AUTH_TOKEN="Bearer <token>"

# Start Metro
npm start
# Then press i (iOS), a (Android), or w (web)
```

---

## What this proves

- **AEM headless → mobile is hours, not weeks**, when the contract
  (CF model + persisted queries) is well-defined before code starts.
- **Agentic coding scales with architectural discipline, not with
  prompt cleverness.** The 80-line architecture prompt in `prompts/00`
  is the most valuable file in the project.
- **One stack of layered files beats five files of mixed concerns.**
  The hardest bugs in AEM-mobile work come from caching and HTTP being
  intertwined with rendering. The layering makes that impossible by
  construction.

## What this doesn't solve

- **Authentication.** Anonymous publish content only. For protected
  endpoints, wire an OAuth flow before `configureClient()`.
- **Complex personalisation.** No Target / AJO integration. For
  personalised content, you'd add a personalisation layer that runs
  before LAYER 2 and decides which query variant to call.
- **Offline-first conflict resolution.** SWR returns stale on failure;
  it doesn't queue writes or sync deltas. For full offline-first, you'd
  add a queue layer between LAYER 3 and the network.
- **Rich body rendering.** Demo strips HTML to text. In production,
  use `react-native-render-html` or convert AEM body to Markdown
  upstream.

---

## Pairs with

- **Course** — `anatomy-of-code-course.html` (the framework this sample
  obeys)
- **Stalwart** — covered in the course's CODER · C section (the
  original pattern this sample extends to mobile)
- **Runbook** — `architect-runbook.html` (the engagement playbook this
  sample is built inside of)
