import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Flex, Input, Table, Tag, Typography } from "antd";
import { useState } from "react";

import { api, type ListParams } from "../api/client";

const ACTION_COLOR: Record<string, string> = {
  "chat.blocked_input": "red",
  "chat.blocked_output": "red",
  "access.denied": "red",
  "auth.failed": "orange",
  "document.deleted": "orange",
  "chat.answered": "green",
  "document.indexed": "blue",
};

export default function Audit() {
  const [params, setParams] = useState<ListParams>({ page: 1, page_size: 20 });

  const { data, isFetching } = useQuery({
    queryKey: ["audit", params],
    queryFn: () => api.audit(params),
  });

  // The verification button is the demo: it proves the log has not been edited.
  const { data: chain, refetch } = useQuery({
    queryKey: ["audit-verify"],
    queryFn: () => api.verifyAudit().then((r) => r.data),
  });

  return (
    <Flex vertical gap={12}>
      {chain && (
        <Alert
          type={chain.valid ? "success" : "error"}
          showIcon
          message={
            chain.valid
              ? `Hash chain intact across ${chain.entries} entries`
              : `Chain broken at entry ${chain.broken_at} — the log has been tampered with`
          }
          description={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Each entry hashes its contents together with the previous entry's hash, so any edit
              or deletion invalidates every entry after it.
            </Typography.Text>
          }
          action={
            <Button size="small" onClick={() => refetch()}>
              Re-verify
            </Button>
          }
        />
      )}

      <Card size="small" title="Audit trail">
        <Input.Search
          allowClear
          placeholder="Search actions"
          style={{ maxWidth: 280, marginBottom: 12 }}
          onSearch={(q) => setParams((p) => ({ ...p, q, page: 1 }))}
        />

        <Table
          rowKey="id"
          size="small"
          loading={isFetching}
          dataSource={data?.data ?? []}
          scroll={{ x: true }}
          expandable={{
            expandedRowRender: (record: any) => (
              <pre style={{ margin: 0, fontSize: 12 }}>{JSON.stringify(record.details, null, 2)}</pre>
            ),
          }}
          pagination={{
            current: data?.meta.page,
            pageSize: data?.meta.page_size,
            total: data?.meta.total,
          }}
          onChange={(pagination) =>
            setParams((p) => ({ ...p, page: pagination.current, page_size: pagination.pageSize }))
          }
          columns={[
            { title: "#", dataIndex: "id", width: 70 },
            { title: "When", dataIndex: "created_at", render: (v: string) => v?.slice(0, 19).replace("T", " ") },
            {
              title: "Action",
              dataIndex: "action",
              render: (v: string) => <Tag color={ACTION_COLOR[v] ?? "default"}>{v}</Tag>,
            },
            { title: "User", dataIndex: "user_id", ellipsis: true },
            { title: "Resource", dataIndex: "resource", ellipsis: true },
            { title: "Hash", dataIndex: "entry_hash", ellipsis: true, render: (v: string) => v?.slice(0, 16) },
          ]}
        />
      </Card>
    </Flex>
  );
}
