import { useQuery } from "@tanstack/react-query";
import { Card, Col, Row, Statistic, Table, Tag } from "antd";
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

export default function Dashboard() {
  const { data: usage } = useQuery({
    queryKey: ["usage"],
    queryFn: () => api.usage().then((r) => r.data),
    refetchInterval: 10_000,
  });

  const { data: metrics = [] } = useQuery({
    queryKey: ["message-metrics"],
    queryFn: () => api.messageMetrics().then((r) => r.data),
    refetchInterval: 10_000,
  });

  const { data: traces } = useQuery({
    queryKey: ["traces"],
    queryFn: () => api.traces({ page_size: 15 }).then((r) => r.data),
    refetchInterval: 10_000,
  });

  const series = metrics.map((m: any, index: number) => ({
    turn: index + 1,
    latency: m.latency_ms,
    grounded: m.groundedness !== null ? Math.round(m.groundedness * 100) : null,
    tokens: (m.prompt_tokens ?? 0) + (m.completion_tokens ?? 0),
  }));

  return (
    <Row gutter={[12, 12]}>
      {[
        { title: "Requests", value: usage?.requests ?? 0 },
        { title: "Avg latency", value: usage?.avg_latency_ms ?? 0, suffix: "ms" },
        { title: "p95 latency", value: usage?.p95_latency_ms ?? 0, suffix: "ms" },
        { title: "Tokens used", value: usage?.total_tokens ?? 0 },
        { title: "Indexed chunks", value: usage?.chunks ?? 0 },
        { title: "Error rate", value: ((usage?.error_rate ?? 0) * 100).toFixed(1), suffix: "%" },
      ].map((stat) => (
        <Col xs={12} md={8} lg={4} key={stat.title}>
          <Card size="small">
            <Statistic title={stat.title} value={stat.value} suffix={stat.suffix} />
          </Card>
        </Col>
      ))}

      <Col span={24}>
        <Card size="small" title="Latency and groundedness per turn">
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={series}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="turn" />
              <YAxis yAxisId="left" />
              <YAxis yAxisId="right" orientation="right" domain={[0, 100]} />
              <ReTooltip />
              <Legend />
              <Line yAxisId="left" dataKey="latency" name="latency (ms)" stroke="#1668dc" dot={false} />
              <Line yAxisId="right" dataKey="grounded" name="grounded (%)" stroke="#52c41a" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </Col>

      <Col span={24}>
        <Card size="small" title="Recent traces">
          <Table
            size="small"
            rowKey="id"
            dataSource={traces?.data ?? []}
            pagination={false}
            scroll={{ x: true }}
            expandable={{
              expandedRowRender: (record: any) => (
                <>
                  {record.stages?.map((stage: any) => (
                    <Tag key={stage.name}>
                      {stage.name}: {stage.ms}ms
                    </Tag>
                  ))}
                </>
              ),
            }}
            columns={[
              { title: "Trace", dataIndex: "id" },
              { title: "Type", dataIndex: "name" },
              { title: "Latency", dataIndex: "total_ms", render: (v: number) => `${v} ms` },
              { title: "Tokens", dataIndex: "total_tokens" },
              { title: "Cost", dataIndex: "cost_usd", render: (v: number) => `$${v?.toFixed(4) ?? "0.0000"}` },
              {
                title: "Status",
                dataIndex: "error",
                render: (error: string | null) =>
                  error ? <Tag color="red">error</Tag> : <Tag color="green">ok</Tag>,
              },
            ]}
          />
        </Card>
      </Col>

      {/* [PLACEHOLDER: DOMAIN_WIDGETS — the charts the problem statement's users
          actually care about, e.g. claim volume by status, risk distribution] */}
    </Row>
  );
}
