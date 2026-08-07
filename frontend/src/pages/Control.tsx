/**
 * The manager control tower.
 *
 * KPI strip + filters drive the approval queue; charts visualise load, throughput,
 * and category mix. Priority open volume is a pie (not four tiles + a duplicate bar).
 * Every aggregate comes from `/analytics/triage` — nothing is summed from a table page.
 */

import { CheckOutlined, CloudSyncOutlined, ReloadOutlined } from "@ant-design/icons";
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
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ApiError, api, type Severity, type TicketRow } from "../api/client";
import {
  ANIMATION,
  CHART_HEIGHT,
  GRID,
  PRIORITY_COLORS,
  SERIES,
  animationFor,
  axisProps,
  legendProps,
  tooltipProps,
} from "../components/chartTheme";
import DecisionDrawer from "../components/DecisionDrawer";
import SeverityTag, {
  CATEGORY_OPTIONS,
  ConfidenceMeter,
  SEVERITY_OPTIONS,
  TEAM_LABEL,
  TEAM_OPTIONS,
  TeamTag,
} from "../components/SeverityTag";
import StatTile from "../components/StatTile";
import { useUiStore } from "../store/ui";

type WindowDays = "7" | "30" | "all";

interface ControlFilters {
  severity?: string;
  assigned_team?: string;
  category?: string;
  window: WindowDays;
}

const WINDOW_OPTIONS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "all", label: "All time" },
];

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

