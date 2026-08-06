# Enterprise UI Design System

Corporate healthcare design language: crisp, clinical, trustworthy, soothing. Warm
off-white grounds, muted accents, precise 4px geometry, breathable space. No stark
contrasts, no playful rounding.

**This is applied through Ant Design's theme, not a stylesheet.** AntD v5 styles itself
with CSS-in-JS design tokens — a `:root` block of CSS variables will not restyle a
single `<Table>` or `<Button>`. The token object in §7 is what actually changes the app;
the CSS variables in §8 exist only for the handful of elements we author ourselves.

---

## 1. Rules

1. Every value below is a token. No hard-coded hex, px radius, or font-family in a
   component file.
2. Set the theme once, in `frontend/src/main.tsx` `<ConfigProvider theme={...}>`.
3. Density over decoration. This is an enterprise data application; a screen that shows
   more verified information wins over one that shows less more beautifully.
4. **Light mode only.** No dark theme — it doubles the surface area for no judging
   credit inside a 20-hour build.

---

## 2. Colour

### Ground and surface

| Token | Hex | Use |
|---|---|---|
| App background | `#FCFBF8` | Buttery cream. The page itself. |
| Surface | `#FFFFFF` | Cards, modals, table bodies, inputs. |
| Surface alt | `#F5F4F0` | Sider, table headers, hover fills, disabled fields. |
| Border | `#EBE9E1` | Warm light gray. Row dividers, card edges, input outlines. |

The warm ground is the whole trick: white cards on cream read as elevated without a
shadow doing the work. Never put a white card on a white page.

### Text

| Token | Hex | Use |
|---|---|---|
| Text primary | `#1A1A1A` | Rich charcoal. **Never `#000000`.** |
| Text secondary | `#5E5E5E` | Labels, helper text, metadata. 5.99:1 on cream — AA pass. |
| Text tertiary | `#8A8A8A` | Placeholders, disabled. Decorative only — **fails AA**, never for content. |

### Accents

The source brief named four accents but gave a hex for only one. These are the missing
values, desaturated to sit on the warm ground without vibrating against it:

| Role | Hex | Use |
|---|---|---|
| Primary — clay | `#C45A5E` | Brand accent. Active nav, focus rings, key chart series. |
| Primary pressed | `#A84A4D` | **Filled buttons carrying white text** — see the contrast note. |
| Primary deep | `#8F3E41` | Hover on those buttons. |
| Secondary — teal | `#4A7C82` | Anchor. Links, secondary charts, informational states. |
| Tertiary — ochre | `#B08D57` | Muted mustard. Third chart series, "needs attention". |
| Structural navy | `#2E3B4E` | Near-neutral. Chart axes, dense table headers, deep dividers. |

> **Contrast finding — act on this.** White text on `#C45A5E` measures **4.23:1**, below
> the WCAG AA floor of 4.5:1 for normal text. It looks fine and fails audit. So:
> `#C45A5E` is for accents that carry **no text** — borders, icons, indicators, chart
> fills. Filled buttons with white labels use `#A84A4D` (**5.60:1**, comfortable pass),
> hovering to `#8F3E41`. Teal `#4A7C82` with white is **4.67:1** — passes, but do not
> tint it lighter.

### Semantic states

AntD's stock red/green/gold are far too saturated for this ground and will look like a
different product. Override them, and map them to what this app actually shows:

| State | Hex | Where it appears in this app |
|---|---|---|
| Success | `#4F7A5B` | Groundedness ≥ 75%, audit chain intact, indexed |
| Warning | `#B08D57` | Groundedness 50–75%, low-confidence caveat, pending review |
| Error | `#A84A4D` | Blocked answer, broken hash chain, failed index |
| Info | `#4A7C82` | Retrieval mode badge, provider badge, neutral notices |

Sensitivity tags map onto the same set — `public` success, `internal` info,
`confidential` warning, `restricted` error — so the Knowledge Base table reads at a
glance without a legend.

---

## 3. Typography

### The font problem, first

`JJ Circular Std` and `Akzidenz Grotesk Pro` are **licensed commercial typefaces**. They
are almost certainly not installed on the build machine, cannot be pulled from a CDN,
and must not be committed to the repo. Declared but absent, the stack silently falls
through to `system-ui` and every spacing decision below is built on a font nobody sees.

So: declare them first for machines that are licensed, then a fallback chosen to match
Circular's geometric, generous-x-height character.

```css
--font-body: 'JJ Circular Std Book', 'Circular Std', 'Inter', system-ui,
             -apple-system, 'Segoe UI', sans-serif;
--font-heading: 'JJ Circular Std Black', 'Circular Std', 'Inter', system-ui, sans-serif;
--font-data: 'Akzidenz Grotesk Pro', 'Inter', system-ui, sans-serif;
```

Inter is metrically close, free, and self-hostable. If the licensed files *are*
available, drop the `.woff2` into `frontend/public/fonts/` and `@font-face` them with
`font-display: swap` — never a blocking webfont before a demo.

