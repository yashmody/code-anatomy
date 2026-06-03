// =================================================================
// cache.ts · stale-while-revalidate AsyncStorage cache
// =================================================================
//
// Wraps any async fetcher with two-tier caching:
//   1. Return stale immediately if we have it (renders fast).
//   2. Refresh in the background, notify if updated.
//
// Used by every screen that lists or fetches articles. The user sees
// content within milliseconds on warm starts; fresh content appears
// shortly after.
//
// Discipline:
//   - This file owns persistence — nothing else writes to AsyncStorage.
//   - TTL is advisory; we never block on freshness. Network failure
//     surfaces stale data, not an error screen.
//   - Keys are stable strings the caller controls. No magic key derivation.

import AsyncStorage from "@react-native-async-storage/async-storage";

interface CacheEntry<T> {
  data: T;
  writtenAt: number;  // epoch ms
}

const KEY_PREFIX = "aem-cache:v1:";

function k(key: string): string {
  return KEY_PREFIX + key;
}

/** Read a cached value. Returns null if missing or unparseable. */
async function readCache<T>(key: string): Promise<CacheEntry<T> | null> {
  try {
    const raw = await AsyncStorage.getItem(k(key));
    if (!raw) return null;
    return JSON.parse(raw) as CacheEntry<T>;
  } catch {
    return null;
  }
}

async function writeCache<T>(key: string, data: T): Promise<void> {
  const entry: CacheEntry<T> = { data, writtenAt: Date.now() };
  try {
    await AsyncStorage.setItem(k(key), JSON.stringify(entry));
  } catch {
    // Disk full or quota exceeded — silently swallow; cache is advisory.
  }
}

export interface SwrResult<T> {
  data: T | null;
  isStale: boolean;
  ageMs: number | null;
  error: Error | null;
}

/**
 * Stale-while-revalidate fetch.
 * Calls `onUpdate` once when fresh data arrives (which may be immediately
 * if no cache existed, or after the network round-trip if it did).
 *
 * Usage:
 *   useEffect(() => {
 *     swr('articles:home', () => listArticles(), (result) => {
 *       setArticles(result.data ?? []);
 *       setLoading(result.data === null && result.error === null);
 *     });
 *   }, []);
 */
export async function swr<T>(
  key: string,
  fetcher: () => Promise<T>,
  onUpdate: (result: SwrResult<T>) => void,
  options: { maxAgeMs?: number } = {}
): Promise<void> {
  const maxAge = options.maxAgeMs ?? 5 * 60 * 1000; // 5 minutes default

  // 1. Emit cached value immediately (if present).
  const cached = await readCache<T>(key);
  if (cached) {
    const ageMs = Date.now() - cached.writtenAt;
    onUpdate({
      data: cached.data,
      isStale: ageMs > maxAge,
      ageMs,
      error: null,
    });
  }

  // 2. Fetch in the background.
  try {
    const fresh = await fetcher();
    await writeCache(key, fresh);
    onUpdate({ data: fresh, isStale: false, ageMs: 0, error: null });
  } catch (err) {
    // Surface error only if we have no cache to fall back on.
    if (!cached) {
      onUpdate({
        data: null,
        isStale: false,
        ageMs: null,
        error: err instanceof Error ? err : new Error(String(err)),
      });
    }
    // Otherwise: silent failure — user sees stale data, which is the SWR contract.
  }
}

/** Invalidate one key. Used after content events (e.g. user pulls to refresh). */
export async function invalidate(key: string): Promise<void> {
  try {
    await AsyncStorage.removeItem(k(key));
  } catch {
    // ignore
  }
}

/** Invalidate every cache entry. Used on logout or content reset. */
export async function purgeAll(): Promise<void> {
  try {
    const allKeys = await AsyncStorage.getAllKeys();
    const ours = allKeys.filter((x) => x.startsWith(KEY_PREFIX));
    if (ours.length) await AsyncStorage.multiRemove(ours);
  } catch {
    // ignore
  }
}
