import { InboxOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Flex,
  Input,
  Popconfirm,
  Select,
  Table,
  Tag,
  Upload,
} from "antd";
import { useState } from "react";

import { api, type DocumentRow, type ListParams } from "../api/client";

/** Semantic tokens, not raw AntD hues — restricted reads as risk, public as safe. */
const SENSITIVITY_COLOR: Record<string, string> = {
  public: "success",
  internal: "processing",
  confidential: "warning",
  restricted: "error",
};

const STATUS_COLOR: Record<string, string> = {
  indexed: "success",
  processing: "processing",
  failed: "error",
};

export default function Documents() {
  const { message: toast } = App.useApp();
  const queryClient = useQueryClient();

  // Server-side table state — the backend does the paging/sorting/filtering, so this
  // stays correct at any corpus size.
  const [params, setParams] = useState<ListParams>({ page: 1, page_size: 10, sort: "created_at", order: "desc" });
  const [sensitivity, setSensitivity] = useState("internal");
  const [roles, setRoles] = useState<string[]>(["admin", "analyst"]);

  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ["documents", params],
    queryFn: () => api.documents(params),
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadDocument(file, roles, sensitivity),
    onSuccess: ({ data }) => {
      toast.success(`Indexed ${data.chunks} chunks · ${data.pii_tokens_redacted} PII tokens masked`);
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (error: any) => toast.error(error.message ?? "Upload failed"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteDocument(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });

  return (
    <Flex vertical gap={24}>
      <Flex vertical gap={4}>
        <h1 className="page-title">Knowledge Base</h1>
        <p className="page-subtitle">
          Upload runbooks, SLA docs, and service catalogues here. Triage and the assistant
          search this library to ground every decision — nothing is answered from memory alone.
        </p>
      </Flex>

      <Card size="small" title="Add to the knowledge base">
        <Flex gap={12} wrap align="center" style={{ marginBottom: 16 }}>
          <Select
            value={sensitivity}
            onChange={setSensitivity}
            style={{ width: 160 }}
            options={["public", "internal", "confidential", "restricted"].map((v) => ({ value: v, label: v }))}
          />
          <Select
            mode="multiple"
            value={roles}
            onChange={setRoles}
            style={{ minWidth: 240 }}
            placeholder="Roles allowed to retrieve this"
            // [PLACEHOLDER: DOMAIN_ROLES]
            options={["admin", "analyst", "viewer"].map((v) => ({ value: v, label: v }))}
          />
        </Flex>

        <Upload.Dragger
          multiple
          showUploadList={false}
          accept=".txt,.md,.log,.csv,.json,.pdf,.png,.jpg,.jpeg,.webp"
          customRequest={({ file }) => upload.mutate(file as File)}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">Drop documents here</p>
          <p className="ant-upload-hint">
            Text, PDF and images. PII is masked before anything is embedded.
          </p>
        </Upload.Dragger>
      </Card>

      <Card size="small" title="Indexed documents">
        {error && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message="Could not load documents"
            description={(error as Error).message}
            action={
              <Button size="small" onClick={() => refetch()}>
                Retry
              </Button>
            }
          />
        )}

        <Flex gap={8} style={{ marginBottom: 16 }}>
          <Input.Search
            allowClear
            placeholder="Search filenames"
            style={{ maxWidth: 280 }}
            onSearch={(q) => setParams((p) => ({ ...p, q, page: 1 }))}
          />
          <Select
            allowClear
            placeholder="Modality"
            style={{ width: 140 }}
            options={["text", "pdf", "image"].map((v) => ({ value: v, label: v }))}
            onChange={(modality) => setParams((p) => ({ ...p, filter: { ...p.filter, modality }, page: 1 }))}
          />
        </Flex>

        <Table<DocumentRow>
          rowKey="id"
          size="small"
          loading={isFetching || upload.isPending}
          dataSource={data?.data ?? []}
          scroll={{ x: true }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="Nothing indexed yet. Drop a runbook above and decisions start citing it."
              />
            ),
          }}
          pagination={{
            current: data?.meta.page,
            pageSize: data?.meta.page_size,
            total: data?.meta.total,
            showSizeChanger: true,
            showTotal: (total, range) => (
              <span className="tabular">
                {range[0]}–{range[1]} of {total}
              </span>
            ),
          }}
          onChange={(pagination, _filters, sorter: any) =>
            setParams((p) => ({
              ...p,
              page: pagination.current,
              page_size: pagination.pageSize,
              sort: sorter?.field ?? p.sort,
              order: sorter?.order === "ascend" ? "asc" : "desc",
            }))
          }
          columns={[
            { title: "File", dataIndex: "filename", sorter: true },
            { title: "Type", dataIndex: "modality", render: (v: string) => <Tag>{v}</Tag> },
            {
              title: "Sensitivity",
              dataIndex: "sensitivity",
              render: (v: string) => <Tag color={SENSITIVITY_COLOR[v]}>{v}</Tag>,
            },
            {
              title: "Visible to",
              dataIndex: "allowed_roles",
              render: (roles: string[]) => roles.map((r) => <Tag key={r}>{r}</Tag>),
            },
            {
              title: "Status",
              dataIndex: "status",
              width: 120,
              render: (v: string) => <Tag color={STATUS_COLOR[v] ?? "default"}>{v}</Tag>,
            },
            {
              title: "Chunks",
              dataIndex: "chunk_count",
              align: "right",
              width: 100,
              sorter: true,
              render: (v: number) => <span className="tabular">{v}</span>,
            },
            {
              title: "Indexed",
              dataIndex: "created_at",
              width: 170,
              sorter: true,
              render: (v: string) => <span className="data">{v?.slice(0, 19).replace("T", " ")}</span>,
            },
            {
              title: "",
              render: (_: unknown, row: DocumentRow) => (
                <Popconfirm title="Remove this document and its chunks?" onConfirm={() => remove.mutate(row.id)}>
                  <Button danger size="small" type="text">
                    Delete
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Card>
    </Flex>
  );
}
