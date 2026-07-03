/**
 * API response cache with TTL, stale-while-revalidate, AND cross-reload
 * persistence.
 *
 * The Map lives at module scope so it survives React mount/unmount cycles
 * (SPA navigation). In addition, every write is mirrored to `localStorage`,
 * and the store is hydrated from it on load — so the buffer also survives a
 * full page refresh (F5). Revisiting a page renders the previous data
 * instantly while a fresh fetch runs silently in the background.
 *
 * Usage:
 *   import * as Cache from "@/app/apiCache";
 *   const cached = Cache.get<MyType>(key, Cache.TTL.MEDIUM);
 *   if (cached) setState(cached);            // instant render
 *   const fresh = await fetch(...);          // stale-while-revalidate
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

// ── Persistence (localStorage) ─────────────────────────────────────────────
const LS_KEY = "pedkai:apiCache:v1";
const _hasWindow = typeof window !== "undefined";
// Drop persisted entries older than this on hydrate, to bound storage size.
const MAX_PERSIST_AGE = 30 * 60_000; // 30 min

// Hydrate the in-memory store from localStorage on module load.
if (_hasWindow) {
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (raw) {
      const obj = JSON.parse(raw) as Record<string, Entry<unknown>>;
      const now = Date.now();
      for (const [k, v] of Object.entries(obj)) {
        if (v && typeof v.ts === "number" && now - v.ts <= MAX_PERSIST_AGE) {
          _store.set(k, v);
        }
      }
    }
  } catch {
    /* corrupt/unavailable — start empty */
  }
}

let _flushTimer: ReturnType<typeof setTimeout> | null = null;
function _persist(): void {
  if (!_hasWindow || _flushTimer) return;
  // Debounce: batch bursts of set() calls into a single write.
  _flushTimer = setTimeout(() => {
    _flushTimer = null;
    try {
      const obj: Record<string, unknown> = {};
      for (const [k, v] of _store.entries()) obj[k] = v;
      window.localStorage.setItem(LS_KEY, JSON.stringify(obj));
    } catch {
      // Quota exceeded or blocked — the in-memory cache still works. Drop the
      // persisted blob so a partial/corrupt value never lingers.
      try {
        window.localStorage.removeItem(LS_KEY);
      } catch {
        /* ignore */
      }
    }
  }, 250);
}

/** Return cached data if it exists and is within TTL, otherwise null. */
export function get<T>(key: string, ttl: number): T | null {
  const e = _store.get(key) as Entry<T> | undefined;
  if (!e) return null;
  if (Date.now() - e.ts > ttl) return null;
  return e.data;
}

/** Store data in the cache (and mirror to localStorage). */
export function set<T>(key: string, data: T): void {
  _store.set(key, { data, ts: Date.now() });
  _persist();
}

/**
 * Remove cache entries whose key starts with `prefix`.
 * Pass no argument to clear everything (e.g. on logout).
 */
export function clear(prefix?: string): void {
  if (!prefix) {
    _store.clear();
  } else {
    for (const k of _store.keys()) {
      if (k.startsWith(prefix)) _store.delete(k);
    }
  }
  _persist();
}

/** Remove a single cache entry by exact key. */
export function del(key: string): void {
  _store.delete(key);
  _persist();
}

/** How old (in seconds) is the cached entry? Returns null if not cached. */
export function ageSeconds(key: string): number | null {
  const e = _store.get(key);
  if (!e) return null;
  return Math.round((Date.now() - e.ts) / 1000);
}
