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
  Tooltip,
  Typography,
} from "antd";
import { useMemo, useState } from "react";
import Markdown from "react-markdown";

import {
  api,
  ApiError,
  type RetrievedChunk,
  type Severity,
  type Team,
  type TicketDetail,
  type TicketStatus,
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

const TIMELINE_COLOR: Record<string, string> = {
  triaged: "blue",
  override: "gold",
  approved: "green",
  synced: "green",
  failed: "red",
  resolved: "green",
  blocked: "red",
};

function formatMinutes(minutes: number | undefined | null) {
  if (minutes == null || Number.isNaN(minutes)) return "—";
  if (minutes < 60) return `${minutes}m`;
  const hours = minutes / 60;
  return Number.isInteger(hours) ? `${hours}h` : `${hours.toFixed(1)}h`;
}

/**
 * Turn stored rationale into a short bullet list for the drawer.
 * Handles both the new "- **Type:** …" form and older multi-paragraph text.
 */
function simplifyRationale(raw: string): string {
  const text = (raw || "").trim();
  if (!text) return "";

  // Already short bullet form from the composer.
  if (/^-\s+\*\*/m.test(text) && text.split("\n").filter(Boolean).length <= 6) {
    return text;
  }

  const bullets: string[] = [];
  const sections = text.split(/\n\s*\n|\n(?=\*\*)/);
  for (const block of sections) {
    const cleaned = block
      .replace(/^\*\*(.+?)\*\*\s*/gm, "")
      .replace(/\n+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (!cleaned) continue;
    let line = cleaned;
    if (line.length > 160) {
      const cut = line.indexOf(". ");
      if (cut >= 40 && cut <= 160) line = line.slice(0, cut + 1);
      else line = `${line.slice(0, 157)}…`;
    }
    bullets.push(`- ${line}`);
    if (bullets.length >= 4) break;
  }

  return bullets.length ? bullets.join("\n") : `- ${text.slice(0, 200)}${text.length > 200 ? "…" : ""}`;
}

/** Renders `[C1]` as a static chip inside markdown leaves. */
function withCitations(children: React.ReactNode): React.ReactNode {
  const mapNode = (node: React.ReactNode, key: number): React.ReactNode => {
    if (typeof node !== "string") return node;
    const parts = node.split(/(\[C\d+\])/g);
    if (parts.length === 1) return node;
    return parts.map((part, index) => {
      const match = part.match(/^\[(C\d+)\]$/);
      if (!match) return part;
      return (
        <span key={`${key}-${index}`} className="citation-chip" aria-hidden="true">
          {match[1]}
        </span>
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
  const [overrideField, setOverrideField] = useState<OverrideInput["field"] | null>(null);
  const [form] = Form.useForm<OverrideInput>();

  // Retrieval mode is a system-wide setting, not a per-ticket field; provenance
  // reads it from the same cached /health query the header uses.
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => api.health().then((r) => r.data),
    staleTime: 5 * 60_000,
  });

  const ticketForSearch = detail?.ticket;
  const similarQuery = useQuery({
    queryKey: ["similar-tickets", ticketForSearch?.id, ticketForSearch?.title],
    queryFn: () =>
      api
        .search(ticketForSearch!.title || ticketForSearch!.external_id, {
          top_k: 6,
          exclude_ticket_id: ticketForSearch!.id,
          exclude_external_id: ticketForSearch!.external_id || undefined,
          filters: { doc_type: "ticket_history" },
        })
        .then((r) => r.data),
    enabled: !!ticketForSearch?.id && !!ticketForSearch?.title,
    staleTime: 60_000,
  });

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

  const externalKey = (ticket.external_id || "").trim();
  const otherEvidence = (decision?.evidence ?? []).filter((citation) => {
    if (!externalKey) return true;
    return !citation.filename.includes(externalKey) && citation.doc_id !== ticket.id;
  });
  const similarTickets: RetrievedChunk[] = similarQuery.data ?? [];

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

  // Ticket row wins after override; decision_json keeps the AI recommendation.
  const displaySeverity = (ticket.severity || decision?.severity || "") as Severity | "";
  const displayTeam = (ticket.assigned_team || decision?.assigned_team || null) as Team | null;
  const aiSeverity = (decision?.severity || "") as Severity | "";
  const aiTeam = (decision?.assigned_team || null) as Team | null;
  const priorityOverridden =
    !!ticket.overridden_by && !!aiSeverity && !!displaySeverity && aiSeverity !== displaySeverity;
  const teamOverridden =
    !!ticket.overridden_by && !!aiTeam && !!displayTeam && aiTeam !== displayTeam;
  const showOverrideBanner = !!ticket.overridden_by && (priorityOverridden || teamOverridden || !!ticket.override_reason);

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
          {displaySeverity ? (
            <SeverityTag severity={displaySeverity as Severity} />
          ) : (
            <Tag>Priority not assessed</Tag>
          )}
          <StatusTag status={ticket.status} />
          <TeamTag team={displayTeam} />
          <Tag style={{ marginInlineEnd: 0 }}>{ticket.source}</Tag>
          {ticket.overridden_by && <Tag color="warning">Overridden by {ticket.overridden_by}</Tag>}
        </Space>
      </Flex>

      {showOverrideBanner && (
        <Alert
          type="warning"
          showIcon
          message="Human override applied"
          description={
            [
              priorityOverridden ? `Priority: AI suggested ${aiSeverity} → ${displaySeverity}` : null,
              teamOverridden
                ? `Team: AI suggested ${TEAM_LABEL[aiTeam!] ?? aiTeam} → ${TEAM_LABEL[displayTeam!] ?? displayTeam}`
                : null,
              !priorityOverridden && !teamOverridden && displaySeverity
                ? `Current priority: ${displaySeverity}${displayTeam ? ` · team ${TEAM_LABEL[displayTeam] ?? displayTeam}` : ""}`
                : null,
              ticket.override_reason ? `Reason: ${ticket.override_reason}` : null,
            ]
              .filter(Boolean)
              .join(". ")
          }
        />
      )}

      {ticket.status === "failed" && (
        <Alert
          type="error"
          showIcon
          message="Last sync / triage failed"
          description={
            ticket.last_error?.trim() ||
            "The model did not finish this run. Priority and team below may be from an earlier attempt — re-run Sync Now when the LLM is healthy."
          }
        />
      )}

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
              Routed to{" "}
              <strong>{TEAM_LABEL[displayTeam || decision.assigned_team] ?? displayTeam}</strong> as
              Priority <strong>{displaySeverity || decision.severity}</strong>, score{" "}
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
            <span className="label">Why we decided this</span>
            {simplifyRationale(decision.rationale) ? (
              <div className="markdown-body rationale-body">
                <Markdown
                  components={{
                    p: ({ children }) => <p>{withCitations(children)}</p>,
                    li: ({ children }) => <li>{withCitations(children)}</li>,
                    strong: ({ children }) => <strong>{children}</strong>,
                  }}
                >
                  {simplifyRationale(decision.rationale)}
                </Markdown>
              </div>
            ) : (
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                {ticket.status === "failed"
                  ? "No explanation on the last successful run either — re-triage after the model is available."
                  : "This is a thin tracker-style ticket (no active outage named), so confidence stays low until a human confirms."}
              </Typography.Text>
            )}
          </Flex>

          <Flex vertical gap={8}>
            <span className="label">Sources used</span>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Runbooks and other tickets cited for this decision (this ticket excluded).
            </Typography.Text>
            {otherEvidence.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  ticket.status === "failed"
                    ? "No sources on this run — sync failed before retrieval completed."
                    : "No matching runbook cited. Upload an Ops reliability-tracker guide if you want this ticket type grounded."
                }
              />
            ) : (
              otherEvidence.map((citation) => (
                <div key={citation.label} className="evidence-item">
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
            <span className="label">Similar tickets</span>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Other indexed incidents like this one — not the ticket you have open.
            </Typography.Text>
            {similarQuery.isPending ? (
              <Skeleton active paragraph={{ rows: 3 }} />
            ) : similarTickets.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="No other similar tickets in the knowledge base yet. Sync more incidents or re-seed runbooks."
              />
            ) : (
              similarTickets.map((chunk) => (
                <div key={chunk.id} className="evidence-item">
                  <Flex justify="space-between" gap={8} wrap>
                    <Typography.Text strong style={{ fontSize: 13 }}>
                      {(chunk.metadata?.external_id as string) || chunk.filename}
                    </Typography.Text>
                    <span className="tabular" style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                      {(chunk.score * 100).toFixed(0)}% match
                    </span>
                  </Flex>
                  <Typography.Paragraph
                    type="secondary"
                    style={{ fontSize: 13, marginBottom: 0, marginTop: 8 }}
                  >
                    {chunk.text.slice(0, 280)}
                    {chunk.text.length > 280 ? "…" : ""}
                  </Typography.Paragraph>
                </div>
              ))
            )}
          </Flex>

          <Flex vertical gap={8}>
            <span className="label">Suggested first step</span>
            <div className="recommendation">
              <Typography.Paragraph style={{ marginBottom: 8 }}>
                {decision.suggested_first_action?.trim() ||
                  ((decision.subcategory || decision.category || "").toLowerCase().includes("incident")
                    ? "Treat as a reliability tracker: confirm no linked active outage, keep with Ops, set a review date."
                    : "No runbook step recorded — use engineer judgement.")}
              </Typography.Paragraph>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Recommendation only — TicketSphere does not change production. A human runs this.
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
              Dispute priority
            </Button>
            {onRetriage && (
              <Tooltip title="Re-runs the triage graph. Not available on all backends.">
                <Button type="text" icon={<ReloadOutlined />} loading={busy} onClick={onRetriage}>
                  Re-triage
                </Button>
              </Tooltip>
            )}
          </Flex>
        </>
      )}

      <Modal
        open={overrideField !== null}
        title={overrideField === "severity" ? "Dispute the priority" : "Reassign to another team"}
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
            label={<span className="label">{overrideField === "severity" ? "New priority" : "New team"}</span>}
            rules={[{ required: true, message: "Pick a value" }]}
          >
            <Select
              options={overrideField === "severity" ? SEVERITY_OPTIONS : TEAM_OPTIONS}
              placeholder={overrideField === "severity" ? "Select a priority" : "Select a team"}
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
      const team = (data.assigned_team || "ops") as Team;
      toast.success(
        `Routed to ${TEAM_LABEL[team] ?? team} · SLA ${formatMinutes(data.sla_target_mins)}`
      );
      invalidate();
      onClose();
    },
    onError: (error: Error) => {
      if (error instanceof ApiError && error.status === 409) {
        toast.error(error.message || "Ticket is not ready to approve (needs priority + team).");
        return;
      }
      toast.error(error.message);
    },
  });

  const override = useMutation({
    mutationFn: (input: OverrideInput) => api.override(ticketId!, input),
    onSuccess: ({ data }) => {
      const team = (data.assigned_team || "ops") as Team;
      toast.success(
        `Override routed — ${data.severity || "—"} · ${TEAM_LABEL[team] ?? team} (written to Jira)`
      );
      invalidate();
      onClose();
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
  // Live backend has no POST /tickets/:id/retriage — hide the control (api.retriage still
  // soft-fails if something else wires it).
  const canRetriage = false;

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
      onRetriage={canRetriage ? () => retriage.mutate() : undefined}
    />
  );

  const timelinePane = useMemo(() => {
    if (timelineQuery.isPending) return <Skeleton active paragraph={{ rows: 6 }} />;
    const events = timelineQuery.data ?? [];
    // Backend may not implement /timeline — empty is fine for demo.
    if (timelineQuery.error || !events.length) {
      const ticket = detailQuery.data?.ticket;
      return (
        <Flex vertical gap={12}>
          {ticket && (
            <Alert
              type="info"
              showIcon
              message={`${ticket.external_id} · ${ticket.source}`}
              description={
                ticket.last_error
                  ? `Last error: ${ticket.last_error}`
                  : `Status ${ticket.status}. Full timeline API is not available — showing ticket fields only.`
              }
            />
          )}
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No timeline events yet." />
        </Flex>
      );
    }
    return (
      <Timeline
        items={events.map((event) => ({
          color: TIMELINE_COLOR[event.kind] ?? "gray",
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
      extra={
        ticket ? (
          <Tag>{STATUS[ticket.status as TicketStatus]?.label ?? ticket.status}</Tag>
        ) : null
      }
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
