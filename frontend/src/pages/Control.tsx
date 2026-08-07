/**
 * The manager control tower.
 *
 * Four rows: what is happening now, what the trend looks like, what is waiting on a
 * human, and where the system has been wrong lately. Every number on this screen
 * comes from `/analytics/triage` — nothing is summed in the browser from whichever
 * page of rows a table happens to hold, because that number would be wrong and
 * nobody would notice.
 */

import { CheckOutlined, ReloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Empty,
  Flex,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Skeleton,
  Space,
  Table,
  Tooltip,
  Typography,
} from "antd";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api, type Severity, type TicketRow } from "../api/client";
import {
  CHART_HEIGHT,
  GRID,
  SERIES,
  animationFor,
  axisProps,
  legendProps,
  tooltipProps,
} from "../components/chartTheme";
import DecisionDrawer from "../components/DecisionDrawer";
import SeverityTag, {
  ConfidenceMeter,
  SEVERITY_OPTIONS,
  TEAM_LABEL,
  TEAM_OPTIONS,
  TeamTag,
} from "../components/SeverityTag";
import StatTile from "../components/StatTile";
import { useUiStore } from "../store/ui";

const SEVERITY_TONE = { S1: "error", S2: "warning", S3: "info", S4: "default" } as const;

function ChartCard({
  title,
  loading,
  empty,
  children,
}: {
  title: string;
  loading: boolean;
  empty: boolean;
  children: React.ReactElement;
}) {
  return (
    <Card size="small" title={title} className="chart-card">
      {loading ? (
        <Skeleton active paragraph={{ rows: 5 }} />
      ) : empty ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data in this window yet." />
      ) : (
        <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
          {children}
        </ResponsiveContainer>
      )}
    </Card>
  );
}

