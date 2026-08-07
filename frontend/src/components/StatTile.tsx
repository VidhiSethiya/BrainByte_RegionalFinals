/**
 * The one stat tile used by Queue, Control and Triage.
 *
 * Display-size value, 12px uppercase caption, tabular figures. A tile never
 * computes anything — it renders a number an endpoint returned, and shows an
 * em dash when that number has not arrived rather than a confident zero.
 */

import { Card, Flex, Skeleton, Tooltip, Typography } from "antd";
import type { ReactNode } from "react";

export type StatTone = "default" | "success" | "warning" | "error" | "info";

const TONE_COLOR: Record<StatTone, string> = {
  default: "var(--text-primary)",
  success: "var(--success)",
  warning: "var(--warning)",
  error: "var(--error)",
  info: "var(--info)",
};

interface StatTileProps {
  label: string;
  value: number | string | null | undefined;
  suffix?: string;
  hint?: string;
  tone?: StatTone;
  loading?: boolean;
  extra?: ReactNode;
  onClick?: () => void;
  /** Small circular glyph on the left. Decorative — the label carries the meaning. */
  icon?: ReactNode;
  /** One-line qualifier under the value, e.g. "Critical priority". */
  caption?: string;
  /** Recent history for the inline sparkline. Two points minimum, or it is skipped. */
  trend?: number[];
  /** Dense tile for dashboard strips — equal height, less padding, no sparkline. */
  compact?: boolean;
}

/**
 * Inline sparkline. Hand-drawn rather than a Recharts instance: twelve of these
 * on a screen would mount twelve responsive containers for sixty pixels each.
 * Decorative and `aria-hidden` — the number beside it is the accessible value.
 */
function Sparkline({ points, tone }: { points: number[]; tone: StatTone }) {
  const width = 100;
  const height = 20;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const path = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * width;
      const y = height - ((point - min) / span) * (height - 4) - 2;
      return `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      className="sparkline"
      width="100%"
      height={height}
      preserveAspectRatio="none"
      viewBox={`0 0 ${width} ${height}`}
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d={path}
        stroke={TONE_COLOR[tone === "default" ? "info" : tone]}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function StatTile({
  label,
  value,
  suffix,
  hint,
  tone = "default",
  loading = false,
  extra,
  onClick,
  icon,
  caption,
  trend,
  compact = false,
}: StatTileProps) {
  const display = value === null || value === undefined ? "—" : value;
  // Long values (currency, token counts) step down a size rather than wrapping
  // onto a second line and breaking the tile grid.
  const digits = String(display).length + (suffix?.length ?? 0);
  const fontSize = compact
    ? digits > 9
      ? 16
      : digits > 6
        ? 18
        : 22
    : digits > 9
      ? 22
      : digits > 6
        ? 26
        : 32;
  const valueLineHeight = compact ? "28px" : "40px";
  const showTrend = !compact && trend && trend.length > 1 && !loading;

  const body = (
    <Card
      size="small"
      hoverable={!!onClick}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      className={`stat-tile${compact ? " is-compact" : ""}${onClick ? " is-interactive" : ""}`}
      styles={{ body: { padding: compact ? "10px 12px" : 16 } }}
    >
      <Flex align="center" gap={compact ? 8 : 12} style={{ minHeight: compact ? 56 : undefined }}>
        {icon && <span className="stat-icon">{icon}</span>}

        <Flex vertical gap={compact ? 0 : 2} flex={1} style={{ minWidth: 0 }}>
          <Flex align="center" justify="space-between" gap={8}>
            <span className="label">{label}</span>
            {extra}
          </Flex>

          {loading ? (
            <Skeleton.Input active size="small" style={{ width: 72, height: compact ? 24 : 32 }} />
          ) : (
            <Typography.Text
              className="tabular"
              style={{
                fontSize,
                lineHeight: valueLineHeight,
                letterSpacing: "-0.02em",
                color: TONE_COLOR[tone],
                whiteSpace: "nowrap",
              }}
            >
              {display}
              {suffix && value !== null && value !== undefined && (
                <span
                  style={{
                    fontSize: compact ? 12 : 16,
                    color: "var(--text-secondary)",
                    marginInlineStart: 4,
                  }}
                >
                  {suffix}
                </span>
              )}
            </Typography.Text>
          )}

          {caption && !loading && !compact && (
            <Typography.Text style={{ fontSize: 12, color: TONE_COLOR[tone] }}>{caption}</Typography.Text>
          )}

          {/* Under the value, never beside it — a 3-column tile has no room to
              put a chart next to a 32px figure without the two colliding. */}
          {showTrend && <Sparkline points={trend!} tone={tone} />}
        </Flex>
      </Flex>
    </Card>
  );

  return hint ? <Tooltip title={hint}>{body}</Tooltip> : body;
}
