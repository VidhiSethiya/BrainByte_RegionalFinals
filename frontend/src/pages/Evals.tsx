/**
 * Evaluations — the page that says whether any of this actually works.
 *
 * Two halves: RAG quality (groundedness, precision, recall) and triage quality
 * (classification accuracy, routing precision, severity error). The confusion matrix
 * is the honest one — it shows *where* the severity model is wrong, not just how often.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Empty,
  Flex,
  Progress,
  Row,
  Skeleton,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useState } from "react";

import { api, type ListParams, type Severity } from "../api/client";
import StatTile from "../components/StatTile";

const SEVERITIES: Severity[] = ["S1", "S2", "S3", "S4"];

/** One scored question from the evaluation set. */
interface EvalRow {
  id: string;
  question: string;
  answer: string;
  groundedness: number;
  context_precision: number;
  context_recall: number;
  hallucination: number;
  latency_ms: number;
  total_tokens: number;
  retrieval_mode: string;
}

type EvalMetric = "groundedness" | "context_precision" | "context_recall" | "hallucination";

const SUMMARY_PARAMS: ListParams = { page: 1, page_size: 200 };

/** The four metrics, and what each one is actually telling you. */
const METRIC_HELP: Record<string, string> = {
  groundedness: "Share of answer claims supported by retrieved context. Generation quality.",
  context_precision: "Share of retrieved chunks that were relevant. High noise lowers this.",
  context_recall: "Whether retrieval found what the answer needed. Misses lower this.",
  hallucination: "1 − groundedness. Reported separately because it is the risk number.",
};

