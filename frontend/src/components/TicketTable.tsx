/**
 * The one ticket table. Queue and History both render this — the columns differ by
 * a prop, not by a second file.
 *
 * UI pagination: pages the rows already loaded in `page.data`. Callers fetch a
 * large page from the API; this table only sorts server-side and paginates client-side.
 */

import { Alert, Empty, Table, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { SorterResult } from "antd/es/table/interface";
import type { ReactNode } from "react";

import type { Paged, TicketRow } from "../api/client";
import SeverityTag, {
  ConfidenceMeter,
  RelativeTime,
  SlaCountdown,
  StatusTag,
  TeamStatusTag,
  TeamTag,
} from "./SeverityTag";
import { FETCH_ALL_PAGE_SIZE, uiPagination } from "./uiPagination";

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
      title: "Priority",
      dataIndex: "severity",
      width: 136,
      sorter: true,
      sortOrder: sortOrder("severity"),
      render: (_value, row) => <SeverityTag severity={row.severity} />,
    },
    ...(variant === "queue"
      ? ([
          {
            title: "SLA",
            dataIndex: "sla_due_at",
            width: 128,
            render: (_value, row) =>
              row.sla_due_at ? (
                <SlaCountdown dueAt={row.sla_due_at} />
              ) : (
                <Typography.Text type="secondary">—</Typography.Text>
              ),
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
      // Manager sees the real pipeline status; a team member only needs to know
      // whether it's still theirs to work, sitting with them, or done.
      render: (_value, row) => (showTeam ? <StatusTag status={row.status} /> : <TeamStatusTag status={row.status} />),
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
          // Resolution time is a manager metric (SLA/throughput reporting) — a
          // team member's own History doesn't need it.
          ...(showTeam
            ? ([
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
              ] as ColumnsType<TicketRow>)
            : []),
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

  return (
    <Table<TicketRow>
      rowKey="id"
      size="small"
      loading={loading}
      dataSource={page?.data ?? []}
      columns={columns}
      pagination={uiPagination}
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
      onChange={(_paginationConfig, _filters, sorter) => {
        const single = Array.isArray(sorter) ? sorter[0] : (sorter as SorterResult<TicketRow>);
        // Client-side paging only — sort still goes to the API.
        if (!single?.field || single.order === undefined) return;
        onChange({
          page: 1,
          page_size: FETCH_ALL_PAGE_SIZE,
          sort: (single.field as string) ?? sort,
          order: single.order === "ascend" ? "asc" : "desc",
        });
      }}
    />
  );
}
