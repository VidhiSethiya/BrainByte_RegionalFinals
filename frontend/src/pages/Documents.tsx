import { InboxOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Card, Flex, Input, Popconfirm, Select, Table, Tag, Upload } from "antd";
import { useState } from "react";

import { api, type DocumentRow, type ListParams } from "../api/client";

const SENSITIVITY_COLOR: Record<string, string> = {
  public: "green",
  internal: "blue",
  confidential: "orange",
  restricted: "red",
};

export default function Documents() {
  const { message: toast } = App.useApp();
  const queryClient = useQueryClient();

  // Server-side table state — the backend does the paging/sorting/filtering, so this
  // stays correct at any corpus size.
  const [params, setParams] = useState<ListParams>({ page: 1, page_size: 10, sort: "created_at", order: "desc" });
  const [sensitivity, setSensitivity] = useState("internal");
  const [roles, setRoles] = useState<string[]>(["admin", "analyst"]);

  const { data, isFetching } = useQuery({
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
    <Flex vertical gap={12}>
      <Card size="small" title="Add to the knowledge base">
        <Flex gap={12} wrap align="center" style={{ marginBottom: 12 }}>
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
        <Flex gap={8} style={{ marginBottom: 12 }}>
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
          pagination={{
            current: data?.meta.page,
            pageSize: data?.meta.page_size,
            total: data?.meta.total,
            showSizeChanger: true,
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
            { title: "Chunks", dataIndex: "chunk_count", sorter: true },
            { title: "Indexed", dataIndex: "created_at", sorter: true, render: (v: string) => v?.slice(0, 19).replace("T", " ") },
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
