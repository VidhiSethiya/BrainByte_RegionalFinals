/**
 * The only file besides `main.tsx` allowed to contain a hex.
 *
 * Recharts takes colours as props and cannot read AntD tokens, so the palette is
 * pinned here once and imported. Never inline a colour in a chart.
 */

import { useCallback, useState } from "react";

/** teal, sky, amber, navy — in this order, always. */
export const SERIES = ["#027289", "#4FB3C4", "#DE8433", "#14304A"];

/** Priority pie slices — Highest → Low. Matches SeverityTag intent, not Ant tokens. */
export const PRIORITY_COLORS: Record<string, string> = {
  Highest: "#C0392B",
  High: "#DE8433",
  Medium: "#4FB3C4",
  Low: "#14304A",
};

/** Hover / click muted state for interactive chart shapes. */
export const INTERACTIVE_MUTED = "#9AA8B5";

export const AXIS = "#14304A";
export const GRID = "#E1EBEF";
export const SURFACE = "#FFFFFF";
export const TEXT_SECONDARY = "#5A6B7B";

/**
 * Per-chart hover + click selection. Hover or selected index renders as grey;
 * click toggles selection. Cursor is handled in CSS (`.chart-card`).
 */
export function useChartInteraction() {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [selected, setSelected] = useState<ReadonlySet<number>>(() => new Set());

  const onMouseEnter = useCallback((_data: unknown, index: number) => {
    setHoverIndex(index);
  }, []);

  const onMouseLeave = useCallback(() => {
    setHoverIndex(null);
  }, []);

  const onClick = useCallback((_data: unknown, index: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }, []);

  const fillFor = useCallback(
    (base: string, index: number) =>
      hoverIndex === index || selected.has(index) ? INTERACTIVE_MUTED : base,
    [hoverIndex, selected]
  );

  /** Series-level mute (area / line): key by series name. */
  const [mutedSeries, setMutedSeries] = useState<ReadonlySet<string>>(() => new Set());
  const [hoverSeries, setHoverSeries] = useState<string | null>(null);

  const seriesFill = useCallback(
    (base: string, name: string) =>
      hoverSeries === name || mutedSeries.has(name) ? INTERACTIVE_MUTED : base,
    [hoverSeries, mutedSeries]
  );

  const onSeriesEnter = useCallback((name: string) => setHoverSeries(name), []);
  const onSeriesLeave = useCallback(() => setHoverSeries(null), []);
  const onSeriesClick = useCallback((name: string) => {
    setMutedSeries((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  return {
    onMouseEnter,
    onMouseLeave,
    onClick,
    fillFor,
    seriesFill,
    onSeriesEnter,
    onSeriesLeave,
    onSeriesClick,
  };
}

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
  // Soft grey band under the active bar / category on hover.
  cursor: { fill: "rgba(154,168,181,0.22)" },
} as const;

export const legendProps = {
  wrapperStyle: { fontSize: 12, color: TEXT_SECONDARY },
} as const;
