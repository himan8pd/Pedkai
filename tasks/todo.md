# Pedkai TODO

## Pending

- [ ] **Light/Dark Mode — Inference & Polish**
  - AI inference button on divergence page fails in light mode (styling + error handling)
  - Test all pages end-to-end in light mode — check for missed hardcoded colors
  - Topology canvas: review node colors for contrast on light background
  - Login/tenant-select pages: currently always dark (brand decision?) — verify intentional
  - Sleeping cells, scorecard, incidents, feedback pages — visual QA in light mode
  - Consider system preference detection (`prefers-color-scheme`) as default

## Completed (2026-03-23)

- [x] ThemeContext with localStorage persistence
- [x] CSS variable overrides for `[data-theme="light"]`
- [x] Tailwind class overrides for hardcoded brand colors
- [x] Sun/Moon toggle in Navigation bar
- [x] Topology canvas theme-aware drawing
- [x] Historic analysis banner light-mode text fix
- [x] Navbar height matches logo at all breakpoints
- [x] Logo flush top-left corner
