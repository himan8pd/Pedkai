# Frontend Architecture Audit Report

**Date:** 2026-03-10
**Project:** Pedkai NOC Command Center
**Directory:** `/Users/himanshu/Projects/Pedkai/frontend`

---

## Executive Summary

The Pedkai frontend is a **Next.js 16.1.6** application using React 19.2.3 with TypeScript. The architecture follows App Router conventions with a clean separation of layout, pages, and reusable components. The codebase totals **3,069 lines** of TypeScript/TSX code (excluding tests, node_modules, and build artifacts).

**Key characteristics:**
- Client-side rendering (`"use client"` directives on interactive components)
- Static export capability for cloud deployment (via `next.config.ts` conditional export)
- Auth context provider pattern for multi-tenant support
- Tailwind CSS 4 with custom brand color palette
- API-driven architecture communicating with backend at `/api/v1/*` endpoints

---

## Directory Structure & Files

### Root Level

```
/frontend/
├── app/                           # Next.js App Router directory
├── public/                        # Static assets (logo, favicon)
├── lib/                          # Shared utility functions
├── node_modules/                 # Dependencies
├── .next/                        # Build output
├── package.json                  # Dependencies & scripts
├── package-lock.json
├── next.config.ts               # Next.js configuration
├── tsconfig.json                # TypeScript configuration
├── tailwind.config.ts            # Tailwind CSS 4 config
├── postcss.config.mjs            # PostCSS configuration
├── eslint.config.mjs             # ESLint rules
├── Dockerfile                    # Container image
├── .dockerignore
├── .gitignore
└── README.md
```

### App Directory Structure

```
app/
├── layout.tsx                    # Root layout (28 lines)
│   └── Wraps AuthLayout, sets metadata
├── layout-auth.tsx               # Auth & tenant selection (302 lines)
│   └── Handles login, tenant selection, context provision
├── page.tsx                      # Home page → redirect (8 lines)
├── globals.css                   # Global styles & CSS variables
├── context/
│   └── AuthContext.tsx           # Auth context provider (42 lines)
├── components/
│   ├── Navigation.tsx            # Top navigation bar (133 lines)
│   ├── Dashboard.tsx             # Dashboard component wrapper (95 lines)
│   ├── IngestionControlPanel.tsx # Data ingestion UI (211 lines)
│   ├── SitrepPanel.tsx           # Situation report panel (125 lines)
│   ├── AlarmCard.tsx             # Alarm display card (41 lines)
│   ├── StatCard.tsx              # Statistics card (19 lines)
│   └── FeedbackWidget.tsx        # Feedback submission (89 lines)
├── dashboard/
│   └── page.tsx                  # Dashboard page (142 lines)
├── incidents/
│   └── page.tsx                  # Incidents list & detail (493 lines)
├── scorecard/
│   └── page.tsx                  # Autonomous scorecard (427 lines)
├── divergence/
│   └── page.tsx                  # Configuration divergence report (676 lines)
├── topology/
│   └── page.tsx                  # Network topology visualization (664 lines)
├── roi/
│   └── page.tsx                  # ROI dashboard (299 lines)
├── gtm-demo/
│   └── page.tsx                  # Go-to-market demo page (285 lines)
└── page-slim.tsx                 # Alternate slim page layout (8 lines)
```

### Supporting Files

```
lib/
└── utils.ts                      # Tailwind className utility (6 lines)
```

---

## Line Count Summary

### Page Routes (Route Handlers)
| File | Lines | Purpose |
|------|-------|---------|
| `app/page.tsx` | 8 | Home → `/dashboard` redirect |
| `app/dashboard/page.tsx` | 142 | Main dashboard with scorecard & alarms |
| `app/incidents/page.tsx` | 493 | Incident list, search, detail view |
| `app/scorecard/page.tsx` | 427 | Autonomous system scorecard & metrics |
| `app/divergence/page.tsx` | 676 | Configuration drift detection & reporting |
| `app/topology/page.tsx` | 664 | Network topology graph & search |
| `app/roi/page.tsx` | 299 | ROI dashboard & metrics |
| `app/gtm-demo/page.tsx` | 285 | Demo/GTM showcase page |
| **Subtotal** | **2,986** | Route pages |

### Layouts & Auth
| File | Lines | Purpose |
|------|-------|---------|
| `app/layout.tsx` | 28 | Root layout, metadata, font setup |
| `app/layout-auth.tsx` | 302 | Auth provider, login/tenant selection UI |
| `app/context/AuthContext.tsx` | 42 | React context for token & tenant |
| **Subtotal** | **372** | Layouts & context |

