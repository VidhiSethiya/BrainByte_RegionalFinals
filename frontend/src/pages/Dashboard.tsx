import { ReloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Empty, Flex, Row, Table, Tag } from "antd";

import { api } from "../api/client";
import StatTile from "../components/StatTile";
import { uiPagination } from "../components/uiPagination";

export default function Dashboard() {
  const usage = useQuery({
    queryKey: ["usage"],
    queryFn: () => api.usage().then((r) => r.data),
    refetchInterval: 10_000,
  });

  const traces = useQuery({
    queryKey: ["traces"],
    queryFn: () => api.traces({ page_size: 15 }),
    refetchInterval: 10_000,
  });

  const tiles = [
    { label: "Requests", value: usage.data?.requests },
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
          <h1 className="page-title">Usage</h1>
          <p className="page-subtitle">Platform usage: throughput, tokens, index size and errors.</p>
        </Flex>
        <Button
          icon={<ReloadOutlined />}
          loading={usage.isFetching}
          onClick={() => {
            usage.refetch();
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
          <Col xs={12} md={12} xl={6} key={tile.label}>
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
            pagination={uiPagination}
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
