/**
 * Previous tickets — the same table, a different question.
 *
 * Queue asks "what do I work next". History asks "was the system right, and what did
 * we do about it when it wasn't". That is why the Overridden column exists and why
 * the drawer opens read-only with a timeline: the interesting artefact here is the
 * story, not the action.
 *
 * Filters live in Zustand so a drawer round-trip does not lose them.
 */

import { SearchOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  DatePicker,
  Drawer,
  Empty,
  Flex,
  Input,
  List,
  Select,
  Skeleton,
  Space,
  Button,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState } from "react";

import { api, type RetrievedChunk, type TicketListParams } from "../api/client";
import DecisionDrawer from "../components/DecisionDrawer";
import {
  CATEGORY_OPTIONS,
  ENVIRONMENT_OPTIONS,
  SEVERITY_OPTIONS,
  STATUS_OPTIONS,
  TEAM_OPTIONS,
} from "../components/SeverityTag";
import TicketTable from "../components/TicketTable";
import { isManagerRole } from "../layouts/AppLayout";
import { useUiStore } from "../store/ui";

function toParams(filters: ReturnType<typeof useUiStore.getState>["historyFilters"]): TicketListParams {
  const { q, page, page_size, sort, order, from, to, ...rest } = filters;
  return {
    page,
    page_size,
    sort,
    order,
    q,
    from,
    to,
    filter: Object.fromEntries(Object.entries(rest).filter(([, value]) => value !== undefined)) as Record<
      string,
      string
    >,
  };
}