**Do not use the corporate logo or wordmark** unless the event materials grant it.
Design language is fine to borrow; identity marks in a screenshot are a different thing.

### Scale

| Level | Font | Size / line-height | Notes |
|---|---|---|---|
| Display / H1 | Heading | `32px / 40px`, tracking `-0.02em` | Page titles only, one per screen |
| H2 | Heading | `24px / 1.4` | Section headings |
| H3 | Heading | `20px / 1.4` | Card titles |
| Label / definition | Body | `12px / 16px`, tracking `0.05em`, uppercase | Form labels, stat captions. Text secondary. |
| Body | Body | `14px / 20px` | Default. Enterprise density. |
| Data / tabular | Data | `13px` + `font-variant-numeric: tabular-nums` | See below |

**Tabular figures are the substantive rule here**, not the font name. Any column of
numbers — latency, tokens, scores, counts, IDs — must set `tabular-nums` so digits share
a width and the column aligns. Proportional digits in a data table are the single most
common tell of an amateur enterprise UI.

Negative tracking on the display size only. At 14px it hurts legibility.

---

## 4. Geometry and spacing

- **8px grid.** Every padding, margin and gap is 8/16/24/32/40/48. No 10px, no 15px.
- **Radius:** `4px` buttons, inputs, tags, badges. `8px` cards, modals, drawers. Nothing
  above 8px — pill shapes read as consumer, not enterprise.
- **Borders:** `1px solid #EBE9E1` for row dividers, card edges, header rules.
- **Elevation** — diffuse, never dark:
  - Card `0 4px 12px rgba(0,0,0,0.03)`
  - Dropdown / modal / drawer `0 8px 24px rgba(0,0,0,0.06)`
- **Control height:** `32px` default, `24px` small, `40px` large.

Prefer a border to a shadow for anything that is not floating. Shadows are for things
that leave the plane.

---

## 5. Glass — deliberately restrained

The brief asks for an Apple-style glass effect. Taken literally, glassmorphism fights
everything else here: it wants heavy blur, translucency and large radii, while this
system is crisp, opaque and 4px. Applied to content it will make text illegible over a
scrolling background and look cheap next to the clinical palette.

Use it as a **surface treatment on floating chrome only**:

```css
--glass-bg: rgba(252, 251, 248, 0.72);
--glass-blur: blur(12px) saturate(115%);
--glass-border: 1px solid rgba(235, 233, 225, 0.9);
```

| Allowed | Forbidden |
|---|---|
| Sticky app header | Content cards |
| Chatbot drawer panel | Table rows or headers |
| Modal overlay backdrop | Dashboard stat tiles |
| Floating action button | Anything containing body copy over imagery |

Rules: opacity stays **≥ 0.7** so text keeps its contrast; blur stays **≤ 12px**; never
apply `backdrop-filter` to a large scrolling surface — it repaints every frame and will
visibly stutter a demo on integrated graphics. Ship without it if the header janks.

---

## 6. Components

**Primary button** — fill `#A84A4D`, white 14px label, radius 4px, hover `#8F3E41`, no
shadow. **Secondary** — white fill, `1px solid #EBE9E1`, charcoal label, hover fill
`#F5F4F0`. **Text button** for tertiary actions; no third filled style.

**Inputs** — white, `1px solid #EBE9E1`, `8px 12px`. Focus: `1px solid #4A7C82` plus
`0 0 0 2px rgba(74,124,130,0.10)`. Never remove the focus ring; keyboard navigation is
an accessibility requirement, and judges do tab through things.

**Tables** — header `#F5F4F0` with 12px uppercase labels, `1px` row dividers, hover
`#FCFBF8`, no zebra striping (it fights the warm ground). Numeric columns right-aligned
with tabular figures.

**Tags** — 4px radius, tinted background at ~12% of the semantic colour with the solid
colour as text. Never full-saturation fills.

**Cards** — white on cream, 8px radius, `1px` border **and** the soft shadow, 24px
padding, 16px between title and body.

---

## 7. Ant Design theme — the part that actually applies

`frontend/src/main.tsx`. Verify token names against the installed `antd` version; v5
renames occasionally.

