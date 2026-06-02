# 00 · Architecture Prompt

The first prompt — the contract every later prompt inherits from. Run this once at the start of the project, in a fresh agent-coding session. It defines the file layout, the layering rules, and the discipline the AI must obey before it generates anything else.

This is the equivalent of the Stalwart contract for AEM → mobile work.

---

## The prompt

```
You are building a React Native (Expo) sample app that consumes content
from Adobe Experience Manager (AEM) via persisted GraphQL queries.

The architecture is deliberately layered. Every file you produce must
belong to exactly one of these layers, and must not violate the rules
of its layer.

LAYER 1 — model.ts
  Purpose: TypeScript interfaces and types that mirror the AEM Content
  Fragment models 1:1.
  Allowed: type definitions, type guards, pure derivation helpers
  (e.g. isNew(date)).
  Forbidden: HTTP calls, persistence, React, anything stateful.

LAYER 2 — api.ts
  Purpose: the ONLY file in the project that knows the AEM HTTP API
  exists.
  Allowed: fetch(), persisted query URLs, request/response shapes,
  ApiError class.
  Forbidden: caching, persistence, React, UI concerns.

LAYER 3 — cache.ts
  Purpose: the ONLY file that touches AsyncStorage. Implements
  stale-while-revalidate.
  Allowed: AsyncStorage.* calls, TTL helpers, cache-key prefixing.
  Forbidden: HTTP, React, UI concerns, knowing what's being cached
  beyond a generic <T>.

LAYER 4 — components/*.tsx
  Purpose: small, presentational React components. Receive data via
  props; emit events via callbacks.
  Allowed: View, Text, Image, Pressable, StyleSheet.
  Forbidden: fetching, navigation, AsyncStorage, business logic.

LAYER 5 — screens/*.tsx
  Purpose: composition. Wire components, api.ts and cache.ts together
  to produce a screen.
  Allowed: useState, useEffect, useCallback, calls to api.ts and
  cache.ts, composition of components.
  Forbidden: defining new visual primitives, talking to fetch()
  directly (must go through api.ts), reading from AsyncStorage
  directly (must go through cache.ts).

LAYER 6 — App.tsx
  Purpose: root, configuration, simple route state.
  Allowed: configureClient() once at startup, route state, mounting
  one screen at a time.
  Forbidden: anything that belongs in a screen.

RULES FOR EVERY FILE
  - TypeScript strict mode. No `any`. No `@ts-ignore`.
  - File header comment explaining what the file is FOR and what it
    is FORBIDDEN from doing.
  - No business logic in JSX. If a screen has more than 30 lines of
    logic, extract it to a helper.
  - Errors thrown by api.ts are caught in screens and translated to
    UI state — never bubbled to the user as raw exceptions.

Confirm you understand this contract before generating any file.
When generating a file, output the full file contents and nothing else.
```

## Why this prompt

Without this contract, an AI will conflate concerns by default:
- Fetch logic inside a component
- AsyncStorage calls scattered across screens
- Cache TTL hardcoded in three different places
- Untyped JSON shapes flowing through render code

With the contract in place, each subsequent file generation has a
fixed lane to stay in. The AI's quality on the second file is much
higher than on the first, because the first file already established
the pattern.

## What follows

After this prompt, ask the agent to read `aem-side/article-model.json`
and `aem-side/persisted-queries.graphql`, then proceed to prompts
01 through 04 in order.
