/**
 * The only file besides `main.tsx` allowed to contain a hex.
 *
 * Recharts takes colours as props and cannot read AntD tokens, so the palette is
 * pinned here once and imported. Never inline a colour in a chart.
 */

/** teal, sky, amber, navy — in this order, always. */
export const SERIES = ["#027289", "#4FB3C4", "#DE8433", "#14304A"];

export const AXIS = "#14304A";
export const GRID = "#E1EBEF";
export const SURFACE = "#FFFFFF";
export const TEXT_SECONDARY = "#5A6B7B";

/**
 * Recharts series animation. Long enough to read as a draw-in, short enough
 * that a manager scanning four charts never waits for one.
 */
export const ANIMATION = {
  isAnimationActive: true,
  animationDuration: 700,
  animationEasing: "ease-out",
} as const;

/** Stagger by series index so a grouped bar chart draws in order, not at once. */
export const animationFor = (index: number) => ({
  ...ANIMATION,
  animationBegin: index * 120,
});

/** Every chart is this tall, inside a `<Card size="small">`. */
export const CHART_HEIGHT = 260;

/** Shared axis/tooltip props so eight charts do not drift into eight styles. */
export const axisProps = {
  stroke: AXIS,
  tick: { fill: TEXT_SECONDARY, fontSize: 12 },
  tickLine: false,
  axisLine: { stroke: GRID },
} as const;

export const tooltipProps = {
  contentStyle: {
    background: SURFACE,
    border: `1px solid ${GRID}`,
    borderRadius: 8,
    boxShadow: "0 10px 28px rgba(18,35,63,0.10)",
    fontSize: 13,
  },
  labelStyle: { color: TEXT_SECONDARY, fontSize: 12 },
  cursor: { fill: "rgba(2,114,137,0.06)" },
} as const;

export const legendProps = {
  wrapperStyle: { fontSize: 12, color: TEXT_SECONDARY },
} as const;
