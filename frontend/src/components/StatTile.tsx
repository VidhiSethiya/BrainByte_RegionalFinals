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
}: StatTileProps) {
  const display = value === null || value === undefined ? "—" : value;
  // Long values (currency, token counts) step down a size rather than wrapping
  // onto a second line and breaking the tile grid.
  const digits = String(display).length + (suffix?.length ?? 0);
  const fontSize = digits > 9 ? 22 : digits > 6 ? 26 : 32;

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
      styles={{ body: { padding: 16 } }}
    >
      <Flex vertical gap={8}>
        <Flex align="center" justify="space-between" gap={8}>
          <span className="label">{label}</span>
          {extra}
        </Flex>

        {loading ? (
          <Skeleton.Input active size="small" style={{ width: 72, height: 32 }} />
        ) : (
          <Typography.Text
            className="tabular"
            style={{
              fontSize,
              lineHeight: "40px",
              letterSpacing: "-0.02em",
              color: TONE_COLOR[tone],
              whiteSpace: "nowrap",
            }}
          >
            {display}
            {suffix && value !== null && value !== undefined && (
              <span style={{ fontSize: 16, color: "var(--text-secondary)", marginInlineStart: 4 }}>{suffix}</span>
            )}
          </Typography.Text>
        )}
      </Flex>
    </Card>
  );

  return hint ? <Tooltip title={hint}>{body}</Tooltip> : body;
}