export default function History() {
  const filters = useUiStore((state) => state.historyFilters);
  const setFilters = useUiStore((state) => state.setHistoryFilters);
  const resetFilters = useUiStore((state) => state.resetHistoryFilters);
  const selectedTicketId = useUiStore((state) => state.selectedTicketId);
  const drawerOpen = useUiStore((state) => state.drawerOpen);
  const openTicket = useUiStore((state) => state.openTicket);
  const selectTicket = useUiStore((state) => state.selectTicket);
  const closeDrawer = useUiStore((state) => state.closeDrawer);

  const [similarFor, setSimilarFor] = useState<{ id: string; title: string } | null>(null);

  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.me().then((r) => r.data),
    staleTime: 5 * 60_000,
  });
  const manager = isManagerRole(me?.role);

  const params = useMemo(() => toParams(filters), [filters]);

  const history = useQuery({
    queryKey: ["tickets", params],
    queryFn: () => api.tickets(params),
    placeholderData: (previous) => previous,
  });

  const similar = useQuery({
    queryKey: ["search", similarFor?.title],
    queryFn: () => api.search(similarFor!.title, { top_k: 6 }).then((r) => r.data),
    enabled: !!similarFor,
  });

  const range: [Dayjs, Dayjs] | undefined =
    filters.from && filters.to ? [dayjs(filters.from), dayjs(filters.to)] : undefined;

  return (
    <Flex vertical gap={24}>
      <Flex align="flex-end" justify="space-between" gap={16} wrap>
        <Flex vertical gap={4}>
          <h1 className="page-title">History</h1>
          <p className="page-subtitle">
            Closed and synced tickets, with the decision, the override and the outcome on each one.
          </p>
        </Flex>
        <Space>
          <Button onClick={resetFilters}>Clear filters</Button>
          {selectedTicketId && (
            <Button
              icon={<SearchOutlined />}
              onClick={() => {
                const row = history.data?.data.find((ticket) => ticket.id === selectedTicketId);
                if (row) setSimilarFor({ id: row.id, title: row.title });
              }}
            >
              Find similar
            </Button>
          )}
        </Space>
      </Flex>

      <Card size="small">
        <Flex gap={8} wrap style={{ marginBottom: 16 }}>
          <Input.Search
            allowClear
            placeholder="Search ticket id or title"
            style={{ maxWidth: 280 }}
            defaultValue={filters.q}
            onSearch={(q) => setFilters({ q: q || undefined })}
          />
          <Select
            style={{ width: 150 }}
            value={filters.state ?? "all"}
            options={[
              { value: "closed", label: "Closed" },
              { value: "open", label: "Still open" },
              { value: "all", label: "All states" },
            ]}
            onChange={(state) => setFilters({ state })}
          />
          <Select
            allowClear
            placeholder="Severity"
            style={{ width: 150 }}
            value={filters.severity}
            options={SEVERITY_OPTIONS}
            onChange={(severity) => setFilters({ severity })}
          />
          {/* Team filter is manager-only: the API scopes an engineer to their own
              team, and offering the control would imply otherwise. */}
          {manager && (
            <Select
              allowClear
              placeholder="Team"
              style={{ width: 130 }}
              value={filters.assigned_team}
              options={TEAM_OPTIONS}
              onChange={(assigned_team) => setFilters({ assigned_team })}
            />
          )}
          <Select
            allowClear
            placeholder="Status"
            style={{ width: 150 }}
            value={filters.status}
            options={STATUS_OPTIONS}
            onChange={(status) => setFilters({ status })}
          />
          <Select
            allowClear
            showSearch
            placeholder="Category"
            style={{ width: 170 }}
            value={filters.category}
            options={CATEGORY_OPTIONS}
            onChange={(category) => setFilters({ category })}
          />
          <Select
            allowClear
            placeholder="Environment"
            style={{ width: 150 }}
            value={filters.environment}
            options={ENVIRONMENT_OPTIONS}
            onChange={(environment) => setFilters({ environment })}
          />
          <DatePicker.RangePicker
            value={range}
            onChange={(dates) =>
              setFilters({
                from: dates?.[0]?.startOf("day").toISOString(),
                to: dates?.[1]?.endOf("day").toISOString(),
              })
            }
          />
        </Flex>

        <TicketTable
          page={history.data}
          loading={history.isFetching && !history.data}
          error={history.error as Error | null}
          onRetry={() => history.refetch()}
          showTeam={manager}
          variant="history"
          sort={filters.sort}
          order={filters.order}
          selectedId={selectedTicketId}
          onChange={(change) => setFilters(change)}
          onRowClick={(ticket) => {
            selectTicket(ticket.id);
            openTicket(ticket.id);
          }}
          emptyDescription={
            <Flex vertical gap={8} align="center">
              <Typography.Text>No tickets in this window.</Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                Widen the date range, or clear the filters above.
              </Typography.Text>
            </Flex>
          }
        />
      </Card>

      <DecisionDrawer
        ticketId={selectedTicketId}
        open={drawerOpen}
        onClose={closeDrawer}
        readOnly
        showTimeline
      />

      <Drawer
        open={!!similarFor}
        onClose={() => setSimilarFor(null)}
        width={480}
        title="Similar tickets and runbook passages"
        styles={{ wrapper: { boxShadow: "var(--shadow-float)" } }}
      >
        {similar.isPending && <Skeleton active paragraph={{ rows: 6 }} />}
        {similar.error && (
          <Alert
            type="error"
            showIcon
            message="Search failed"
            description={(similar.error as Error).message}
            action={
              <Button size="small" onClick={() => similar.refetch()}>
                Retry
              </Button>
            }
          />
        )}
        {similar.data && (
          <List
            dataSource={similar.data}
            locale={{
              emptyText: (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Nothing close enough to show." />
              ),
            }}
            renderItem={(chunk: RetrievedChunk) => (
              <List.Item>
                <Flex vertical gap={4} style={{ width: "100%" }}>
                  <Flex justify="space-between" gap={8}>
                    <Typography.Text strong style={{ fontSize: 13 }}>
                      {chunk.filename}
                      {chunk.page !== null ? ` · p.${chunk.page}` : ""}
                    </Typography.Text>
                    <span className="tabular" style={{ fontSize: 13, color: "var(--text-secondary)" }}>
                      {(chunk.score * 100).toFixed(0)}%
                    </span>
                  </Flex>
                  <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                    {chunk.text}
                  </Typography.Text>
                </Flex>
              </List.Item>
            )}
          />
        )}
      </Drawer>
    </Flex>
  );
}