export default function Control() {
  const { message: toast } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [overrideTarget, setOverrideTarget] = useState<TicketRow | null>(null);
  const [form] = Form.useForm<{ field: "severity" | "assigned_team"; new_value: string; reason: string }>();

  const selectedTicketId = useUiStore((state) => state.selectedTicketId);
  const drawerOpen = useUiStore((state) => state.drawerOpen);
  const openTicket = useUiStore((state) => state.openTicket);
  const closeDrawer = useUiStore((state) => state.closeDrawer);

  const analytics = useQuery({
    queryKey: ["triage-analytics"],
    queryFn: () => api.triageAnalytics().then((r) => r.data),
    refetchInterval: 10_000,
  });

  const approvalParams = useMemo(
    () => ({ page: 1, page_size: 10, sort: "priority_score", order: "desc" as const, filter: { needs_human: "true" } }),
    []
  );

  const approvals = useQuery({
    queryKey: ["team-queue", approvalParams],
    queryFn: () => api.teamQueue(approvalParams),
    refetchInterval: 10_000,
  });

  const invalidate = () =>
    ["tickets", "team-queue", "triage-analytics"].forEach((key) =>
      queryClient.invalidateQueries({ queryKey: [key] })
    );

  const approve = useMutation({
    mutationFn: (id: string) => api.approve(id),
    onSuccess: ({ data }) => {
      toast.success(`Approved — routed to ${TEAM_LABEL[data.assigned_team ?? "ops"]}`);
      invalidate();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const override = useMutation({
    mutationFn: (input: { id: string; field: string; new_value: string; reason: string }) =>
      api.override(input.id, { field: input.field, new_value: input.new_value, reason: input.reason }),
    onSuccess: ({ data }) => {
      toast.success(`Override saved on ${data.external_id}`);
      setOverrideTarget(null);
      form.resetFields();
      invalidate();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const data = analytics.data;
  const loading = analytics.isPending;
  const countFor = (severity: Severity) =>
    data?.by_severity.find((entry) => entry.severity === severity)?.count;

  // The only tile with a real history behind it: `over_time` carries triaged and
  // overridden per day, so the override-rate sparkline is measured, not invented.
  const overrideTrend = (data?.over_time ?? [])
    .filter((day) => day.triaged > 0)
    .map((day) => (day.overridden / day.triaged) * 100);

  const teamSeries = (data?.by_team ?? []).map((entry) => ({
    team: TEAM_LABEL[entry.team],
    open: entry.open,
    capacity: entry.capacity,
  }));

  if (analytics.error) {
    return (
      <Alert
        type="error"
        showIcon
        message="Control tower is unavailable"
        description={(analytics.error as Error).message}
        action={
          <Button size="small" onClick={() => analytics.refetch()}>
            Retry
          </Button>
        }
      />
    );
  }

  return (
    <Flex vertical gap={24}>
      <Flex align="flex-end" justify="space-between" gap={16} wrap>
        <Flex vertical gap={4}>
          <h1 className="page-title">Control Tower</h1>
          <p className="page-subtitle">
            Four queues, one view — what is at risk, what is waiting on you, and where the system
            has been wrong.
          </p>
        </Flex>
        <Button icon={<ReloadOutlined />} loading={analytics.isFetching} onClick={() => analytics.refetch()}>
          Refresh
        </Button>
      </Flex>

      <Row gutter={[16, 16]}>
        {(["S1", "S2", "S3", "S4"] as Severity[]).map((severity) => (
          <Col xs={12} md={6} xl={3} key={severity}>
            <StatTile
              label={`${severity} open`}
              value={countFor(severity)}
              tone={SEVERITY_TONE[severity]}
              loading={loading}
            />
          </Col>
        ))}
        <Col xs={12} md={6} xl={3}>
          <StatTile
            label="SLA at risk"
            value={data?.sla_at_risk}
            tone={data?.sla_at_risk ? "warning" : "default"}
            loading={loading}
            hint="Under 30 minutes to the response target"
          />
        </Col>
        <Col xs={12} md={6} xl={3}>
          <StatTile
            label="Awaiting approval"
            value={data?.awaiting_approval}
            tone={data?.awaiting_approval ? "warning" : "default"}
            loading={loading}
          />
        </Col>
        <Col xs={12} md={6} xl={3}>
          <StatTile
            label="Classification accuracy"
            value={data ? (data.classification_accuracy * 100).toFixed(1) : null}
            suffix="%"
            tone="success"
            loading={loading}
            hint="Against the labelled eval set"
          />
        </Col>
        <Col xs={12} md={6} xl={3}>
          <StatTile
            label="Routing precision"
            value={data ? (data.routing_precision * 100).toFixed(1) : null}
            suffix="%"
            tone="success"
            loading={loading}
          />
        </Col>
        <Col xs={12} md={6} xl={3}>
          <StatTile
            label="Override rate"
            value={data ? (data.override_rate * 100).toFixed(1) : null}
            suffix="%"
            tone={data && data.override_rate > 0.2 ? "warning" : "default"}
            trend={overrideTrend}
            loading={loading}
            hint="How often a human corrected the system"
          />
        </Col>
        <Col xs={12} md={6} xl={3}>
          <StatTile
            label="Severity MAE"
            value={data ? data.severity_mae.toFixed(2) : null}
            loading={loading}
            hint="Mean absolute error in severity levels"
          />
        </Col>
        <Col xs={12} md={6} xl={3}>
          <StatTile
            label="Avg cost / decision"
            value={data ? `$${data.avg_cost_usd.toFixed(4)}` : null}
            loading={loading}
          />
        </Col>
        <Col xs={12} md={6} xl={3}>
          <StatTile
            label="Avg latency"
            value={data ? (data.avg_latency_ms / 1000).toFixed(1) : null}
            suffix="s"
            loading={loading}
          />
        </Col>
        <Col xs={12} md={6} xl={3}>
          <StatTile
            label="Tokens today"
            value={data?.tokens_today?.toLocaleString() ?? null}
            loading={loading}
            hint="Reported by the analytics endpoint, not summed in the browser"
          />
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={12}>
          <ChartCard title="Open tickets by severity" loading={loading} empty={!data?.by_severity.length}>
            <BarChart data={data?.by_severity ?? []}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="severity" {...axisProps} />
              <YAxis allowDecimals={false} {...axisProps} />
              <ReTooltip {...tooltipProps} />
              <Legend {...legendProps} />
              <Bar dataKey="count" name="open" fill={SERIES[0]} radius={[4, 4, 0, 0]} {...animationFor(0)} />
            </BarChart>
          </ChartCard>
        </Col>

        <Col xs={24} xl={12}>
          <ChartCard title="Load against capacity, by team" loading={loading} empty={!teamSeries.length}>
            <BarChart data={teamSeries}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="team" {...axisProps} />
              <YAxis allowDecimals={false} {...axisProps} />
              <ReTooltip {...tooltipProps} />
              <Legend {...legendProps} />
              <Bar dataKey="open" name="open" fill={SERIES[0]} radius={[4, 4, 0, 0]} {...animationFor(0)} />
              <Bar dataKey="capacity" name="capacity" fill={SERIES[1]} radius={[4, 4, 0, 0]} {...animationFor(1)} />
            </BarChart>
          </ChartCard>
        </Col>

        <Col xs={24} xl={12}>
          <ChartCard title="Decisions over time, with overrides" loading={loading} empty={!data?.over_time.length}>
            <LineChart data={data?.over_time ?? []}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
              <XAxis dataKey="date" {...axisProps} />
              <YAxis allowDecimals={false} {...axisProps} />
              <ReTooltip {...tooltipProps} />
              <Legend {...legendProps} />
              <Line
                dataKey="triaged"
                name="triaged"
                stroke={SERIES[0]}
                dot={false}
                strokeWidth={2}
                {...animationFor(0)}
              />
              <Line
                dataKey="overridden"
                name="overridden"
                stroke={SERIES[2]}
                dot={false}
                strokeWidth={2}
                {...animationFor(1)}
              />
            </LineChart>
          </ChartCard>
        </Col>

        <Col xs={24} xl={12}>
          <ChartCard title="Category mix" loading={loading} empty={!data?.by_category?.length}>
            <BarChart data={data?.by_category ?? []} layout="vertical" margin={{ left: 24 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" allowDecimals={false} {...axisProps} />
              <YAxis type="category" dataKey="category" width={110} {...axisProps} />
              <ReTooltip {...tooltipProps} />
              <Legend {...legendProps} />
              <Bar dataKey="count" name="tickets" fill={SERIES[3]} radius={[0, 4, 4, 0]} {...animationFor(0)} />
            </BarChart>
          </ChartCard>
        </Col>
      </Row>

      <Card size="small" title="Approval queue — decisions the system stopped">
        <Table<TicketRow>
          rowKey="id"
          size="small"
          loading={approvals.isFetching && !approvals.data}
          dataSource={approvals.data?.data ?? []}
          scroll={{ x: true }}
          pagination={false}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="Nothing is waiting on you. Every decision cleared its own gate."
              />
            ),
          }}
          onRow={(row) => ({ onClick: () => openTicket(row.id), style: { cursor: "pointer" } })}
          columns={[
            {
              title: "Ticket",
              dataIndex: "external_id",
              width: 130,
              render: (value: string) => <span className="data">{value}</span>,
            },
            { title: "Title", dataIndex: "title", ellipsis: true },
            {
              title: "Severity",
              dataIndex: "severity",
              width: 136,
              render: (_v, row) => <SeverityTag severity={row.severity} />,
            },
            {
              title: "Team",
              dataIndex: "assigned_team",
              width: 108,
              render: (_v, row) => <TeamTag team={row.assigned_team} />,
            },
            {
              title: "Confidence",
              dataIndex: "confidence",
              width: 128,
              render: (value: number) => <ConfidenceMeter value={value} />,
            },
            {
              // The most important column: why the system refused to decide alone.
              title: "Why it stopped",
              dataIndex: "id",
              width: 240,
              render: (_v, row) => (
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                  {row.confidence < 0.7
                    ? "Confidence below the routing gate"
                    : row.severity === "S1"
                      ? "S1 on a production path always needs a human"
                      : "Held by policy for manager approval"}
                </Typography.Text>
              ),
            },
            {
              title: "",
              width: 190,
              render: (_v, row) => (
                <Space size={4} onClick={(event) => event.stopPropagation()}>
                  <Tooltip title="Approving requires no reason. Overriding always does.">
                    <Button
                      type="primary"
                      size="small"
                      icon={<CheckOutlined />}
                      loading={approve.isPending && approve.variables === row.id}
                      onClick={() => approve.mutate(row.id)}
                    >
                      Approve
                    </Button>
                  </Tooltip>
                  <Button size="small" onClick={() => setOverrideTarget(row)}>
                    Override
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Card size="small" title="Recent overrides — where the system was corrected">
        {data?.recent_overrides === undefined && !loading ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="The analytics endpoint is not reporting overrides yet."
          />
        ) : (
          <Table
            rowKey="ticket_id"
            size="small"
            loading={loading}
            dataSource={(data?.recent_overrides ?? []).slice(0, 10)}
            pagination={false}
            scroll={{ x: true }}
            locale={{
              emptyText: (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No overrides in this window." />
              ),
            }}
            columns={[
              {
                title: "Ticket",
                dataIndex: "external_id",
                width: 130,
                render: (value: string) => <span className="data">{value}</span>,
              },
              { title: "Title", dataIndex: "title", ellipsis: true },
              { title: "Field", dataIndex: "field", width: 130 },
              {
                title: "Change",
                width: 140,
                render: (_v, row: any) => (
                  <span className="data">
                    {row.from} → {row.to}
                  </span>
                ),
              },
              { title: "By", dataIndex: "by", width: 110 },
              { title: "Reason", dataIndex: "reason", ellipsis: true },
              {
                title: "",
                width: 90,
                render: () => (
                  <Button type="link" size="small" onClick={() => navigate("/history")}>
                    History
                  </Button>
                ),
              },
            ]}
          />
        )}
      </Card>

      <DecisionDrawer ticketId={selectedTicketId} open={drawerOpen} onClose={closeDrawer} canApprove />

      <Modal
        open={!!overrideTarget}
        title={`Override ${overrideTarget?.external_id ?? ""}`}
        okText="Save override"
        confirmLoading={override.isPending}
        onCancel={() => {
          setOverrideTarget(null);
          form.resetFields();
        }}
        onOk={() => form.submit()}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          requiredMark={false}
          preserve={false}
          initialValues={{ field: "severity" }}
          onFinish={(values) =>
            override.mutate({
              id: overrideTarget!.id,
              field: values.field,
              new_value: values.new_value,
              reason: values.reason,
            })
          }
        >
          <Form.Item name="field" label={<span className="label">Field</span>}>
            <Select
              options={[
                { value: "severity", label: "Severity" },
                { value: "assigned_team", label: "Assigned team" },
              ]}
              onChange={() => form.setFieldValue("new_value", undefined)}
            />
          </Form.Item>

          <Form.Item noStyle shouldUpdate={(prev, next) => prev.field !== next.field}>
            {({ getFieldValue }) => (
              <Form.Item
                name="new_value"
                label={<span className="label">New value</span>}
                rules={[{ required: true, message: "Pick a value" }]}
              >
                <Select
                  options={getFieldValue("field") === "severity" ? SEVERITY_OPTIONS : TEAM_OPTIONS}
                  placeholder="Select a value"
                />
              </Form.Item>
            )}
          </Form.Item>

          <Form.Item
            name="reason"
            label={<span className="label">Reason</span>}
            extra="Your reason trains the eval set."
            rules={[{ required: true, min: 10, message: "At least 10 characters — say why" }]}
          >
            <Input.TextArea rows={3} showCount maxLength={400} />
          </Form.Item>
        </Form>
      </Modal>
    </Flex>
  );
}
