import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Empty, Flex, Input, Skeleton, Table, Tag, Tooltip, Typography } from "antd";
import { useState } from "react";

import { api, type ListParams } from "../api/client";

/** Semantic, not decorative: red is a refusal or a denial, green is a completed action. */
const ACTION_COLOR: Record<string, string> = {
  "chat.blocked_input": "error",
  "chat.blocked_output": "error",
  "access.denied": "error",
  "auth.failed": "warning",
  "document.deleted": "warning",
  "ticket.overridden": "warning",
  "chat.answered": "success",
  "ticket.approved": "success",
  "ticket.synced": "success",
  "document.indexed": "processing",
  "ticket.triaged": "processing",
};

export default function Audit() {
  const [params, setParams] = useState<ListParams>({ page: 1, page_size: 20 });

  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ["audit", params],
    queryFn: () => api.audit(params),
  });

  // The verification button is the demo: it proves the log has not been edited.
  const chain = useQuery({
    queryKey: ["audit-verify"],
    queryFn: () => api.verifyAudit().then((r) => r.data),
  });

  return (
    <Flex vertical gap={24}>
      <Flex vertical gap={4}>
        <h1 className="page-title">Audit Trail</h1>
        <p className="page-subtitle">
          Every decision, override, approval and refusal — in a hash chain that cannot be edited
          after the fact.
        </p>
      </Flex>

      {chain.isPending ? (
        <Skeleton.Input active block style={{ height: 64 }} />
      ) : chain.data ? (
        <Alert
          type={chain.data.valid ? "success" : "error"}
          showIcon
          message={
            chain.data.valid
              ? `Hash chain intact across ${chain.data.entries.toLocaleString()} entries`
              : `Chain broken at entry ${chain.data.broken_at} — the log has been tampered with`
          }
          description={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Each entry hashes its contents together with the previous entry's hash, so any edit
              or deletion invalidates every entry after it.
            </Typography.Text>
          }
          action={
            <Button size="small" onClick={() => chain.refetch()} loading={chain.isFetching}>
              Re-verify
            </Button>
          }
        />
      ) : null}

      <Card size="small" title="Audit trail">
        <Input.Search
          allowClear
          placeholder="Search actions"
          style={{ maxWidth: 280, marginBottom: 16 }}
          onSearch={(q) => setParams((p) => ({ ...p, q, page: 1 }))}
        />

        {error ? (
          <Alert
            type="error"
            showIcon
            message="Could not load the audit trail"
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
            loading={isFetching && !data}
            dataSource={data?.data ?? []}
            scroll={{ x: true }}
            expandable={{
              expandedRowRender: (record: any) => (
                <pre className="data" style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(record.details, null, 2)}
                </pre>
              ),
            }}
            locale={{
              emptyText: (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No audit entries match this search." />
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
              {
                title: "#",
                dataIndex: "id",
                width: 70,
                align: "right",
                render: (v: number) => <span className="tabular">{v}</span>,
              },
              {
                title: "When",
                dataIndex: "created_at",
                width: 170,
                render: (v: string) => <span className="data">{v?.slice(0, 19).replace("T", " ")}</span>,
              },
              {
                title: "Action",
                dataIndex: "action",
                width: 190,
                render: (v: string) => <Tag color={ACTION_COLOR[v] ?? "default"}>{v}</Tag>,
              },
              { title: "User", dataIndex: "user_id", width: 120, ellipsis: true },
              { title: "Resource", dataIndex: "resource", ellipsis: true },
              {
                title: "Entry hash",
                dataIndex: "entry_hash",
                width: 190,
                render: (v: string) => (
                  <Tooltip title={v}>
                    <span className="data">{v?.slice(0, 16)}…</span>
                  </Tooltip>
                ),
              },
            ]}
          />
        )}
      </Card>
    </Flex>
  );
}
