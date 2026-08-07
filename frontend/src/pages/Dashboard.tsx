import { ReloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Empty, Flex, Row, Skeleton, Table, Tag } from "antd";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api/client";
import {
  CHART_HEIGHT,
  GRID,
  SERIES,
  animationFor,
  axisProps,
  legendProps,
  tooltipProps,
} from "../components/chartTheme";
import StatTile from "../components/StatTile";

export default function Dashboard() {
  const usage = useQuery({
    queryKey: ["usage"],
    queryFn: () => api.usage().then((r) => r.data),
    refetchInterval: 10_000,
  });

  const metrics = useQuery({
    queryKey: ["message-metrics"],
    queryFn: () => api.messageMetrics().then((r) => r.data),
    refetchInterval: 10_000,
  });

  const traces = useQuery({
    queryKey: ["traces"],
    queryFn: () => api.traces({ page_size: 15 }),
    refetchInterval: 10_000,
  });

  const series = (metrics.data ?? []).map((m: any, index: number) => ({
    turn: index + 1,
    latency: m.latency_ms,
    grounded: m.groundedness !== null ? Math.round(m.groundedness * 100) : null,
    tokens: (m.prompt_tokens ?? 0) + (m.completion_tokens ?? 0),
  }));

  const tiles = [
    { label: "Requests", value: usage.data?.requests },
    { label: "Avg latency", value: usage.data?.avg_latency_ms, suffix: "ms" },
    { label: "p95 latency", value: usage.data?.p95_latency_ms, suffix: "ms" },
    { label: "Tokens used", value: usage.data?.total_tokens?.toLocaleString?.() },
    { label: "Indexed chunks", value: usage.data?.chunks?.toLocaleString?.() },
    {
      label: "Error rate",
      value: usage.data ? ((usage.data.error_rate ?? 0) * 100).toFixed(1) : undefined,
      suffix: "%",
      tone: usage.data && usage.data.error_rate > 0.05 ? ("error" as const) : ("default" as const),
    },
  ];

  return (
    <Flex vertical gap={24}>
      <Flex align="flex-end" justify="space-between" gap={16} wrap>
        <Flex vertical gap={4}>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Platform health: throughput, latency, groundedness and cost.</p>
        </Flex>
        <Button
          icon={<ReloadOutlined />}
          loading={usage.isFetching}
          onClick={() => {
            usage.refetch();
            metrics.refetch();
            traces.refetch();
          }}
        >
          Refresh
        </Button>
      </Flex>

      {usage.error && (
        <Alert
          type="error"
          showIcon
          message="Usage metrics unavailable"
          description={(usage.error as Error).message}
          action={
            <Button size="small" onClick={() => usage.refetch()}>
              Retry
            </Button>
          }
        />
      )}

      <Row gutter={[16, 16]}>
        {tiles.map((tile) => (
          <Col xs={12} md={8} xl={4} key={tile.label}>
            <StatTile
              label={tile.label}
              value={tile.value ?? null}
              suffix={tile.suffix}
              tone={tile.tone}
              loading={usage.isPending}
            />
          </Col>
        ))}
      </Row>

      <Card size="small" title="Latency and groundedness per turn" className="chart-card">
        {metrics.isPending ? (
          <Skeleton active paragraph={{ rows: 5 }} />
        ) : series.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="No answered turns yet. Ask something on the Assistant page."
          />
        ) : (
          <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
            <LineChart data={series}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
              <XAxis dataKey="turn" {...axisProps} />
              <YAxis yAxisId="left" {...axisProps} />
              <YAxis yAxisId="right" orientation="right" domain={[0, 100]} {...axisProps} />
              <ReTooltip {...tooltipProps} />
              <Legend {...legendProps} />
              <Line
                yAxisId="left"
                dataKey="latency"
                name="latency (ms)"
                stroke={SERIES[0]}
                dot={false}
                strokeWidth={2}
                {...animationFor(0)}
              />
              <Line
                yAxisId="right"
                dataKey="grounded"
                name="grounded (%)"
                stroke={SERIES[1]}
                dot={false}
                strokeWidth={2}
                {...animationFor(1)}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </Card>

      <Card size="small" title="Recent traces">
        {traces.error ? (
          <Alert
            type="error"
            showIcon
            message="Traces unavailable"
            description={(traces.error as Error).message}
            action={
              <Button size="small" onClick={() => traces.refetch()}>
                Retry
              </Button>
            }
          />
        ) : (
          <Table
            size="small"
            rowKey="id"
            loading={traces.isFetching && !traces.data}
            dataSource={traces.data?.data ?? []}
            pagination={false}
            scroll={{ x: true }}
            locale={{
              emptyText: (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No traces recorded yet." />
              ),
            }}
            expandable={{
              expandedRowRender: (record: any) => (
                <Flex gap={4} wrap>
                  {record.stages?.map((stage: any) => (
                    <Tag key={stage.name}>
                      {stage.name}: <span className="tabular">{stage.ms}ms</span>
                    </Tag>
                  ))}
                </Flex>
              ),
            }}
            columns={[
              { title: "Trace", dataIndex: "id", render: (v: string) => <span className="data">{v}</span> },
              { title: "Type", dataIndex: "name" },
              {
                title: "Latency",
                dataIndex: "total_ms",
                align: "right",
                render: (v: number) => <span className="tabular">{v} ms</span>,
              },
              {
                title: "Tokens",
                dataIndex: "total_tokens",
                align: "right",
                render: (v: number) => <span className="tabular">{v?.toLocaleString?.() ?? v}</span>,
              },
              {
                title: "Cost",
                dataIndex: "cost_usd",
                align: "right",
                render: (v: number) => <span className="tabular">${v?.toFixed(4) ?? "0.0000"}</span>,
              },
              {
                title: "Status",
                dataIndex: "error",
                width: 120,
                render: (error: string | null) =>
                  error ? <Tag color="error">{error}</Tag> : <Tag color="success">ok</Tag>,
              },
            ]}
          />
        )}
      </Card>
    </Flex>
  );
}
