/**
 * The decision surface. Everything else on the product hangs off this component.
 *
 * One component, three placements: an actionable drawer on Queue, a read-only drawer
 * with a timeline on History, and an inline panel on Triage (`DecisionBody`). It is
 * on screen for most of the demo, and its job is one sentence long: make the AI's
 * decision legible, and reversible in two clicks.
 *
 * The system *recommends*. Nothing here executes a remediation, and no copy implies
 * that it does.
 */

import {
  CheckOutlined,
  CopyOutlined,
  ReloadOutlined,
  SwapOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Flex,
  Form,
  Input,
  Modal,
  Select,
  Skeleton,
  Space,
  Tabs,
  Tag,
  Timeline,
  Typography,
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import Markdown from "react-markdown";

import {
  api,
  type Team,
  type TicketDetail,
  type TimelineEvent,
} from "../api/client";
import SeverityTag, {
  ConfidenceMeter,
  SEVERITY_OPTIONS,
  STATUS,
  StatusTag,
  TEAM_LABEL,
  TEAM_OPTIONS,
  TeamTag,
} from "./SeverityTag";

const TIMELINE_COLOR: Record<TimelineEvent["kind"], string> = {
  triaged: "blue",
  override: "gold",
  approved: "green",
  synced: "green",
  failed: "red",
  resolved: "green",
  blocked: "red",
};

function formatMinutes(minutes: number) {
  if (minutes < 60) return `${minutes}m`;
  const hours = minutes / 60;
  return Number.isInteger(hours) ? `${hours}h` : `${hours.toFixed(1)}h`;
}

/**
 * Renders `[C1]` inside markdown text as a clickable chip that scrolls to the
 * matching evidence item. Applied to the leaf renderers rather than pre-parsing the
 * string, so markdown emphasis and lists keep working.
 */
function withCitations(children: React.ReactNode, onCite: (label: string) => void): React.ReactNode {
  const mapNode = (node: React.ReactNode, key: number): React.ReactNode => {
    if (typeof node !== "string") return node;
    const parts = node.split(/(\[C\d+\])/g);
    if (parts.length === 1) return node;
    return parts.map((part, index) => {
      const match = part.match(/^\[(C\d+)\]$/);
      if (!match) return part;
      return (
        <button
          key={`${key}-${index}`}
          type="button"
          className="citation-chip"
          onClick={() => onCite(match[1])}
          aria-label={`Jump to evidence ${match[1]}`}
        >
          {match[1]}
        </button>
      );
    });
  };

  return Array.isArray(children) ? children.map(mapNode) : mapNode(children, 0);
}

interface OverrideInput {
  field: "severity" | "assigned_team" | "priority_score";
  new_value: string;
  reason: string;
}

interface DecisionBodyProps {
  detail?: TicketDetail;
  loading?: boolean;
  error?: Error | null;
  onRetry?: () => void;
  readOnly?: boolean;
  /** Managers get Approve on an escalated decision. */
  canApprove?: boolean;
  onAccept?: () => void;
  onApprove?: () => void;
  onOverride?: (input: OverrideInput) => void;
  onRetriage?: () => void;
  busy?: boolean;
}

/**
 * The decision itself. Extracted from the drawer so Triage can render it inline
 * without a second implementation.
 */
export function DecisionBody({
  detail,
  loading = false,
  error,
  onRetry,
  readOnly = false,
  canApprove = false,
  onAccept,
  onApprove,
  onOverride,
  onRetriage,
  busy = false,
}: DecisionBodyProps) {
  const { message: toast } = App.useApp();
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const [overrideField, setOverrideField] = useState<OverrideInput["field"] | null>(null);
  const [form] = Form.useForm<OverrideInput>();
  const evidenceRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // Retrieval mode is a system-wide setting, not a per-ticket field; provenance
  // reads it from the same cached /health query the header uses.
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => api.health().then((r) => r.data),
    staleTime: 5 * 60_000,
  });

  useEffect(() => {
    if (!highlighted) return;
    const timer = window.setTimeout(() => setHighlighted(null), 2400);
    return () => window.clearTimeout(timer);
  }, [highlighted]);

  if (loading) return <Skeleton active paragraph={{ rows: 8 }} />;

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message="Could not load this decision"
        description={error.message}
        action={
          onRetry && (
            <Button size="small" onClick={onRetry}>
              Retry
            </Button>
          )
        }
      />
    );
  }

  if (!detail) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Select a ticket to see its decision." />;
  }

  const { ticket, decision, guardrails_fired: guardrails } = detail;
  const blocked = !decision;

  function jumpToCitation(label: string) {
    setHighlighted(label);
    evidenceRefs.current[label]?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function submitOverride(values: OverrideInput) {
    onOverride?.({ ...values, field: overrideField! });
    setOverrideField(null);
    form.resetFields();
  }

  const provenance = [
    { label: "Model", value: detail.model },
    { label: "Tier", value: detail.tier },
    { label: "Latency", value: `${(detail.latency_ms / 1000).toFixed(2)}s` },
    { label: "Tokens", value: detail.total_tokens.toLocaleString() },
    { label: "Cost", value: `$${detail.cost_usd.toFixed(4)}` },
    { label: "Trace id", value: detail.trace_id },
    { label: "Retrieval", value: health?.retrieval_mode ?? "—" },
    { label: "Source", value: ticket.source },
    { label: "Guardrails", value: guardrails.length ? guardrails.map((g) => g.type).join(", ") : "none fired" },
  ];

  return (
    <Flex vertical gap={24}>
      <Flex vertical gap={8}>
        <Flex align="baseline" gap={8} wrap>
          <span className="data" style={{ color: "var(--text-secondary)" }}>
            {ticket.external_id}
          </span>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {ticket.application} · {ticket.environment}
          </Typography.Text>
        </Flex>
        <Typography.Title level={4} style={{ margin: 0 }}>
          {ticket.title}
        </Typography.Title>
        <Space size={8} wrap>
          {/* No decision means no assessed severity — showing one would invent a fact. */}
          {decision ? <SeverityTag severity={ticket.severity} /> : <Tag>Severity not assessed</Tag>}
          <StatusTag status={ticket.status} />
          <TeamTag team={ticket.assigned_team} />
          {ticket.overridden_by && <Tag color="warning">Overridden by {ticket.overridden_by}</Tag>}
        </Space>
      </Flex>

      {!!guardrails.length && (
        <div className="blocked-panel">
          <Flex vertical gap={8}>
            <Flex align="center" gap={8}>
              <WarningOutlined style={{ color: "var(--error)" }} />
              <Typography.Text strong>
                {blocked ? "Blocked before a decision was made" : "Guardrails fired on this ticket"}
              </Typography.Text>
            </Flex>
            {guardrails.map((guardrail) => (
              <Typography.Text key={guardrail.type} style={{ fontSize: 13 }}>
                <strong>{guardrail.type.replace(/_/g, " ")}</strong>
                {guardrail.detail ? ` — ${guardrail.detail}` : ""}
              </Typography.Text>
            ))}
            {blocked && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Nothing was routed and nothing was written to Jira. A human decides what happens next.
              </Typography.Text>
            )}
          </Flex>
        </div>
      )}

      {decision && (
        <>
          {/* The one line a reader must get, before any detail. */}
          <div style={{ background: "var(--bg-surface-alt)", borderRadius: "var(--radius-md)", padding: 16 }}>
            <Typography.Text style={{ fontSize: 16, lineHeight: "24px" }}>
              Routed to <strong>{TEAM_LABEL[decision.assigned_team]}</strong> as{" "}
              <strong>{decision.severity}</strong>, priority{" "}
              <strong className="tabular">{decision.priority_score}</strong>, SLA{" "}
              <strong>{formatMinutes(decision.sla_target_mins)}</strong>, confidence{" "}
              <strong className="tabular">{(decision.confidence * 100).toFixed(0)}%</strong>.
            </Typography.Text>
            <Flex align="center" gap={12} style={{ marginTop: 12 }}>
              <ConfidenceMeter value={decision.confidence} />
              {decision.needs_human && <Tag color="warning">Held for human review</Tag>}
              {decision.duplicate_of && <Tag color="processing">Possible duplicate of {decision.duplicate_of}</Tag>}
            </Flex>
            {decision.needs_human && decision.escalation_reason && (
              <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginTop: 8, marginBottom: 0 }}>
                {decision.escalation_reason}
              </Typography.Paragraph>
            )}
          </div>

          <Flex vertical gap={8}>
            <span className="label">Rationale</span>
            <div className="markdown-body">
              <Markdown
                components={{
                  p: ({ children }) => <p>{withCitations(children, jumpToCitation)}</p>,
                  li: ({ children }) => <li>{withCitations(children, jumpToCitation)}</li>,
                }}
              >
                {decision.rationale}
              </Markdown>
            </div>
          </Flex>

          <Flex vertical gap={8}>
            <span className="label">Evidence</span>
            {decision.evidence.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No sources were cited." />
            ) : (
              decision.evidence.map((citation) => (
                <div
                  key={citation.label}
                  ref={(element) => {
                    evidenceRefs.current[citation.label] = element;
                  }}
                  className={`evidence-item ${highlighted === citation.label ? "is-highlighted" : ""}`}
                >
                  <Flex align="baseline" gap={8} wrap>
                    <span className="citation-chip" aria-hidden="true">
                      {citation.label}
                    </span>
                    <Typography.Text strong style={{ fontSize: 13 }}>
                      {citation.filename}
                    </Typography.Text>
                    {citation.page !== null && (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        page {citation.page}
                      </Typography.Text>
                    )}
                  </Flex>
                  <Typography.Paragraph
                    type="secondary"
                    style={{ fontSize: 13, marginBottom: 0, marginTop: 8 }}
                  >
                    {citation.snippet}
                  </Typography.Paragraph>
                </div>
              ))
            )}
          </Flex>

          <Flex vertical gap={8}>
            <span className="label">Suggested first action — recommendation only</span>
            <div className="recommendation">
              <Typography.Paragraph style={{ marginBottom: 8 }}>
                {decision.suggested_first_action}
              </Typography.Paragraph>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                TicketSphere does not execute remediation. A human runs this step.
              </Typography.Text>
            </div>
          </Flex>
        </>
      )}

      <Flex vertical gap={8}>
        <Flex align="center" justify="space-between">
          <span className="label">Provenance</span>
          <Button
            type="text"
            size="small"
            icon={<CopyOutlined />}
            aria-label="Copy provenance"
            onClick={() => {
              navigator.clipboard
                ?.writeText(provenance.map((row) => `${row.label}: ${row.value}`).join("\n"))
                .then(() => toast.success("Provenance copied"))
                .catch(() => toast.error("Clipboard unavailable"));
            }}
          >
            Copy
          </Button>
        </Flex>
        <Descriptions size="small" column={2} bordered items={provenance.map((row) => ({
          key: row.label,
          label: row.label,
          children: <span className="data">{row.value}</span>,
        }))} />
      </Flex>

      <Flex vertical gap={8}>
        <span className="label">Ticket body — PII masked at ingest</span>
        <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 0 }}>
          {detail.body_masked}
        </Typography.Paragraph>
      </Flex>

      {!readOnly && (
        <>
          <Divider style={{ margin: 0 }} />
          <Flex gap={8} wrap>
            {canApprove && ticket.needs_human && (
              <Button type="primary" icon={<CheckOutlined />} loading={busy} onClick={onApprove}>
                Approve escalation
              </Button>
            )}
            {!(canApprove && ticket.needs_human) && (
              <Button type="primary" icon={<CheckOutlined />} loading={busy} onClick={onAccept} disabled={blocked}>
                Accept decision
              </Button>
            )}
            <Button icon={<SwapOutlined />} disabled={blocked} onClick={() => setOverrideField("assigned_team")}>
              Reassign
            </Button>
            <Button disabled={blocked} onClick={() => setOverrideField("severity")}>
              Dispute severity
            </Button>
            <Button type="text" icon={<ReloadOutlined />} loading={busy} onClick={onRetriage}>
              Re-triage
            </Button>
          </Flex>
        </>
      )}

      <Modal
        open={overrideField !== null}
        title={overrideField === "severity" ? "Dispute the severity" : "Reassign to another team"}
        okText="Save override"
        onCancel={() => {
          setOverrideField(null);
          form.resetFields();
        }}
        onOk={() => form.submit()}
        confirmLoading={busy}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={submitOverride} requiredMark={false} preserve={false}>
          <Form.Item
            name="new_value"
            label={<span className="label">{overrideField === "severity" ? "New severity" : "New team"}</span>}
            rules={[{ required: true, message: "Pick a value" }]}
          >
            <Select
              options={overrideField === "severity" ? SEVERITY_OPTIONS : TEAM_OPTIONS}
              placeholder={overrideField === "severity" ? "Select a severity" : "Select a team"}
            />
          </Form.Item>
          <Form.Item
            name="reason"
            label={<span className="label">Reason</span>}
            extra="Your reason trains the eval set."
            rules={[{ required: true, min: 10, message: "At least 10 characters — say why" }]}
          >
            <Input.TextArea rows={3} showCount maxLength={400} placeholder="Why is the system wrong here?" />
          </Form.Item>
        </Form>
      </Modal>
    </Flex>
  );
}