function ConfusionMatrix({ cells }: { cells: { predicted: Severity; actual: Severity; count: number }[] }) {
  const max = Math.max(1, ...cells.map((cell) => cell.count));
  const lookup = new Map(cells.map((cell) => [`${cell.actual}|${cell.predicted}`, cell.count]));

  return (
    <Flex vertical gap={8}>
      <table className="confusion" role="table" aria-label="Severity confusion matrix">
        <thead>
          <tr>
            <th scope="col" className="label">
              actual ⁄ predicted
            </th>
            {SEVERITIES.map((severity) => (
              <th key={severity} scope="col" className="label">
                {severity}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {SEVERITIES.map((actual) => (
            <tr key={actual}>
              <th scope="row" className="label">
                {actual}
              </th>
              {SEVERITIES.map((predicted) => {
                const count = lookup.get(`${actual}|${predicted}`) ?? 0;
                const onDiagonal = actual === predicted;
                return (
                  <td
                    key={predicted}
                    className={`confusion-cell ${onDiagonal ? "is-correct" : count ? "is-error" : ""}`}
                    // Opacity, not a second hue — the number carries the value.
                    style={{ "--weight": count / max } as React.CSSProperties}
                  >
                    <span className="tabular">{count}</span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Rows are the labelled severity, columns what the system predicted. Everything off the
        diagonal is a miss; one column away is a near miss, two is a problem.
      </Typography.Text>
    </Flex>
  );
}

export default function Evals() {
  const { message: toast } = App.useApp();
  const queryClient = useQueryClient();
  const [params, setParams] = useState<ListParams>({ page: 1, page_size: 10 });

  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ["evals", params],
    queryFn: () => api.evals(params),
  });

  /**
   * The tiles and the A/B describe the whole evaluation set, so they are computed
   * from the whole set — never from whichever page the table happens to show.
   */
  const summary = useQuery({
    queryKey: ["evals", SUMMARY_PARAMS],
    queryFn: () => api.evals(SUMMARY_PARAMS),
  });

  const analytics = useQuery({
    queryKey: ["triage-analytics"],
    queryFn: () => api.triageAnalytics().then((r) => r.data),
  });

  const run = useMutation({
    mutationFn: () => api.runEvals(),
    onSuccess: ({ data }) => {
      toast.success(`Evaluated ${data.cases} cases`);
      queryClient.invalidateQueries({ queryKey: ["evals"] });
    },
    onError: (error: any) => toast.error(error.message ?? "Eval run failed"),
  });

  const rows: EvalRow[] = data?.data ?? [];
  const allRows: EvalRow[] = summary.data?.data ?? [];

  const mean = (subset: EvalRow[], key: EvalMetric) =>
    subset.length ? subset.reduce((sum, row) => sum + (row[key] ?? 0), 0) / subset.length : 0;
  const average = (key: EvalMetric) => mean(allRows, key);

  // Hybrid against pure vector, scored on the same questions.
  const hybrid = allRows.filter((row) => row.retrieval_mode === "hybrid");
  const vector = allRows.filter((row) => row.retrieval_mode !== "hybrid");
  const abRows = (["groundedness", "context_precision", "context_recall"] as EvalMetric[]).map((key) => ({
    key,
    metric: key.replace(/_/g, " "),
    hybrid: mean(hybrid, key),
    vector: mean(vector, key),
  }));

  const triage = analytics.data;

  return (
    <Flex vertical gap={24}>
      <Flex align="flex-end" justify="space-between" gap={16} wrap>
        <Flex vertical gap={4}>
          <h1 className="page-title">Evaluations</h1>
          <p className="page-subtitle">
            Retrieval and generation quality, and how close the triage decisions are to the labelled set.
          </p>
        </Flex>
        <Button type="primary" loading={run.isPending} onClick={() => run.mutate()}>
          Run evaluation set
        </Button>
      </Flex>

      <Card size="small" title="Retrieval and generation quality">
        <Row gutter={[16, 16]}>
          {(["groundedness", "context_precision", "context_recall", "hallucination"] as EvalMetric[]).map((key) => (
            <Col xs={12} md={6} key={key}>
              <Tooltip title={METRIC_HELP[key]}>
                <div>
                  <StatTile
                    label={key.replace(/_/g, " ")}
                    value={allRows.length ? (average(key) * 100).toFixed(1) : null}
                    suffix="%"
                    tone={key === "hallucination" ? "error" : "success"}
                    loading={summary.isPending}
                  />
                  <Progress
                    percent={Math.round(average(key) * 100)}
                    showInfo={false}
                    size="small"
                    strokeColor={key === "hallucination" ? "var(--error)" : "var(--success)"}
                    style={{ marginTop: 8 }}
                  />
                </div>
              </Tooltip>
            </Col>
          ))}
        </Row>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={12}>
          <Card size="small" title="Triage accuracy">
            <Row gutter={[16, 16]}>
              <Col xs={12}>
                <StatTile
                  label="Classification accuracy"
                  value={triage ? (triage.classification_accuracy * 100).toFixed(1) : null}
                  suffix="%"
                  tone="success"
                  loading={analytics.isPending}
                />
              </Col>
              <Col xs={12}>
                <StatTile
                  label="Routing precision"
                  value={triage ? (triage.routing_precision * 100).toFixed(1) : null}
                  suffix="%"
                  tone="success"
                  loading={analytics.isPending}
                />
              </Col>
              <Col xs={12}>
                <StatTile
                  label="Severity MAE"
                  value={triage ? triage.severity_mae.toFixed(2) : null}
                  loading={analytics.isPending}
                  hint="Mean absolute error in severity levels"
                />
              </Col>
              <Col xs={12}>
                <StatTile
                  label="Override rate"
                  value={triage ? (triage.override_rate * 100).toFixed(1) : null}
                  suffix="%"
                  tone={triage && triage.override_rate > 0.2 ? "warning" : "default"}
                  loading={analytics.isPending}
                  hint="Every override is a labelled correction"
                />
              </Col>
            </Row>
          </Card>
        </Col>

        <Col xs={24} xl={12}>
          <Card size="small" title="Severity confusion matrix">
            {analytics.isPending ? (
              <Skeleton active paragraph={{ rows: 4 }} />
            ) : triage?.severity_confusion?.length ? (
              <ConfusionMatrix cells={triage.severity_confusion} />
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="The analytics endpoint is not reporting a confusion matrix yet."
              />
            )}
          </Card>
        </Col>
      </Row>

      <Card size="small" title="Hybrid against pure vector, same questions">
        {summary.isPending ? (
          <Skeleton active paragraph={{ rows: 3 }} />
        ) : allRows.length ? (
          <Table
            rowKey="key"
            size="small"
            pagination={false}
            dataSource={abRows}
            scroll={{ x: true }}
            columns={[
              { title: "Metric", dataIndex: "metric" },
              {
                title: `Hybrid (${hybrid.length} questions)`,
                dataIndex: "hybrid",
                align: "right",
                render: (value: number) => <span className="tabular">{(value * 100).toFixed(1)}%</span>,
              },
              {
                title: `Vector only (${vector.length} questions)`,
                dataIndex: "vector",
                align: "right",
                render: (value: number) => <span className="tabular">{(value * 100).toFixed(1)}%</span>,
              },
              {
                title: "Delta",
                key: "delta",
                align: "right",
                render: (_v, row) => {
                  const delta = (row.hybrid - row.vector) * 100;
                  return (
                    <span
                      className="tabular"
                      style={{ color: delta >= 0 ? "var(--success)" : "var(--error)" }}
                    >
                      {delta >= 0 ? "+" : ""}
                      {delta.toFixed(1)} pts
                    </span>
                  );
                },
              },
            ]}
          />
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="No scored questions yet. Run the set to compare the two retrieval modes."
          />
        )}
      </Card>

      <Card size="small" title="Per-question results">
        {error ? (
          <Alert
            type="error"
            showIcon
            message="Could not load evaluation results"
            description={(error as Error).message}
            action={
              <Button size="small" onClick={() => refetch()}>
                Retry
              </Button>
            }
          />
        ) : (
          <Table
            rowKey="id"
            size="small"
            loading={isFetching || run.isPending}
            dataSource={rows}
            scroll={{ x: true }}
            expandable={{
              expandedRowRender: (record: EvalRow) => (
                <Typography.Paragraph style={{ marginBottom: 0 }}>{record.answer}</Typography.Paragraph>
              ),
            }}
            locale={{
              emptyText: (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="No evaluation runs yet. Run the set to score retrieval and generation."
                />
              ),
            }}
            pagination={{
              current: data?.meta.page,
              pageSize: data?.meta.page_size,
              total: data?.meta.total,
              showTotal: (total, range) => (
                <span className="tabular">
                  {range[0]}–{range[1]} of {total}
                </span>
              ),
            }}
            onChange={(pagination) =>
              setParams((p) => ({ ...p, page: pagination.current, page_size: pagination.pageSize }))
            }
            columns={[
              { title: "Question", dataIndex: "question", ellipsis: true },
              {
                title: "Grounded",
                dataIndex: "groundedness",
                align: "right",
                render: (v: number) => <span className="tabular">{(v * 100).toFixed(0)}%</span>,
              },
              {
                title: "Precision",
                dataIndex: "context_precision",
                align: "right",
                render: (v: number) => <span className="tabular">{(v * 100).toFixed(0)}%</span>,
              },
              {
                title: "Recall",
                dataIndex: "context_recall",
                align: "right",
                render: (v: number) => <span className="tabular">{(v * 100).toFixed(0)}%</span>,
              },
              {
                title: "Retrieval",
                dataIndex: "retrieval_mode",
                width: 110,
                render: (value: string) => <Tag color={value === "hybrid" ? "success" : "default"}>{value}</Tag>,
              },
              {
                title: "Latency",
                dataIndex: "latency_ms",
                align: "right",
                render: (v: number) => <span className="tabular">{v} ms</span>,
              },
              {
                title: "Tokens",
                dataIndex: "total_tokens",
                align: "right",
                render: (v: number) => <span className="tabular">{v}</span>,
              },
            ]}
          />
        )}
      </Card>
    </Flex>
  );
}
