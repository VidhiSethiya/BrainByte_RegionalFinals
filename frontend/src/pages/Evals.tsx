import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Card, Col, Progress, Row, Statistic, Table, Tooltip } from "antd";
import { useState } from "react";

import { api, type ListParams } from "../api/client";

/** The four metrics, and what each one is actually telling you. */
const METRIC_HELP: Record<string, string> = {
  groundedness: "Share of answer claims supported by retrieved context. Generation quality.",
  context_precision: "Share of retrieved chunks that were relevant. High noise lowers this.",
  context_recall: "Whether retrieval found what the answer needed. Misses lower this.",
  hallucination: "1 − groundedness. Reported separately because it is the risk number.",
};

export default function Evals() {
  const { message: toast } = App.useApp();
  const queryClient = useQueryClient();
  const [params, setParams] = useState<ListParams>({ page: 1, page_size: 10 });

  const { data, isFetching } = useQuery({
    queryKey: ["evals", params],
    queryFn: () => api.evals(params),
  });

  const run = useMutation({
    mutationFn: () => api.runEvals(),
    onSuccess: ({ data }) => {
      toast.success(`Evaluated ${data.cases} cases`);
      queryClient.invalidateQueries({ queryKey: ["evals"] });
    },
    onError: (error: any) => toast.error(error.message ?? "Eval run failed"),
  });

  const rows = data?.data ?? [];
  const average = (key: string) =>
    rows.length ? rows.reduce((sum: number, r: any) => sum + (r[key] ?? 0), 0) / rows.length : 0;

  return (
    <Row gutter={[12, 12]}>
      <Col span={24}>
        <Card
          size="small"
          title="Retrieval and generation quality"
          extra={
            <Button type="primary" loading={run.isPending} onClick={() => run.mutate()}>
              Run evaluation set
            </Button>
          }
        >
          <Row gutter={12}>
            {["groundedness", "context_precision", "context_recall", "hallucination"].map((key) => (
              <Col xs={12} md={6} key={key}>
                <Tooltip title={METRIC_HELP[key]}>
                  <Card size="small">
                    <Statistic title={key.replace(/_/g, " ")} value={(average(key) * 100).toFixed(1)} suffix="%" />
                    <Progress
                      percent={Math.round(average(key) * 100)}
                      showInfo={false}
                      size="small"
                      status={key === "hallucination" ? "exception" : "normal"}
                    />
                  </Card>
                </Tooltip>
              </Col>
            ))}
          </Row>
        </Card>
      </Col>

      <Col span={24}>
        <Card size="small" title="Per-question results">
          <Table
            rowKey="id"
            size="small"
            loading={isFetching || run.isPending}
            dataSource={rows}
            scroll={{ x: true }}
            expandable={{ expandedRowRender: (record: any) => <div>{record.answer}</div> }}
            pagination={{
              current: data?.meta.page,
              pageSize: data?.meta.page_size,
              total: data?.meta.total,
            }}
            onChange={(pagination) =>
              setParams((p) => ({ ...p, page: pagination.current, page_size: pagination.pageSize }))
            }
            columns={[
              { title: "Question", dataIndex: "question", ellipsis: true },
              { title: "Grounded", dataIndex: "groundedness", render: (v: number) => `${(v * 100).toFixed(0)}%` },
              { title: "Precision", dataIndex: "context_precision", render: (v: number) => `${(v * 100).toFixed(0)}%` },
              { title: "Recall", dataIndex: "context_recall", render: (v: number) => `${(v * 100).toFixed(0)}%` },
              { title: "Latency", dataIndex: "latency_ms", render: (v: number) => `${v} ms` },
              { title: "Tokens", dataIndex: "total_tokens" },
            ]}
          />
        </Card>
      </Col>
    </Row>
  );
}