function cutoffIso(window: WindowDays): string | undefined {
  if (window === "all") return undefined;
  const days = Number(window);
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

export default function Control() {
  const { message: toast } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [overrideTarget, setOverrideTarget] = useState<TicketRow | null>(null);
  const [filters, setFilters] = useState<ControlFilters>({ window: "30" });
  const [form] = Form.useForm<{ field: "severity" | "assigned_team"; new_value: string; reason: string }>();

  const selectedTicketId = useUiStore((state) => state.selectedTicketId);
  const drawerOpen = useUiStore((state) => state.drawerOpen);
  const openTicket = useUiStore((state) => state.openTicket);
  const closeDrawer = useUiStore((state) => state.closeDrawer);

  const [syncActive, setSyncActive] = useState(false);

  const analytics = useQuery({
    queryKey: ["triage-analytics"],
    queryFn: () => api.triageAnalytics().then((r) => r.data),
    // Faster poll while Sync Now is in flight so the tower fills as tickets land.
    refetchInterval: syncActive ? 3_000 : 10_000,
  });

  const approvalParams = useMemo(() => {
    // Do not lock to status=awaiting_approval only — failed Syncs used to flip
    // human-gated SCRUM tickets to status=failed and they dropped out of this list.
    const filter: Record<string, string> = {};
    if (filters.severity) filter.severity = filters.severity;
    if (filters.assigned_team) filter.assigned_team = filters.assigned_team;
    if (filters.category) filter.category = filters.category;
    return {
      page: 1,
      page_size: 50,
      sort: "priority_score",
      order: "desc" as const,
      filter,
    };
  }, [filters.severity, filters.assigned_team, filters.category]);

  const approvals = useQuery({
    queryKey: ["team-queue", "approval", approvalParams],
    queryFn: () => api.teamQueue(approvalParams),
    refetchInterval: syncActive ? 3_000 : 10_000,
  });

  const approvalRows = useMemo(() => {
    const rows = approvals.data?.data ?? [];
    return rows.filter((row) => {
      // Routed / approved / overridden decisions leave this queue.
      if (row.status === "routed" || row.status === "approved" || row.status === "synced" || row.status === "resolved") {
        return false;
      }
      if (!row.needs_human) return false;
      if (row.status === "awaiting_approval") return true;
      // Still needs a human, already classified — show even if last sync failed.
      if (row.severity && row.assigned_team) {
        return row.status === "failed" || row.status === "triaged" || row.status === "new";
      }
      return false;
    });
  }, [approvals.data?.data]);
  const invalidate = () =>
    ["tickets", "team-queue", "triage-analytics"].forEach((key) =>
      queryClient.invalidateQueries({ queryKey: [key] })
    );

  const syncNow = useMutation({
    mutationFn: () => {
      setSyncActive(true);
      toast.open({
        type: "loading",
        content: "Syncing Jira — pull + triage can take several minutes…",
        key: "jira-sync",
        duration: 0,
      });
      return api.syncNow();
    },
    onSuccess: ({ data }) => {
      const watermark = data.watermark ? ` · watermark ${data.watermark}` : "";
      toast.open({
        type: "success",
        content: `Jira sync: pulled ${data.pulled}, triaged ${data.triaged}, failed ${data.failed}${watermark}`,
        key: "jira-sync",
        duration: 8,
      });
      if (data.error) toast.warning(data.error);
      invalidate();
    },
    onError: (error: Error) =>
      toast.open({
        type: "error",
        content: error.message || "Jira sync failed",
        key: "jira-sync",
        duration: 6,
      }),
    onSettled: () => {
      setSyncActive(false);
      invalidate();
    },
  });

  const recalcConfidence = useMutation({
    mutationFn: () => api.recalculateConfidence(),
    onSuccess: ({ data }) => {
      toast.success(
        `Confidence recalculated for ${data.updated} ticket${data.updated === 1 ? "" : "s"}` +
          (data.failed ? ` (${data.failed} failed)` : "")
      );
      invalidate();
    },
    onError: (error: Error) => toast.error(error.message || "Confidence recalculation failed"),
  });

  const approve = useMutation({
    mutationFn: (id: string) => api.approve(id),
    onSuccess: ({ data }) => {
      toast.success(`Approved — routed to ${TEAM_LABEL[(data.assigned_team as keyof typeof TEAM_LABEL) ?? "ops"] ?? data.assigned_team}`);
      invalidate();
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
    mutationFn: (input: { id: string; field: string; new_value: string; reason: string }) =>
      api.override(input.id, { field: input.field, new_value: input.new_value, reason: input.reason }),
    onSuccess: ({ data }) => {
      toast.success(
        `Override routed — ${data.external_id} · ${data.severity || "—"} (written to Jira)`
      );
      setOverrideTarget(null);
      form.resetFields();
      invalidate();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const data = analytics.data;
  const loading = analytics.isPending;
  const since = cutoffIso(filters.window);

  const priorityPie = useMemo(() => {
    const counts = new Map(
      (data?.by_severity ?? []).map((entry) => [entry.severity, entry.count] as const)
    );
    return (["Highest", "High", "Medium", "Low"] as Severity[])
      .filter((severity) => !filters.severity || filters.severity === severity)
      .map((severity) => ({
        name: severity,
        value: counts.get(severity) ?? 0,
      }))
      .filter((slice) => slice.value > 0 || !filters.severity);
  }, [data?.by_severity, filters.severity]);

  const teamUtilization = useMemo(() => {
    return (data?.by_team ?? [])
      .filter((entry) => !filters.assigned_team || entry.team === filters.assigned_team)
      .map((entry) => {
        const util = entry.capacity > 0 ? Math.round((entry.open / entry.capacity) * 100) : 0;
        return {
          team: TEAM_LABEL[entry.team],
          open: entry.open,
          capacity: entry.capacity,
          utilization: util,
          oldest_hours: Math.round((entry.oldest_age_mins || 0) / 60),
        };
      });
  }, [data?.by_team, filters.assigned_team]);

  const throughput = useMemo(() => {
    return (data?.over_time ?? []).filter((day) => !since || day.date >= since);
  }, [data?.over_time, since]);

  const categoryMix = useMemo(() => {
    return (data?.by_category ?? [])
      .filter((entry) => !filters.category || entry.category === filters.category)
      .slice()
      .sort((a, b) => b.count - a.count)
      .slice(0, 8);
  }, [data?.by_category, filters.category]);

  const filtersActive = !!(filters.severity || filters.assigned_team || filters.category || filters.window !== "30");

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
            What is at risk, what is waiting on you, and where load is piling up.
          </p>
        </Flex>
        <Space>
          <Tooltip title="Recompute confidence with evidence coverage, band margin, and precedent agreement (no full re-triage).">
            <Button
              icon={<ReloadOutlined spin={recalcConfidence.isPending} />}
              loading={recalcConfidence.isPending}
              onClick={() => recalcConfidence.mutate()}
            >
              Recalculate confidence
            </Button>
          </Tooltip>
          <Tooltip title="Pull new/updated Jira issues and triage them. Charts refresh every 3s while sync runs.">
            <Button
              type="primary"
              icon={<CloudSyncOutlined spin={syncNow.isPending} />}
              loading={syncNow.isPending}
              onClick={() => syncNow.mutate()}
            >
              {syncNow.isPending ? "Syncing…" : "Sync Now"}
            </Button>
          </Tooltip>
          <Button icon={<ReloadOutlined />} loading={analytics.isFetching} onClick={() => analytics.refetch()}>
            Refresh
          </Button>
        </Space>
      </Flex>

      <Card size="small" className="control-filters">
        <Flex gap={12} wrap align="center">
          <span className="label">Filters</span>
          <Select
            allowClear
            placeholder="Priority"
            style={{ width: 140 }}
            options={SEVERITY_OPTIONS}
            value={filters.severity}
            onChange={(severity) => setFilters((prev) => ({ ...prev, severity }))}
          />
          <Select
            allowClear
            placeholder="Team"
            style={{ width: 140 }}
            options={TEAM_OPTIONS}
            value={filters.assigned_team}
            onChange={(assigned_team) => setFilters((prev) => ({ ...prev, assigned_team }))}
          />
          <Select
            allowClear
            placeholder="Category"
            style={{ width: 160 }}
            options={CATEGORY_OPTIONS}
            value={filters.category}
            onChange={(category) => setFilters((prev) => ({ ...prev, category }))}
          />
          <Select
            style={{ width: 150 }}
            options={WINDOW_OPTIONS}
            value={filters.window}
            onChange={(window: WindowDays) => setFilters((prev) => ({ ...prev, window }))}
          />
          {filtersActive && (
            <Button
              type="link"
              onClick={() => setFilters({ window: "30" })}
              style={{ paddingInline: 0 }}
            >
              Reset
            </Button>
          )}
        </Flex>
      </Card>

      <div className="control-kpi-grid control-kpi-grid--slim">
        <StatTile
          compact
          label="SLA at risk"
          value={data?.sla_at_risk}
          tone={data?.sla_at_risk ? "warning" : "default"}
          hint="Under 30 minutes to the response target"
          loading={loading}
        />
        <StatTile
          compact
          label="Awaiting approval"
          value={data?.awaiting_approval}
          tone={data?.awaiting_approval ? "warning" : "default"}
          loading={loading}
        />
        <StatTile
          compact
          label="Override rate"
          value={data ? (data.override_rate * 100).toFixed(1) : null}
          suffix="%"
          tone={data && data.override_rate > 0.2 ? "warning" : "default"}
          hint="How often a human corrected the system"
          loading={loading}
        />
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12} xl={8}>
          <ChartCard
            title="Open volume by Priority"
            loading={loading}
            empty={!priorityPie.some((slice) => slice.value > 0)}
          >
            <PieChart>
              <Pie
                data={priorityPie}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                innerRadius={52}
                outerRadius={88}
                paddingAngle={2}
                {...ANIMATION}
              >
                {priorityPie.map((slice) => (
                  <Cell key={slice.name} fill={PRIORITY_COLORS[slice.name] ?? SERIES[0]} />
                ))}
              </Pie>
              <ReTooltip {...tooltipProps} />
              <Legend {...legendProps} />
            </PieChart>
          </ChartCard>
        </Col>

        <Col xs={24} lg={12} xl={8}>
          <ChartCard title="Team utilization (% of capacity)" loading={loading} empty={!teamUtilization.length}>
            <BarChart data={teamUtilization} layout="vertical" margin={{ left: 8, right: 12 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" domain={[0, "dataMax"]} unit="%" {...axisProps} />
              <YAxis type="category" dataKey="team" width={64} {...axisProps} />
              <ReTooltip
                {...tooltipProps}
                formatter={(value: number | string, _name: string, item) => {
                  const row = item?.payload as { open?: number; capacity?: number } | undefined;
                  return [`${value}% (${row?.open ?? 0}/${row?.capacity ?? 0} open)`, "Utilization"];
                }}
              />
              <Bar dataKey="utilization" name="utilization" fill={SERIES[0]} radius={[0, 4, 4, 0]} {...animationFor(0)} />
            </BarChart>
          </ChartCard>
        </Col>

        <Col xs={24} lg={12} xl={8}>
          <ChartCard title="Oldest open ticket age (hours)" loading={loading} empty={!teamUtilization.length}>
            <BarChart data={teamUtilization} layout="vertical" margin={{ left: 8, right: 12 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" allowDecimals={false} {...axisProps} />
              <YAxis type="category" dataKey="team" width={64} {...axisProps} />
              <ReTooltip {...tooltipProps} />
              <Bar dataKey="oldest_hours" name="hours" fill={SERIES[2]} radius={[0, 4, 4, 0]} {...animationFor(0)} />
            </BarChart>
          </ChartCard>
        </Col>

        <Col xs={24} xl={12}>
          <ChartCard title="Triage throughput vs overrides" loading={loading} empty={!throughput.length}>
            <AreaChart data={throughput}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
              <XAxis dataKey="date" {...axisProps} />
              <YAxis allowDecimals={false} {...axisProps} />
              <ReTooltip {...tooltipProps} />
              <Legend {...legendProps} />
              <Area
                type="monotone"
                dataKey="triaged"
                name="triaged"
                stroke={SERIES[0]}
                fill={SERIES[0]}
                fillOpacity={0.18}
                strokeWidth={2}
                {...animationFor(0)}
              />
              <Area
                type="monotone"
                dataKey="overridden"
                name="overridden"
                stroke={SERIES[2]}
                fill={SERIES[2]}
                fillOpacity={0.22}
                strokeWidth={2}
                {...animationFor(1)}
              />
            </AreaChart>
          </ChartCard>
        </Col>

        <Col xs={24} xl={12}>
          <ChartCard title="Top categories in the backlog" loading={loading} empty={!categoryMix.length}>
            <BarChart data={categoryMix} layout="vertical" margin={{ left: 24 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" allowDecimals={false} {...axisProps} />
              <YAxis type="category" dataKey="category" width={110} {...axisProps} />
              <ReTooltip {...tooltipProps} />
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
          dataSource={approvalRows}
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
            {
              title: "Source",
              dataIndex: "source",
              width: 80,
              render: (value: string) => <Tag style={{ marginInlineEnd: 0 }}>{value}</Tag>,
            },
            { title: "Title", dataIndex: "title", ellipsis: true },
            {
              title: "Priority",
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
              title: "Why it stopped",
              dataIndex: "escalation_reason",
              width: 280,
              render: (_v, row) => {
                const reason =
                  row.escalation_reason?.trim() ||
                  (row.severity === "Highest"
                    ? "Priority Highest always requires approval"
                    : row.confidence < 0.5
                      ? "Confidence below the routing gate"
                      : row.needs_human
                        ? "Held for human review"
                        : "—");
                return (
                  <Typography.Text type="secondary" style={{ fontSize: 13 }} ellipsis={{ tooltip: reason }}>
                    {reason}
                  </Typography.Text>
                );
              },
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
            dataSource={(data?.recent_overrides ?? [])
              .filter((row) => !filters.severity || row.from === filters.severity || row.to === filters.severity)
              .slice(0, 10)}
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
                render: (_v, row: { from: string; to: string }) => (
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
                { value: "severity", label: "Priority" },
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
