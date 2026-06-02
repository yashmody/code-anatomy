# 02 · API Prompt

Generates `rn-app/src/lib/api.ts` — the only file in the project that
knows AEM's HTTP API exists. Built on top of model.ts and the persisted
GraphQL queries.

---

## Prerequisite

Prompts 00 and 01 already run. `model.ts` exists.

## The prompt

```
Read aem-side/persisted-queries.graphql and rn-app/src/lib/model.ts.

Generate rn-app/src/lib/api.ts following the LAYER 2 rules.

Requirements:
1. Define an AemClientConfig interface: baseUrl, namespace, optional
   authToken, optional timeoutMs (default 8000).
2. Define configureClient(cfg) that captures config in a module-scope
   variable. Subsequent calls overwrite.
3. Internal fetchPersisted<T>(queryName, variables) function that:
   - Constructs URL: ${baseUrl}/graphql/execute.json/${namespace}/${queryName}
   - Appends variables as URL-encoded query params (skipping null/undefined)
   - Adds Authorization header if authToken configured
   - Uses AbortController for the timeout
   - Throws ApiError(message, status) on HTTP failure or abort
   - Returns the parsed JSON response
4. ApiError class extending Error with a numeric `status` field.
5. One public function per persisted query, mirroring the GraphQL
   queries file. Names and parameter shapes must match the .graphql
   exactly:
   - listArticles({ category?, limit?, offset? }) → ArticleSummary[]
   - featuredArticles(limit?) → ArticleSummary[]
   - articleBySlug(slug) → Article | null  (null if no result)
6. Every public function returns typed data unwrapped from the response
   envelope (so callers don't see resp.data.articleList.items — they
   see the items array).

Do NOT add caching, retry logic, or offline handling here. Those belong
in cache.ts (LAYER 3).

Output the file content only.
```

## What this prompt teaches

That fetching from AEM is one of those problems where the right code
is 90% boilerplate and 10% decision. The 10% decision is encoded once
in the prompt; the 90% boilerplate is generated. The next time you
need a new persisted query function, you append one bullet to this
prompt and re-run.

## What to verify

- [ ] No reference to AsyncStorage, no caching logic, no React
- [ ] AbortController + timeout actually wired (not just declared)
- [ ] Errors thrown as ApiError, never plain Error or raw fetch errors
- [ ] Function signatures match the persisted queries
- [ ] articleBySlug returns null for not-found, not an array

## Next prompt

03-cache-prompt.md generates the AsyncStorage SWR layer.
