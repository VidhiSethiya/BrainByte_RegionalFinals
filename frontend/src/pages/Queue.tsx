/**
 * The engineer console — the screen that actually gets used all day.
 *
 * Everything here optimises one number: clicks from "a ticket arrived" to "a decision
 * is accepted". That number is two.
 *
 * The table is server-side and the tiles come from the analytics endpoint — no total
 * on this page is computed in the browser from the page of rows it happens to hold.
 */

import {
  ExclamationCircleOutlined,
  FileTextOutlined,
  HourglassOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Col, Flex, Input, Row, Select, Typography } from "antd";
import type { InputRef } from "antd";
import { useEffect, useMemo, useRef } from "react";

import { api, meQueryKey, type TicketListParams, type TicketRow } from "../api/client";
import DecisionDrawer from "../components/DecisionDrawer";
import { SEVERITY_OPTIONS, STATUS_OPTIONS } from "../components/SeverityTag";
import StatTile from "../components/StatTile";
import TicketTable from "../components/TicketTable";
import { isManagerRole } from "../layouts/AppLayout";
import { useUiStore } from "../store/ui";

function toParams(filters: ReturnType<typeof useUiStore.getState>["queueFilters"]): TicketListParams {
  const { q, page, page_size, sort, order, ...rest } = filters;
  return {
    page,
    page_size,
    sort,
    order,
    q,
    filter: Object.fromEntries(Object.entries(rest).filter(([, value]) => value !== undefined)) as Record<
      string,
      string
    >,
  };
}

