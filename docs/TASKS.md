# Pedkai — Task Backlog

## Open Tasks

### T-001: Consolidate Root-Level Documentation into Single Product Specification

**Priority:** Medium
**Status:** Open
**Created:** 2026-03-04

**Context:**
The Pedkai root directory contains numerous overlapping documents describing the product vision,
architecture, implementation roadmaps, executive reviews, and strategic audits. These include
(non-exhaustive): `Pedkai_Vision_V8.md`, `README.md`, `pedkai.md`, `Pedkai.rtf`,
`Pedkai_Marketing.rtf`, `ARCHITECTURE_S3_REMEDIATION.md.resolved`, `IMPLEMENTATION_ROADMAP_V4.md`,
`Product_Vision_Alignment_Report.md`, `Gemini_Sales_Pitch.md`, multiple `pedkai_executive_re_review_v*.md`
files, committee reviews, strategic audits, and several `implementation_plan*.md` variants.

**Task:**
1. Audit all root-level documentation files and catalogue what each covers.
2. Consolidate into a single authoritative **Product Specification Document** (`PRODUCT_SPEC.md`).
3. The consolidated document should cover:
   - Product vision and value proposition
   - Architecture overview
   - Feature inventory (wedges, workstreams, phases)
   - Data model and multi-tenant design
   - TMF standards compliance (TMF628, TMF642)
   - Deployment model
   - Security model
4. Archive superseded documents into a `docs/archive/` directory.
5. Update any internal cross-references.

**Origin:** Identified during Telco2 integration testing — the scattered documentation made it
difficult to establish a single source of truth for what Pedkai's key features are.