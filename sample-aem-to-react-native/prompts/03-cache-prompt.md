# 03 · Cache Prompt

Generates `rn-app/src/lib/cache.ts` — the only file that touches
AsyncStorage, wrapped in a stale-while-revalidate contract.

---

## The prompt

```
Generate rn-app/src/lib/cache.ts following LAYER 3 rules.

Requirements:
1. CacheEntry<T> shape: { data: T, writtenAt: number (epoch ms) }
2. All keys are prefixed with "aem-cache:v1:" — single prefix point so
   future cache versioning is one constant change.
3. Internal readCache<T>(key) and writeCache<T>(key, data). Both
   absorb errors silently — the cache is advisory; a failed write or
   parse must not crash the app.
4. Public swr<T>(key, fetcher, onUpdate, options) function with this
   contract:
   - Step 1: read the cache. If hit, call onUpdate immediately with
     { data, isStale, ageMs, error: null }. isStale = ageMs > maxAge.
   - Step 2: call fetcher(). On success: write to cache, call
     onUpdate with fresh data, isStale: false, ageMs: 0.
   - Step 3: on fetcher() failure: surface the error to onUpdate ONLY
     IF there was no cached value to fall back on. Otherwise: swallow
     the error silently.
5. Default maxAgeMs: 5 minutes.
6. invalidate(key) removes a single entry. purgeAll() removes every
   entry under our prefix.
7. SwrResult<T> shape: { data: T | null, isStale: boolean,
   ageMs: number | null, error: Error | null }.

Do NOT add: HTTP, retry logic, mutex/locking, key derivation magic.

Output the file content only.
```

## Why SWR specifically

Three reasons SWR is the right caching pattern for AEM-backed mobile:

1. **Author velocity vs perceived perf.** Editors publish multiple
   times a day; users open the app multiple times an hour. The user
   should see content immediately and get freshness shortly after —
   not block on a network round-trip every launch.

2. **Network is unreliable on mobile.** A user on the subway must see
   yesterday's content, not an error screen. SWR makes "stale cache
   wins on network failure" the default behaviour, not a special case.

3. **CDN aligns with SWR.** AEM's persisted queries are CDN-cacheable
   by URL. SWR on the client + CDN cache at the edge gives two-tier
   caching with consistent invalidation — both refresh on author
   publish, both fall back to stale on failure.

## What to verify

- [ ] swr() calls onUpdate at least once even if cache is empty AND
      fetcher fails (the error path)
- [ ] writeCache failures don't propagate
- [ ] purgeAll only touches keys under aem-cache:v1: prefix
- [ ] No exported types leak AsyncStorage internals

## Next prompt

04-screens-prompts.md generates the UI layer.