### Components
| File | Lines | Purpose |
|------|-------|---------|
| `app/components/IngestionControlPanel.tsx` | 211 | Data pipeline & divergence generation |
| `app/components/Navigation.tsx` | 133 | Top nav with data status |
| `app/components/SitrepPanel.tsx` | 125 | Situation report sidebar panel |
| `app/components/FeedbackWidget.tsx` | 89 | Feedback submission form |
| `app/components/Dashboard.tsx` | 95 | Dashboard layout wrapper |
| `app/components/AlarmCard.tsx` | 41 | Individual alarm display |
| `app/components/StatCard.tsx` | 19 | Statistics card |
| **Subtotal** | **713** | Reusable components |

### Utilities & Config
| File | Lines | Purpose |
|------|-------|---------|
| `lib/utils.ts` | 6 | `cn()` className merger |
| **Total Frontend Code** | **3,069** | Excludes node_modules, .next, tests |

---

## React Components Defined in Key Files

### `page.tsx` (Home Page)
**Total lines: 8**

```typescript
export default function Home() {
  // Redirect to dashboard — frontend decomposed into routed pages (P1.8)
  redirect('/dashboard')
}
```
**Components:** 1 (`Home` → redirects, no UI)

### `layout.tsx` (Root Layout)
**Total lines: 28**

```typescript
export default function RootLayout({ children })
// Sets:
// - Metadata: title "pedk.ai | NOC Command Center"
// - Font: Inter from next/font/google
// - AuthLayout provider wrapper
```
**Components:** 1 (`RootLayout`)

### `layout-auth.tsx` (Authentication Layout)
**Total lines: 302**

```typescript
export default function AuthLayout({ children })
// Components/Functions:
//   - handleLogout()
//   - handleLogin()
//   - handleTenantSelect()
//   - Conditional rendering: login form → tenant selector → app
//   - Phase state machine: 'login' | 'tenant-select' | 'app'
```
**Components:** 1 (`AuthLayout`) with 3 major handler functions

### Page Route Examples

#### `dashboard/page.tsx` (142 lines)
```typescript
export default function DashboardPage()
// Functions:
//   - fetchScorecard() → GET /api/v1/autonomous/scorecard
//   - useEffect() → EventSource for streaming alarms
// Renders:
//   - Dashboard component
//   - SitrepPanel component
//   - IngestionControlPanel component
```

#### `incidents/page.tsx` (493 lines)
```typescript
export default function IncidentsPage()
// Functions:
//   - fetchIncidents() → GET /api/v1/incidents/
//   - searchIncidents() → /api/v1/incidents/search
//   - getIncidentDetail() → /api/v1/incidents/{id}
// State:
//   - incidents[], selectedIncident, searchTerm, pagination
// Renders:
//   - Incident table with sorting & filtering
//   - Incident detail modal
```

#### `topology/page.tsx` (664 lines)
```typescript
export default function TopologyPage()
// Functions:
//   - fetchGraph() → GET /api/v1/topology/{tenantId}/neighborhood/{seed}?hops={n}
//   - searchQuery() → GET /api/v1/topology/{tenantId}/search?q={query}
// State:
//   - graphData, seedId, hopCount, searchResults
// Renders:
//   - Canvas/SVG graph visualization
//   - Seed & hop controls
//   - Search panel
```

#### `divergence/page.tsx` (676 lines)
```typescript
export default function DivergencePage()
// Functions:
//   - fetchSummaryAndScore() → GET /api/v1/reports/divergence/summary
//   - fetchRecords() → GET /api/v1/reports/divergence/records?page={p}&page_size={s}
//   - handleRunDivergence() → POST /api/v1/reports/divergence/run
// State:
//   - summary, score, records[], filters, pagination
// Renders:
//   - Divergence summary cards
//   - Record table with filter/sort
//   - Run button
```

---

## Current Routes (App Directory Structure)

All routes are implemented as **page.tsx** files following Next.js App Router convention:

| Route | Page File | Purpose |
|-------|-----------|---------|
| `/` | `app/page.tsx` | Redirects to `/dashboard` |
| `/dashboard` | `app/dashboard/page.tsx` | Main dashboard (scorecard, alarms) |
| `/incidents` | `app/incidents/page.tsx` | Incident management & drill-down |
| `/scorecard` | `app/scorecard/page.tsx` | Autonomous system metrics & KPIs |
| `/divergence` | `app/divergence/page.tsx` | Configuration drift detection |
| `/topology` | `app/topology/page.tsx` | Network topology graph & search |
| `/roi` | `app/roi/page.tsx` | ROI dashboard metrics |
| `/gtm-demo` | `app/gtm-demo/page.tsx` | Go-to-market demo page |

**No dynamic routes** (e.g., `[id]` folders) are currently implemented. Detail views are modal-based within the same route.

---

## API Endpoints (All Calls from Frontend)

All API calls use the pattern `${API_BASE_URL}/api/v1/...` where:
```typescript
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'
```