interface DecisionDrawerProps {
  ticketId: string | null;
  open: boolean;
  onClose: () => void;
  readOnly?: boolean;
  canApprove?: boolean;
  /** History shows the decision alongside the story of what happened to it. */
  showTimeline?: boolean;
}

export default function DecisionDrawer({
  ticketId,
  open,
  onClose,
  readOnly = false,
  canApprove = false,
  showTimeline = false,
}: DecisionDrawerProps) {
  const { message: toast } = App.useApp();
  const queryClient = useQueryClient();

  const detailQuery = useQuery({
    queryKey: ["ticket", ticketId],
    queryFn: () => api.ticket(ticketId!).then((r) => r.data),
    enabled: open && !!ticketId,
  });

  const timelineQuery = useQuery({
    queryKey: ["ticket-timeline", ticketId],
    queryFn: () => api.ticketTimeline(ticketId!).then((r) => r.data),
    enabled: open && showTimeline && !!ticketId,
  });

  const invalidate = () => {
    ["tickets", "team-queue", "triage-analytics", "ticket", "ticket-timeline"].forEach((key) =>
      queryClient.invalidateQueries({ queryKey: [key] })
    );
  };

  const accept = useMutation({
    mutationFn: () => api.approve(ticketId!),
    onSuccess: ({ data }) => {
      toast.success(
        `Routed to ${TEAM_LABEL[(data.assigned_team ?? "ops") as Team]} · SLA ${formatMinutes(data.sla_target_mins)}`
      );
      invalidate();
      onClose();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const override = useMutation({
    mutationFn: (input: OverrideInput) => api.override(ticketId!, input),
    onSuccess: ({ data }) => {
      toast.success(
        `Override saved — ${data.severity} · ${TEAM_LABEL[(data.assigned_team ?? "ops") as Team]}`
      );
      invalidate();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const retriage = useMutation({
    mutationFn: () => api.retriage(ticketId!),
    onSuccess: ({ data }) => {
      toast.success(
        data.decision
          ? `Re-triaged in ${(data.total_ms / 1000).toFixed(1)}s · ${data.decision.severity} · ${(
              data.decision.confidence * 100
            ).toFixed(0)}% confidence`
          : "Re-triage blocked by guardrails — no decision was produced"
      );
      invalidate();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const busy = accept.isPending || override.isPending || retriage.isPending;

  const decisionPane = (
    <DecisionBody
      detail={detailQuery.data}
      loading={detailQuery.isPending}
      error={detailQuery.error as Error | null}
      onRetry={() => detailQuery.refetch()}
      readOnly={readOnly}
      canApprove={canApprove}
      busy={busy}
      onAccept={() => accept.mutate()}
      onApprove={() => accept.mutate()}
      onOverride={(input) => override.mutate(input)}
      onRetriage={() => retriage.mutate()}
    />
  );

  const timelinePane = useMemo(() => {
    if (timelineQuery.isPending) return <Skeleton active paragraph={{ rows: 6 }} />;
    if (timelineQuery.error) {
      return (
        <Alert
          type="error"
          showIcon
          message="Could not load the timeline"
          description={(timelineQuery.error as Error).message}
          action={
            <Button size="small" onClick={() => timelineQuery.refetch()}>
              Retry
            </Button>
          }
        />
      );
    }
    const events = timelineQuery.data ?? [];
    if (!events.length) {
      return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Nothing has happened to this ticket yet." />;
    }
    return (
      <Timeline
        items={events.map((event) => ({
          color: TIMELINE_COLOR[event.kind],
          children: (
            <Flex vertical gap={4}>
              <Typography.Text strong style={{ fontSize: 13 }}>
                {event.summary}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {event.actor} · {new Date(event.at).toLocaleString()}
              </Typography.Text>
            </Flex>
          ),
        }))}
      />
    );
  }, [timelineQuery.data, timelineQuery.error, timelineQuery.isPending]);

  const ticket = detailQuery.data?.ticket;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={560}
      destroyOnClose
      title={
        <Flex vertical gap={2}>
          <span className="data" style={{ color: "var(--text-secondary)" }}>
            {ticket?.external_id ?? "Decision"}
          </span>
          <Typography.Text strong>{readOnly ? "Decision record" : "Decision"}</Typography.Text>
        </Flex>
      }
      extra={ticket ? <Tag>{STATUS[ticket.status].label}</Tag> : null}
      styles={{ body: { paddingTop: 16 }, wrapper: { boxShadow: "var(--shadow-float)" } }}
    >
      {showTimeline ? (
        <Tabs
          items={[
            { key: "decision", label: "Decision", children: decisionPane },
            { key: "timeline", label: "Timeline", children: timelinePane },
          ]}
        />
      ) : (
        decisionPane
      )}
    </Drawer>
  );
}