```ts
import type { ThemeConfig } from "antd";

export const theme: ThemeConfig = {
  token: {
    colorPrimary: "#A84A4D",
    colorInfo: "#4A7C82",
    colorSuccess: "#4F7A5B",
    colorWarning: "#B08D57",
    colorError: "#A84A4D",

    colorBgLayout: "#FCFBF8",
    colorBgContainer: "#FFFFFF",
    colorBgElevated: "#FFFFFF",

    colorText: "#1A1A1A",
    colorTextSecondary: "#5E5E5E",
    colorTextTertiary: "#8A8A8A",
    colorBorder: "#EBE9E1",
    colorBorderSecondary: "#EBE9E1",

    borderRadius: 4,
    borderRadiusLG: 8,
    borderRadiusSM: 4,

    fontFamily:
      "'JJ Circular Std Book', 'Circular Std', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
    fontSize: 14,
    fontSizeHeading1: 32,
    fontSizeHeading2: 24,
    fontSizeHeading3: 20,
    lineHeight: 1.43,

    controlHeight: 32,
    boxShadow: "0 4px 12px rgba(0,0,0,0.03)",
    boxShadowSecondary: "0 8px 24px rgba(0,0,0,0.06)",
    wireframe: false,
  },
  components: {
    Layout: {
      bodyBg: "#FCFBF8",
      headerBg: "#FFFFFF",
      siderBg: "#F5F4F0",
      headerHeight: 56,
    },
    Menu: {
      itemBg: "#F5F4F0",
      itemSelectedBg: "#FFFFFF",
      itemSelectedColor: "#A84A4D",
      itemHoverBg: "#FCFBF8",
      itemBorderRadius: 4,
    },
    Table: {
      headerBg: "#F5F4F0",
      headerColor: "#5E5E5E",
      rowHoverBg: "#FCFBF8",
      borderColor: "#EBE9E1",
      cellPaddingBlock: 12,
    },
    Card: { paddingLG: 24, headerBg: "transparent" },
    Button: { primaryShadow: "none", defaultShadow: "none", contentFontSize: 14 },
    Input: {
      activeBorderColor: "#4A7C82",
      hoverBorderColor: "#4A7C82",
      activeShadow: "0 0 0 2px rgba(74,124,130,0.10)",
    },
    Tag: { defaultBg: "#F5F4F0", defaultColor: "#5E5E5E" },
  },
};
```

Delete the placeholder `colorPrimary: "#1668dc"` currently in `main.tsx`.

---

## 8. CSS variables — for what we author ourselves

`frontend/src/index.css`, imported once in `main.tsx`. Covers the message bubbles,
citation strip and glass chrome that are not AntD components. Everything else takes the
theme above.

```css
:root {
  --bg-app: #FCFBF8;
  --bg-surface: #FFFFFF;
  --bg-surface-alt: #F5F4F0;

  --accent: #C45A5E;          /* non-text use only */
  --accent-action: #A84A4D;   /* text-bearing fills */
  --accent-action-hover: #8F3E41;
  --accent-secondary: #4A7C82;

  --text-primary: #1A1A1A;
  --text-secondary: #5E5E5E;
  --border-color: #EBE9E1;

  --success: #4F7A5B;
  --warning: #B08D57;
  --error: #A84A4D;

  --font-body: 'JJ Circular Std Book', 'Circular Std', 'Inter', system-ui, sans-serif;
  --font-heading: 'JJ Circular Std Black', 'Circular Std', 'Inter', system-ui, sans-serif;

  --radius-sm: 4px;
  --radius-md: 8px;
  --space: 8px;
  --shadow-card: 0 4px 12px rgba(0, 0, 0, 0.03);
  --shadow-float: 0 8px 24px rgba(0, 0, 0, 0.06);

  --glass-bg: rgba(252, 251, 248, 0.72);
  --glass-blur: blur(12px) saturate(115%);
}

body {
  background: var(--bg-app);
  color: var(--text-primary);
  font-family: var(--font-body);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

h1, h2, h3 { font-family: var(--font-heading); color: var(--text-primary); }
h1 { font-size: 32px; line-height: 40px; letter-spacing: -0.02em; }

.tabular { font-variant-numeric: tabular-nums; }
```

---

## 9. Screen-by-screen

| Screen | What the theme changes |
|---|---|
| Login | Cream page, single white card, `#A84A4D` submit. Kill the default AntD blue. |
| App shell | `#F5F4F0` sider, white header, cream content. Selected nav = white pill + clay label. Glass on the header if it stays smooth. |
| Assistant | User bubble `#F5F4F0`, assistant white + border, blocked tinted `--error` at 8%. Groundedness tag uses the semantic three. Citations 12px uppercase. |
| Chatbot drawer | Glass panel, `--shadow-float`. |
| Dashboard | Stat tiles white on cream, values 32px heading + `tabular-nums`. Charts use clay / teal / ochre / navy **in that order** — never AntD defaults. |
| Knowledge Base | Sensitivity tags on the semantic map. Numeric columns right-aligned, tabular. |
| Evaluations | Metric tiles share the stat-tile treatment; progress bars success/warning/error by band. |
| Audit | Action tags semantic; hash column `--font-data` + tabular so hashes align. |

---

## 10. Do not

- Hard-code a hex, radius or font-family in a component
- Ship AntD's stock blue, red or green anywhere
- Round anything past 8px
- Use `#000000`, or `#8A8A8A` for content text
- Put white text on `#C45A5E`
- Apply `backdrop-filter` to a scrolling list or table
- Build a dark theme
- Add a second UI library, Tailwind, or styled-components
- Remove focus rings