### Authentication & Tenant APIs
| Endpoint | Method | File | Purpose |
|----------|--------|------|---------|
| `/api/v1/auth/token` | POST | `layout-auth.tsx` | Login (username/password) |
| `/api/v1/auth/select-tenant` | POST | `layout-auth.tsx` | Select tenant by ID |

### Autonomous System APIs
| Endpoint | Method | File | Purpose |
|----------|--------|------|---------|
| `/api/v1/autonomous/scorecard` | GET | `dashboard/page.tsx`, `scorecard/page.tsx` | Get KPI metrics |
| `/api/v1/autonomous/detections` | GET | `scorecard/page.tsx` | Get detection summaries |
| `/api/v1/autonomous/value-capture` | GET | `scorecard/page.tsx` | Get value-capture metrics |
| `/api/v1/autonomous/roi-dashboard` | GET | `roi/page.tsx` | Get ROI metrics |

### Streaming & Real-time APIs
| Endpoint | Method | File | Purpose |
|----------|--------|------|---------|
| `/api/v1/stream/alarms?tenant_id={id}` | GET (SSE) | `dashboard/page.tsx` | EventSource stream of alarms |

### Incident Management APIs
| Endpoint | Method | File | Purpose |
|----------|--------|------|---------|
| `/api/v1/incidents/` | GET | `incidents/page.tsx` | List incidents (paginated) |
| `/api/v1/incidents/{id}` | GET | `incidents/page.tsx` | Get incident detail |
| `/api/v1/incidents/search` | GET | `incidents/page.tsx` | Search incidents by term |

### Topology APIs
| Endpoint | Method | File | Purpose |
|----------|--------|------|---------|
| `/api/v1/topology/{tenantId}/search?q={query}` | GET | `topology/page.tsx` | Search nodes in topology |
| `/api/v1/topology/{tenantId}/neighborhood/{seed}?hops={n}` | GET | `topology/page.tsx` | Get graph neighborhood (N-hop) |

### Configuration Divergence APIs
| Endpoint | Method | File | Purpose |
|----------|--------|------|---------|
| `/api/v1/reports/divergence/summary?tenant_id={id}` | GET | `divergence/page.tsx` | Get divergence summary |
| `/api/v1/reports/divergence/score/{tenantId}` | GET | `divergence/page.tsx` | Get divergence score |
| `/api/v1/reports/divergence/records?tenant_id={id}&page={p}&page_size={s}` | GET | `divergence/page.tsx` | Get divergence records (paginated) |
| `/api/v1/reports/divergence/run` | POST | `divergence/page.tsx`, `IngestionControlPanel.tsx` | Trigger divergence detection run |
| `/api/v1/reports/divergence/generate` | POST | `IngestionControlPanel.tsx` | Generate divergence report |

### Ingestion & Data Pipeline APIs
| Endpoint | Method | File | Purpose |
|----------|--------|------|---------|
| `/api/v1/ingestion/status` | GET | `IngestionControlPanel.tsx` | Poll ingestion status |
| `/api/v1/ingestion/stream` | GET (SSE) | `IngestionControlPanel.tsx` | EventSource stream of ingestion progress |
| `/api/v1/ingestion/start` | POST | `IngestionControlPanel.tsx` | Start data ingestion pipeline |

### Feedback & Decision APIs
| Endpoint | Method | File | Purpose |
|----------|--------|------|---------|
| `/api/v1/decisions/{decisionId}/feedback` | POST | `FeedbackWidget.tsx` | Submit feedback on a decision |

### Status & Health APIs
| Endpoint | Method | File | Purpose |
|----------|--------|------|---------|
| `/api/v1/data-status?tenant_id={id}` | GET | `Navigation.tsx` | Get data ingestion status (for nav badge) |

---

## Configuration & Dependencies

### Next.js Configuration (`next.config.ts`)
```typescript
const nextConfig: NextConfig = {
  // Conditional static export for cloud deployment
  ...(process.env.NEXT_OUTPUT_EXPORT === "true" ? { output: "export" } : {})
};
```
- **Static export enabled** when `NEXT_OUTPUT_EXPORT=true` during build
- Supports Caddy reverse proxy serving static files
- Environment variable: `NEXT_PUBLIC_API_BASE_URL` (defaults to `http://localhost:8000`)

### Package Dependencies (React/Next Stack)
| Package | Version | Purpose |
|---------|---------|---------|
| `next` | 16.1.6 | Framework |
| `react` | 19.2.3 | UI library |
| `react-dom` | 19.2.3 | DOM rendering |
| `tailwindcss` | 4 | CSS utility framework |
| `@tailwindcss/postcss` | 4 | PostCSS plugin |
| `clsx` | 2.1.1 | Conditional className |
| `tailwind-merge` | 3.4.0 | Merge Tailwind classes |
| `framer-motion` | 12.34.0 | Animation library |
| `lucide-react` | 0.563.0 | Icon library |

