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

// Persist caps so one big payload (a topology graph, a records page) can never
// blow the ~5MB localStorage budget and wipe everything.
const MAX_ENTRY_BYTES = 256 * 1024; // skip persisting entries larger than this
const MAX_TOTAL_BYTES = 4 * 1024 * 1024; // total persisted budget

let _flushTimer: ReturnType<typeof setTimeout> | null = null;
function _persist(): void {
  if (!_hasWindow || _flushTimer) return;
  // Debounce: batch bursts of set() calls into a single write.
  _flushTimer = setTimeout(() => {
    _flushTimer = null;
    try {
      // Newest-first so the freshest small entries survive the budget.
      const entries = [..._store.entries()].sort((a, b) => b[1].ts - a[1].ts);
      const obj: Record<string, unknown> = {};
      let total = 0;
      for (const [k, v] of entries) {
        const s = JSON.stringify(v);
        if (s.length > MAX_ENTRY_BYTES) continue; // too big — in-memory only
        if (total + s.length > MAX_TOTAL_BYTES) break; // budget exhausted
        obj[k] = v;
        total += s.length;
      }
      window.localStorage.setItem(LS_KEY, JSON.stringify(obj));
    } catch {
      // Still over quota — drop the blob rather than leaving a corrupt one.
      // In-memory cache is unaffected.
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

/**
 * Return cached data if present, IGNORING TTL. Use for instant "buffer" renders
 * (show whatever we last had immediately) paired with a background revalidate.
 */
export function peek<T>(key: string): T | null {
  const e = _store.get(key) as Entry<T> | undefined;
  return e ? e.data : null;
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
