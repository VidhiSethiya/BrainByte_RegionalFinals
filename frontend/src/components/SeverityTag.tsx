/**
 * Domain display atoms. Defined once, imported everywhere — defining a severity
 * colour twice is how a UI ends up calling the same thing two different things.
 *
 * Rule that governs every atom here: colour is reinforcement, never the sole
 * carrier. Every tag ships a text label.
 */

import {
  ClockCircleOutlined,
  FireOutlined,
  InfoCircleOutlined,
  MinusCircleOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { Flex, Tag, Tooltip, Typography } from "antd";
import { useEffect, useState } from "react";

import type { Severity, Team, TicketStatus } from "../api/client";

export const SEVERITY = {
  Highest: { label: "Highest", color: "error", icon: <FireOutlined /> },
  High: { label: "High", color: "warning", icon: <WarningOutlined /> },
  Medium: { label: "Medium", color: "processing", icon: <InfoCircleOutlined /> },
  Low: { label: "Low", color: "default", icon: <MinusCircleOutlined /> },
} as const;

export const STATUS = {
  new: { label: "New", color: "default" },
  triaged: { label: "Triaged", color: "processing" },
  awaiting_approval: { label: "Needs review", color: "warning" },
  // Set by POST /tickets/<id>/approve, between the manager's click and the Jira
  // write-back landing. Without an entry here StatusTag fell through to its
  // raw-string fallback and rendered an unstyled "approved" chip — visible in the
  // demo's approval beat, since a ticket sits in this state until sync completes
  // (and stays here permanently if the sync fails).
  approved: { label: "Approved", color: "success" },
  routed: { label: "Routed", color: "processing" },
  synced: { label: "Synced", color: "success" },
  resolved: { label: "Resolved", color: "success" },
  failed: { label: "Sync failed", color: "error" },
} as const;

export const TEAM_LABEL = { ops: "Ops", azure: "Azure", aws: "AWS", gcp: "GCP" } as const;

export const ENVIRONMENT_LABEL = { prod: "Production", uat: "UAT", dev: "Development" } as const;

/** Widened to string so one <Select options={…}> can take either list. */
export interface SelectOption {
  value: string;
  label: string;
}

export const SEVERITY_OPTIONS: SelectOption[] = (Object.keys(SEVERITY) as Severity[]).map((value) => ({
  value,
  label: SEVERITY[value].label,
}));

export const STATUS_OPTIONS: SelectOption[] = (Object.keys(STATUS) as TicketStatus[]).map((value) => ({
  value,
  label: STATUS[value].label,
}));

export const TEAM_OPTIONS: SelectOption[] = (Object.keys(TEAM_LABEL) as Team[]).map((value) => ({
  value,
  label: TEAM_LABEL[value],
}));

/** The taxonomy the classifier assigns. Filter values are sent verbatim as `filter[category]`. */
export const CATEGORY_OPTIONS: SelectOption[] = [
  "Access",
  "Backup",
  "CI/CD",
  "Compute",
  "Database",
  "Deployment",
  "Messaging",
  "Networking",
  "Observability",
  "Security",
  "Storage",
].map((value) => ({ value, label: value }));

export const ENVIRONMENT_OPTIONS: SelectOption[] = (
  Object.keys(ENVIRONMENT_LABEL) as (keyof typeof ENVIRONMENT_LABEL)[]
).map((value) => ({ value, label: ENVIRONMENT_LABEL[value] }));

export default function SeverityTag({ severity }: { severity: Severity | "" | null | undefined }) {
  if (!severity || !(severity in SEVERITY)) {
    return (
      <Tag style={{ marginInlineEnd: 0 }}>
        Unset
      </Tag>
    );
  }
  const { label, color, icon } = SEVERITY[severity as Severity];
  return (
    <Tag color={color} icon={icon} style={{ marginInlineEnd: 0 }}>
      {label}
    </Tag>
  );
}

export function StatusTag({ status }: { status: TicketStatus | string }) {
  const entry = STATUS[status as TicketStatus] ?? { label: status || "Unknown", color: "default" };
  return (
    <Tag color={entry.color} style={{ marginInlineEnd: 0 }}>
      {entry.label}
    </Tag>
  );
}

/**
 * Team-facing status — collapses the full pipeline vocabulary (new/triaged/
 * awaiting_approval/approved/routed/synced/resolved/failed, plus the AI's own
 * needs_human hold) down to the three states an engineer actually acts on.
 * The manager's queue/history keep the detailed StatusTag; this is only for
 * the team layer (TicketTable's showTeam=false path).
 */
const TEAM_STATUS = {
  closed: { label: "Closed", color: "success" },
  assigned: { label: "Assigned", color: "processing" },
  open: { label: "Open", color: "warning" },
} as const;

const TEAM_STATUS_MAP: Record<string, keyof typeof TEAM_STATUS> = {
  resolved: "closed",
  synced: "closed",
  routed: "assigned",
  approved: "assigned",
  new: "open",
  triaged: "open",
  awaiting_approval: "open",
  failed: "open",
};

export function TeamStatusTag({ status }: { status: TicketStatus | string }) {
  const bucket = TEAM_STATUS_MAP[status] ?? "open";
  const { label, color } = TEAM_STATUS[bucket];
  return (
    <Tag color={color} style={{ marginInlineEnd: 0 }}>
      {label}
    </Tag>
  );
}

export function TeamTag({ team }: { team: Team | "" | null | undefined }) {
  if (!team) return <Tag style={{ marginInlineEnd: 0 }}>Unassigned</Tag>;
  return <Tag style={{ marginInlineEnd: 0 }}>{TEAM_LABEL[team as Team] ?? team}</Tag>;
}

/**
 * Confidence: a bar alone is not an answer, so the number is always rendered too.
 * Below 0.50 the row is also telling the user it needs review.
 */
export function ConfidenceMeter({
  value,
  showBar = true,
}: {
  value: number | null | undefined;
  showBar?: boolean;
}) {
  const score = typeof value === "number" && !Number.isNaN(value) ? value : 0;
  const band = score >= 0.85 ? "is-high" : score >= 0.5 ? "is-mid" : "is-low";
  const wording =
    score >= 0.85
      ? "High confidence"
      : score >= 0.5
        ? "Moderate confidence — auto-routes"
        : "Low confidence — needs review";

  return (
    <Tooltip title={wording}>
      <Flex align="center" gap={8}>
        {showBar && (
          <span className={`confidence-bar ${band}`} aria-hidden="true">
            <span style={{ width: `${Math.round(score * 100)}%` }} />
          </span>
        )}
        <span className="tabular" style={{ fontSize: 13 }}>
          {(score * 100).toFixed(0)}%
        </span>
      </Flex>
    </Tooltip>
  );
}

export function GroundednessTag({ score }: { score?: number | null }) {
  if (score === undefined || score === null) return null;
  const color = score >= 0.75 ? "success" : score >= 0.5 ? "warning" : "error";
  return (
    <Tooltip title="Share of the answer's claims supported by the retrieved sources">
      <Tag color={color} style={{ marginInlineEnd: 0 }}>
        <span className="tabular">Grounded {(score * 100).toFixed(0)}%</span>
      </Tag>
    </Tooltip>
  );
}

const MINUTE = 60_000;

function formatDuration(ms: number) {
  const totalMinutes = Math.floor(Math.abs(ms) / MINUTE);
  if (Math.abs(ms) < 60 * MINUTE) {
    const minutes = Math.floor(Math.abs(ms) / MINUTE);
    const seconds = Math.floor((Math.abs(ms) % MINUTE) / 1000);
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  const hours = Math.floor(totalMinutes / 60);
  if (hours < 48) return `${hours}h ${totalMinutes % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

/** Live SLA countdown: mm:ss under an hour, coarser above. Ochre at 30 minutes. */
export function SlaCountdown({ dueAt }: { dueAt: string | null }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!dueAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [dueAt]);

  if (!dueAt) return <Typography.Text type="secondary">—</Typography.Text>;

  const remaining = Date.parse(dueAt) - now;
  const breached = remaining <= 0;
  const atRisk = !breached && remaining < 30 * MINUTE;
  const color = breached ? "error" : atRisk ? "warning" : "default";
  const label = breached ? `Breached ${formatDuration(remaining)}` : formatDuration(remaining);

  return (
    <Tooltip title={`SLA due ${new Date(dueAt).toLocaleString()}`}>
      <Tag color={color} icon={<ClockCircleOutlined />} style={{ marginInlineEnd: 0 }}>
        <span className="tabular">{label}</span>
      </Tag>
    </Tooltip>
  );
}

/** Relative age, e.g. "18m" — always with the absolute time behind a tooltip. */
export function RelativeTime({ value }: { value: string | null }) {
  if (!value) return <Typography.Text type="secondary">—</Typography.Text>;
  const elapsed = Date.now() - Date.parse(value);
  const minutes = Math.round(elapsed / MINUTE);
  const label =
    minutes < 60
      ? `${minutes}m`
      : minutes < 60 * 48
        ? `${Math.round(minutes / 60)}h`
        : `${Math.round(minutes / 1440)}d`;

  return (
    <Tooltip title={new Date(value).toLocaleString()}>
      <span className="tabular" style={{ fontSize: 13 }}>
        {label}
      </span>
    </Tooltip>
  );
}