### Dev Dependencies
- `typescript` 5, `eslint` 9, `@types/react` 19, `@types/node` 20

### Build Scripts
```json
{
  "dev": "next dev",
  "build": "next build",
  "start": "next start",
  "lint": "eslint"
}
```

### Font Configuration
- **Primary:** Inter (from `next/font/google`)
- **Variable:** `--font-inter` (applied in root layout)
- **Metadata:** "pedk.ai | NOC Command Center"

---

## Design System & Styling

### CSS Variables (globals.css)
```css
:root {
  --background: #06203b;        /* Brand navy */
  --foreground: #f8fafc;        /* White/light */
  --brand-navy: #06203b;        /* Dark blue background */
  --brand-navy-mid: #0a2d4a;    /* Mid-tone panel bg */
  --brand-navy-border: #0d3b5e; /* Border color */
  --brand-cyan: #00d4ff;        /* Accent cyan */
}
```

### Tailwind Class Patterns
- **Text:** `text-white`, `text-white/80` (secondary), `text-white/60` (tertiary)
- **Backgrounds:** `bg-[#06203b]` (brand navy), `bg-[#0a2d4a]` (panels)
- **Borders:** `border-cyan-900/40`
- **Buttons:**
  - Primary (CTA): `bg-cyan-400 hover:bg-cyan-300 text-gray-950 font-bold`
  - Secondary: `bg-violet-500 hover:bg-violet-400 text-white`
- **Hover states:** `hover:bg-white/5`, `hover:bg-[#0d3b5e]`
- **Navigation:** Inactive links have `border border-white/25`

### Glass-morphism Effect
```css
.glass {
  background: rgba(6, 32, 59, 0.7);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(0, 212, 255, 0.1);
}
```

---

## Authentication & State Management

### Auth Context Pattern
```typescript
// context/AuthContext.tsx
interface AuthContextType {
  token: string;
  tenantId: string;
  tenantName: string;
  onLogout: () => void;
}

export function AuthProvider({ token, tenantId, tenantName, onLogout, children }) {
  // Context.Provider
}

export function useAuth() {
  return useContext(AuthContext);
}
```

### Auth Flow (layout-auth.tsx)
1. **Login Phase:** Username/password form → POST `/api/v1/auth/token`
2. **Tenant Selection Phase:** Dropdown of available tenants → POST `/api/v1/auth/select-tenant`
3. **App Phase:** AuthProvider wraps children with token + tenant context

### State Management Approach
- **Local component state** (`useState`) for page-level data
- **React Context** for global auth (token, tenantId, tenantName)
- **No Redux/Zustand:** Simple state lifting for cross-component needs
- **No persistent storage:** Auth state cleared on logout

---

## Accessibility & Metadata

### HTML Metadata (layout.tsx)
```typescript
export const metadata: Metadata = {
  title: "pedk.ai | NOC Command Center",
  description: "Autonomous Network Operations & MTTR Reduction"
};
```

### Charset & Viewport
- Standard Next.js defaults (set by framework)
- No custom viewport meta tags

---

## Potential Issues & Observations

### Code Quality Notes
1. **API Base URL duplication:** Each page defines its own `API_BASE_URL` constant. Consider extracting to `lib/api.ts` or `context/ApiContext.tsx`.
2. **Error handling:** Most fetch calls have basic try-catch. No centralized error boundary or retry logic.
3. **Loading states:** Pages use `isLoading` flags but UI feedback could be more consistent.
4. **TypeScript:** No explicit error/response types; many endpoints use implicit `any` types.

### Performance Considerations
1. **No pagination UI components:** Pages implement pagination manually in state.
2. **No request caching:** Every page refetch makes a new API call (no React Query/SWR).
3. **EventSource streams:** Used for alarms and ingestion progress (good pattern, no polling).
4. **Component size:** Largest pages (`divergence`, `topology`, `incidents`) are 664, 664, 493 lines—consider extracting sub-components.

### Browser Compatibility
- Modern browsers only (uses ES2020+ features via Tailwind 4)
- No IE11 support (intentional per Next.js 16)

---

## Summary Statistics

| Metric | Count |
|--------|-------|
| **Total Routes** | 8 (including home redirect) |
| **Total Components** | 7 reusable + 8 page routes |
| **Total Lines of Code** | 3,069 (TSX/TS) |
| **API Endpoints Used** | 24 distinct endpoints |
| **Authentication Type** | Token-based (JWT implied) |
| **Real-time Capabilities** | EventSource streams (alarms, ingestion) |
| **CSS Framework** | Tailwind CSS 4 + custom CSS variables |
| **State Management** | React Context (auth) + Local State (pages) |

---

**End of Report**