export default function Queue() {
  const filters = useUiStore((state) => state.queueFilters);
  const setFilters = useUiStore((state) => state.setQueueFilters);
  const selectedTicketId = useUiStore((state) => state.selectedTicketId);
  const drawerOpen = useUiStore((state) => state.drawerOpen);
  const openTicket = useUiStore((state) => state.openTicket);
  const selectTicket = useUiStore((state) => state.selectTicket);
  const closeDrawer = useUiStore((state) => state.closeDrawer);
  const searchRef = useRef<InputRef>(null);

  const { data: me } = useQuery({
    queryKey: meQueryKey(),
    queryFn: () => api.me().then((r) => r.data),
    staleTime: 5 * 60_000,
  });
  const manager = isManagerRole(me?.role);

  const params = useMemo(() => toParams(filters), [filters]);

  const queue = useQuery({
    queryKey: ["team-queue", params],
    queryFn: () => api.teamQueue(params),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  });

  const analytics = useQuery({
    queryKey: ["triage-analytics"],
    queryFn: () => api.triageAnalytics().then((r) => r.data),
    refetchInterval: 10_000,
    // Engineers get 403 on /analytics/triage — use queue meta instead.
    enabled: manager,
  });

  const rows: TicketRow[] = queue.data?.data ?? [];
  const queueTotal = queue.data?.meta?.total ?? rows.length;
  const s1FromQueue = rows.filter((row) => row.severity === "Highest").length;
  const awaitingFromQueue = rows.filter(
    (row) => row.needs_human || row.status === "awaiting_approval"
  ).length;

  // j/k/Enter/a/o//: the whole queue is workable without a mouse.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing = target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);

      if (event.key === "/" && !typing) {
        event.preventDefault();
        searchRef.current?.focus();
        return;
      }
      if (typing || event.metaKey || event.ctrlKey || event.altKey) return;

      const index = rows.findIndex((row) => row.id === selectedTicketId);

      if (event.key === "j" || event.key === "k") {
        event.preventDefault();
        if (!rows.length) return;
        const next =
          event.key === "j"
            ? Math.min(rows.length - 1, index + 1)
            : Math.max(0, (index === -1 ? 0 : index) - 1);
        selectTicket(rows[next].id);
        return;
      }
      if (event.key === "Enter" && selectedTicketId && !drawerOpen) {
        event.preventDefault();
        openTicket(selectedTicketId);
        return;
      }
      if ((event.key === "a" || event.key === "o") && selectedTicketId && !drawerOpen) {
        event.preventDefault();
        openTicket(selectedTicketId);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [rows, selectedTicketId, drawerOpen, openTicket, selectTicket]);

  const open = analytics.data;
  const s1Open = manager
    ? open?.by_severity.find((entry) => entry.severity === "Highest")?.count
    : s1FromQueue;
  const totalOpen = manager
    ? open?.by_severity.reduce((sum, entry) => sum + entry.count, 0)
    : queueTotal;
  const slaAtRisk = manager ? open?.sla_at_risk : null;
  const awaitingReview = manager ? open?.awaiting_approval : awaitingFromQueue;
  const tilesLoading = manager ? analytics.isPending : queue.isPending;

  return (
    <Flex vertical gap={24}>
      <Flex align="flex-end" justify="space-between" gap={16} wrap>
        <Flex vertical gap={4}>
          <h1 className="page-title">My Queue</h1>
          <p className="page-subtitle">
            {manager
              ? "Every team's open work, highest priority first."
              : "Your team's open work, highest priority first."}
          </p>
        </Flex>

        <Button icon={<ReloadOutlined />} loading={queue.isFetching} onClick={() => queue.refetch()}>
          Refresh
        </Button>
      </Flex>

      <Row gutter={[16, 16]}>
        <Col xs={12} lg={6}>
          <StatTile
            label="Open"
            value={totalOpen}
            icon={<FileTextOutlined />}
            caption="Active tickets"
            loading={tilesLoading}
            hint={manager ? "Tickets not yet resolved" : "Open tickets in your team queue (this page)"}
          />
        </Col>
        <Col xs={12} lg={6}>
          <StatTile
            label="Highest open"
            value={s1Open}
            icon={<ExclamationCircleOutlined />}
            caption="Critical priority"
            tone={s1Open ? "error" : "default"}
            loading={tilesLoading}
            hint="Critical incidents currently open"
          />
        </Col>
        <Col xs={12} lg={6}>
          <StatTile
            label="SLA at risk"
            value={slaAtRisk}
            icon={<SafetyCertificateOutlined />}
            caption={manager ? "Needs attention" : "Manager view only"}
            tone={slaAtRisk ? "warning" : "default"}
            loading={tilesLoading}
            hint={
              manager
                ? "70% or more of the way through the Priority's SLA resolve window"
                : "SLA aggregates require manager analytics access"
            }
          />
        </Col>
        <Col xs={12} lg={6}>
          <StatTile
            label="Awaiting review"
            value={awaitingReview}
            icon={<HourglassOutlined />}
            caption="Pending review"
            tone={awaitingReview ? "warning" : "default"}
            loading={tilesLoading}
            hint="Decisions the system stopped and handed to a human"
          />
        </Col>
      </Row>

      <Card size="small">
        <Flex gap={8} wrap style={{ marginBottom: 16 }}>
          <Input.Search
            ref={searchRef}
            allowClear
            placeholder="Search ticket id or title  ( / )"
            style={{ maxWidth: 320 }}
            defaultValue={filters.q}
            onSearch={(q) => setFilters({ q: q || undefined })}
          />
          <Select
            allowClear
            placeholder="Priority"
            style={{ width: 160 }}
            value={filters.severity}
            options={SEVERITY_OPTIONS}
            onChange={(severity) => setFilters({ severity })}
          />
          <Select
            allowClear
            placeholder="Status"
            style={{ width: 160 }}
            value={filters.status}
            options={STATUS_OPTIONS}
            onChange={(status) => setFilters({ status })}
          />
          <Select
            allowClear
            placeholder="Needs review"
            style={{ width: 150 }}
            value={filters.needs_human}
            options={[
              { value: "true", label: "Needs review" },
              { value: "false", label: "Auto-routed" },
            ]}
            onChange={(needs_human) => setFilters({ needs_human })}
          />
        </Flex>

        <TicketTable
          page={queue.data}
          loading={queue.isFetching && !queue.data}
          error={queue.error as Error | null}
          onRetry={() => queue.refetch()}
          showTeam={manager}
          variant="queue"
          sort={filters.sort}
          order={filters.order}
          selectedId={selectedTicketId}
          onChange={(change) => setFilters({ ...change, page: change.page })}
          onRowClick={(ticket) => openTicket(ticket.id)}
          emptyDescription={
            <Flex vertical gap={8} align="center">
              <Typography.Text>No tickets in your queue.</Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                Triage one from the Triage tab, or clear the filters above.
              </Typography.Text>
            </Flex>
          }
        />
      </Card>

      <DecisionDrawer
        ticketId={selectedTicketId}
        open={drawerOpen}
        onClose={closeDrawer}
        canApprove={manager}
      />
    </Flex>
  );
}
