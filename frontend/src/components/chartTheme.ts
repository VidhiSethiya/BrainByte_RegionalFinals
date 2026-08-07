/**
 * The only file besides `main.tsx` allowed to contain a hex.
 *
 * Recharts takes colours as props and cannot read AntD tokens, so the palette is
 * pinned here once and imported. Never inline a colour in a chart.
 */

/** clay, teal, ochre, navy — in this order, always. */
export const SERIES = ["#C45A5E", "#4A7C82", "#B08D57", "#2E3B4E"];

export const AXIS = "#2E3B4E";
export const GRID = "#EBE9E1";
export const SURFACE = "#FFFFFF";
export const TEXT_SECONDARY = "#5E5E5E";

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
    boxShadow: "0 8px 24px rgba(0,0,0,0.06)",
    fontSize: 13,
  },
  labelStyle: { color: TEXT_SECONDARY, fontSize: 12 },
  cursor: { fill: "rgba(46,59,78,0.04)" },
} as const;

export const legendProps = {
  wrapperStyle: { fontSize: 12, color: TEXT_SECONDARY },
} as const;
