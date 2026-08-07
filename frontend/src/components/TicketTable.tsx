/**
 * The one ticket table. Queue and History both render this — the columns differ by
 * a prop, not by a second file.
 *
 * Server-side by construction: it renders exactly the page it was handed and reports
 * paging/sorting back to the caller. There is no `dataSource={allRows}` path here,
 * because the moment one exists the app quietly stops being correct at 10,000 rows.
 */

import { Alert, Empty, Table, Tooltip, Typography } from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import type { SorterResult } from "antd/es/table/interface";
import type { ReactNode } from "react";

import type { Paged, TicketRow } from "../api/client";
import SeverityTag, {
  ConfidenceMeter,
  RelativeTime,
  SlaCountdown,
  StatusTag,
  TeamTag,
} from "./SeverityTag";

export interface TableChange {
  page: number;
  page_size: number;
  sort: string;
  order: "asc" | "desc";
}

interface TicketTableProps {
  page?: Paged<TicketRow>;
  loading?: boolean;
  error?: Error | null;
  onRetry?: () => void;
  /** Team column is manager-only — an engineer's queue is one team by definition. */
  showTeam?: boolean;
  /** History adds resolution and override columns. */
  variant?: "queue" | "history";
  sort: string;
  order: "asc" | "desc";
  onChange: (change: TableChange) => void;
  onRowClick: (ticket: TicketRow) => void;
  selectedId?: string | null;
  emptyDescription?: ReactNode;
  footer?: () => ReactNode;
}

export default function TicketTable({
  page,
  loading = false,
  error,
  onRetry,
  showTeam = false,
  variant = "queue",
  sort,
  order,
  onChange,
  onRowClick,
  selectedId,
  emptyDescription,
  footer,
}: TicketTableProps) {
  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message="Could not load tickets"
        description={error.message}
        action={
          onRetry && (
            <Typography.Link onClick={onRetry} role="button">
              Retry
            </Typography.Link>
          )
        }
      />
    );
  }

  const sortOrder = (field: string): "ascend" | "descend" | null =>
    sort === field ? (order === "asc" ? "ascend" : "descend") : null;

  const columns: ColumnsType<TicketRow> = [
    {
      title: "Ticket",
      dataIndex: "external_id",
      width: 132,
      sorter: true,
      sortOrder: sortOrder("external_id"),
      render: (value: string) => <span className="data">{value}</span>,
    },
    {
      title: "Title",
      dataIndex: "title",
      ellipsis: { showTitle: false },
      render: (value: string, row) => (
        <Tooltip title={`${value} — ${row.application} · ${row.environment}`} placement="topLeft">
          <Typography.Text ellipsis>{value}</Typography.Text>
        </Tooltip>
      ),
    },
    {
      title: "Severity",
      dataIndex: "severity",
      width: 136,
      sorter: true,
      sortOrder: sortOrder("severity"),
      render: (_value, row) => <SeverityTag severity={row.severity} />,
    },
    {
      title: "Priority",
      dataIndex: "priority_score",
      width: 92,
      align: "right",
      sorter: true,
      sortOrder: sortOrder("priority_score"),
      render: (value: number) => <span className="tabular">{value}</span>,
    },
    ...(variant === "queue"
      ? ([
          {
            title: "SLA",
            dataIndex: "sla_due_at",
            width: 128,
            render: (_value, row) => <SlaCountdown dueAt={row.sla_due_at} />,
          },
        ] as ColumnsType<TicketRow>)
      : []),
    {
      title: "Age",
      dataIndex: "created_at",
      width: 80,
      align: "right",
      sorter: true,
      sortOrder: sortOrder("created_at"),
      render: (value: string) => <RelativeTime value={value} />,
    },
    ...(showTeam
      ? ([
          {
            title: "Team",
            dataIndex: "assigned_team",
            width: 108,
            render: (_value, row) => <TeamTag team={row.assigned_team} />,
          },
        ] as ColumnsType<TicketRow>)
      : []),
    {
      title: "Confidence",
      dataIndex: "confidence",
      width: 128,
      sorter: true,
      sortOrder: sortOrder("confidence"),
      render: (value: number) => <ConfidenceMeter value={value} />,
    },
    {
      title: "Status",
      dataIndex: "status",
      width: 132,
      render: (_value, row) => <StatusTag status={row.status} />,
    },
    ...(variant === "history"
      ? ([
          {
            title: "Resolved",
            dataIndex: "resolved_at",
            width: 96,
            align: "right",
            render: (value: string | null) => <RelativeTime value={value} />,
          },
          {
            title: "Resolution",
            dataIndex: "resolution_minutes",
            width: 110,
            align: "right",
            sorter: true,
            sortOrder: sortOrder("resolution_minutes"),
            render: (value: number | null) =>
              value === null ? (
                <Typography.Text type="secondary">—</Typography.Text>
              ) : (
                <span className="tabular">{value} min</span>
              ),
          },
          {
            // Quietly the most interesting column on History: where a manager sees
            // how often the system was wrong, and why.
            title: "Overridden",
            dataIndex: "overridden_by",
            width: 148,
            render: (value: string | null, row) =>
              value ? (
                <Tooltip title={row.override_reason ?? ""}>
                  <span style={{ color: "var(--warning)" }}>Yes · {value}</span>
                </Tooltip>
              ) : (
                <Typography.Text type="secondary">No</Typography.Text>
              ),
          },
        ] as ColumnsType<TicketRow>)
      : []),
  ];

  const pagination: TablePaginationConfig = {
    current: page?.meta.page ?? 1,
    pageSize: page?.meta.page_size ?? 10,
    total: page?.meta.total ?? 0,
    showSizeChanger: true,
    showTotal: (total, range) => (
      <span className="tabular">
        {range[0]}–{range[1]} of {total}
      </span>
    ),
  };

  return (
    <Table<TicketRow>
      rowKey="id"
      size="small"
      loading={loading}
      dataSource={page?.data ?? []}
      columns={columns}
      pagination={pagination}
      scroll={{ x: true }}
      sticky
      footer={footer}
      locale={{
        emptyText: (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={emptyDescription ?? "No tickets match these filters."}
          />
        ),
      }}
      rowClassName={(row) => (row.id === selectedId ? "ant-table-row-selected" : "")}
      onRow={(row) => ({
        onClick: () => onRowClick(row),
        onKeyDown: (event: React.KeyboardEvent) => {
          if (event.key === "Enter") onRowClick(row);
        },
        tabIndex: 0,
        style: { cursor: "pointer" },
        "aria-label": `${row.external_id} — ${row.title}`,
      })}
      onChange={(paginationConfig, _filters, sorter) => {
        const single = Array.isArray(sorter) ? sorter[0] : (sorter as SorterResult<TicketRow>);
        onChange({
          page: paginationConfig.current ?? 1,
          page_size: paginationConfig.pageSize ?? 10,
          sort: (single?.field as string) ?? sort,
          order: single?.order === "ascend" ? "asc" : "desc",
        });
      }}
    />
  );
}
