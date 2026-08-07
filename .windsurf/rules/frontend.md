---
trigger: glob
globs: frontend/**
description: TicketSphere frontend rules — read the full spec before writing UI code
---

# TicketSphere frontend rules

**Product:** TicketSphere — *An enterprise AI ticket intelligence platform*

Name and tagline are final. Use them verbatim everywhere: one word, capital T, capital S
— never "Ticketsphere", "Ticket Sphere" or "TICKETSPHERE". The tagline is the header
strapline and the browser title, worded exactly as above.

**Before writing any UI code, read `../../frontend/FRONTEND_SPEC.md`.** It has the design
brief, the API types, the file map and a per-screen spec. `.claude/plans/BLUEPRINT.md`
has the system context. Do not infer the design from existing pages — several of them
still carry unthemed AntD defaults that are being replaced.

## Non-negotiable

1. **Ant Design only.** No Tailwind, no styled-components, no second UI library. Add no
   new npm dependency without asking.
2. **No hard-coded hex, radius or font-family in a component.** Colour comes from the
   AntD theme tokens (`frontend/src/main.tsx`) or the CSS variables in
   `frontend/src/index.css`. The only exceptions are that theme object and
   `src/components/chartTheme.ts`, because Recharts props cannot read tokens.
3. **All HTTP goes through `src/api/client.ts`.** No `fetch` in a component. The client
   already unwraps the `{data, meta}` / `{error}` envelope and handles 401 — do not
   re-implement either.
4. **Server data → TanStack Query. UI state → Zustand** (filters, drawer open, selection
   only — never a ticket or a response).
5. **Tables are AntD `<Table>` in server-side mode**, wired to the list contract
   (`page`, `page_size`, `sort`, `order`, `q`, `filter[...]` → `meta.total`). Never
   client-side pagination. Copy `src/pages/Documents.tsx`.
6. **Light mode only.** No dark theme.
7. **Never remove a focus ring.**
8. **Numeric columns:** right-aligned, `className="tabular"`.
9. **Severity and status never rely on colour alone** — always a text label.
10. **Do not restructure.** Create only the files listed in the spec's file map. Do not
    move or rename existing pages.
11. **The logo is an inline SVG component** (`src/components/Logo.tsx`) — never a PNG, an
    AI-generated image, a CDN asset or an emoji, and never the TCS or any other corporate
    identity mark. Brief and constraints: spec §9.2.1.

## Palette (reference — use tokens, not these literals)

Ground `#FCFBF8` · surface `#FFFFFF` · surface-alt `#F5F4F0` · border `#EBE9E1` ·
text `#1A1A1A` / `#5E5E5E` · action `#A84A4D` (hover `#8F3E41`) · accent `#C45A5E`
(**no text on it**) · teal `#4A7C82` · ochre `#B08D57` · navy `#2E3B4E`.
Chart series order: clay, teal, ochre, navy. Radius 4px controls / 8px cards, nothing above.
8px spacing grid.

## Ground rules for the product

- The UI's job is to make an AI decision **legible and reversible in two clicks**.
- Every override requires a written reason.
- The system **recommends** a first action and never executes it — never build UI that
  implies otherwise.
- Access control is enforced by the API. Hide manager nav from engineers as courtesy, but
  never treat the menu as the security boundary.
- Blocked-by-guardrail states are a feature, not an error. Style them intentionally.
- Every screen ships loading, empty, error and blocked states before it is "done".

## Before calling anything done

`cd frontend && npm run build` must pass clean (`tsc --noEmit` runs as part of it).
