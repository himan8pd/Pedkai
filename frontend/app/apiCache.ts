/**
 * Module-level API response cache with TTL and stale-while-revalidate support.
 *
 * Lives at module scope so it persists across React component mount/unmount
 * cycles (i.e. navigation). This gives instant "previous state" loads when
 * a user revisits a page — the cached data renders immediately while a fresh
 * fetch runs silently in the background.
 *
 * Usage:
 *   import * as Cache from "@/lib/apiCache";
 *   const cached = Cache.get<MyType>(key, Cache.TTL.MEDIUM);
 *   if (cached) setState(cached);
 *   // Always fetch fresh (stale-while-revalidate)
 *   const fresh = await fetch(...);
 *   Cache.set(key, fresh);
 */

type Entry<T> = { data: T; ts: number };
const _store = new Map<string, Entry<unknown>>();

/** Pre-defined TTL buckets (milliseconds). */
export const TTL = {
  /** 30 s — alarms, live incident lists */
  SHORT: 30_000,
  /** 5 min — scorecard, sleeping cells results */
  MEDIUM: 5 * 60_000,
  /** 15 min — topology graph, divergence reconciliation results */
  LONG: 15 * 60_000,
};

/** Return cached data if it exists and is within TTL, otherwise null. */
export function get<T>(key: string, ttl: number): T | null {
  const e = _store.get(key) as Entry<T> | undefined;
  if (!e) return null;
  if (Date.now() - e.ts > ttl) return null;
  return e.data;
}

/** Store data in the cache. */
export function set<T>(key: string, data: T): void {
  _store.set(key, { data, ts: Date.now() });
}

/**
 * Remove cache entries whose key starts with `prefix`.
 * Pass no argument to clear everything (e.g. on logout).
 */
export function clear(prefix?: string): void {
  if (!prefix) {
    _store.clear();
    return;
  }
  for (const k of _store.keys()) {
    if (k.startsWith(prefix)) _store.delete(k);
  }
}

/** How old (in seconds) is the cached entry? Returns null if not cached. */
export function ageSeconds(key: string): number | null {
  const e = _store.get(key);
  if (!e) return null;
  return Math.round((Date.now() - e.ts) / 1000);
}
