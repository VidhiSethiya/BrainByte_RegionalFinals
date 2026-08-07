/**
 * The shell: sider (surface-alt), header (white, glass), content (cream).
 *
 * Nav is filtered by role as a courtesy — the security boundary is the API, which
 * scopes every query by the token. An engineer who types `/control` still gets a 403
 * from the server, and that is the check that matters.
 */

import {
  ApartmentOutlined,
  AuditOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  HistoryOutlined,
  LogoutOutlined,
  MessageOutlined,
  ThunderboltOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Avatar, Button, Dropdown, Flex, Layout, Menu, Skeleton, Space, Tag, Tooltip, Typography } from "antd";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { api, auth } from "../api/client";
import ChatbotDrawer from "../components/ChatbotDrawer";
import Logo from "../components/Logo";

const { Header, Sider, Content } = Layout;

const TAGLINE = "An enterprise AI ticket intelligence platform";

interface NavItem {
  key: string;
  icon: React.ReactNode;
  label: string;
  managerOnly?: boolean;
}

const NAV: NavItem[] = [
  { key: "/queue", icon: <UnorderedListOutlined />, label: "My Queue" },
  { key: "/triage", icon: <ThunderboltOutlined />, label: "Triage" },
  { key: "/history", icon: <HistoryOutlined />, label: "History" },
  { key: "/control", icon: <ApartmentOutlined />, label: "Control Tower", managerOnly: true },
  { key: "/chat", icon: <MessageOutlined />, label: "Assistant", managerOnly: true },
  { key: "/documents", icon: <FileTextOutlined />, label: "Knowledge Base", managerOnly: true },
  { key: "/evals", icon: <ExperimentOutlined />, label: "Evaluations", managerOnly: true },
  { key: "/audit", icon: <AuditOutlined />, label: "Audit Trail", managerOnly: true },
  { key: "/dashboard", icon: <DashboardOutlined />, label: "Dashboard", managerOnly: true },
];

export function isManagerRole(role?: string) {
  return role === "manager" || role === "admin";
}

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();

  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.me().then((r) => r.data),
    staleTime: 5 * 60_000,
  });

  // Health drives the header badges — the fastest way to show whether the demo is
  // running on a hosted endpoint or a local model, and how big the index is.
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => api.health().then((r) => r.data),
    refetchInterval: 30_000,
  });

  const manager = isManagerRole(me?.role);
  const items = NAV.filter((item) => !item.managerOnly || manager).map(({ managerOnly: _managerOnly, ...item }) => item);
  const lastAnswer = health?.last_answer;

  function signOut() {
    auth.clear();
    navigate("/login", { replace: true });
  }

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider breakpoint="lg" collapsedWidth="60" theme="light" className="app-sider" width={220}>
        <div className="brand-block">
          <Logo size={28} variant="mark" />
          <span className="brand-wordmark">TicketSphere</span>
        </div>

        <Menu
          mode="inline"
          selectedKeys={[`/${location.pathname.split("/")[1]}`]}
          items={items}
          onClick={({ key }) => navigate(key)}
          style={{ borderInlineEnd: "none", paddingTop: 8 }}
        />

        {/* Who am I, and am I still connected — answered without opening a menu. */}
        <div className="sider-user">
          <Flex align="center" gap={8}>
            <Avatar size={28} style={{ background: "var(--accent-action)" }}>
              {(me?.username ?? "?").charAt(0).toUpperCase()}
            </Avatar>
            <Flex vertical style={{ minWidth: 0 }}>
              <Typography.Text ellipsis style={{ fontSize: 13, textTransform: "capitalize" }}>
                {me?.role ?? "…"}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                <span className="status-dot" aria-hidden="true" /> Online
              </Typography.Text>
            </Flex>
          </Flex>
        </div>
      </Sider>

      <Layout>
        <Header
          className="glass-header"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
            paddingInline: 24,
            position: "sticky",
            top: 0,
            zIndex: 10,
          }}
        >
          <span className="header-tagline">{TAGLINE}</span>

          <Space size={8} wrap>
            {health ? (
              <>
                <Tooltip title="Model provider and chat model currently serving decisions">
                  <Tag color="processing">
                    {health.provider} · {health.chat_model}
                  </Tag>
                </Tooltip>
                <Tooltip title="Retrieval strategy behind every citation">
                  <Tag color="processing">{health.retrieval_mode} retrieval</Tag>
                </Tooltip>
                <Tooltip title="Chunks currently indexed in the knowledge base">
                  <Tag>
                    <span className="tabular">{health.indexed_chunks?.toLocaleString?.() ?? health.indexed_chunks}</span>{" "}
                    chunks
                  </Tag>
                </Tooltip>
              </>
            ) : (
              <Skeleton.Input active size="small" style={{ width: 220 }} />
            )}

            {lastAnswer && (
              <Tooltip title="Cost and latency of the most recent model call">
                <Typography.Text type="secondary" className="tabular" style={{ fontSize: 12 }}>
                  last answer {(lastAnswer.latency_ms / 1000).toFixed(1)}s ·{" "}
                  {lastAnswer.total_tokens?.toLocaleString?.() ?? lastAnswer.total_tokens} tok · $
                  {Number(lastAnswer.cost_usd ?? 0).toFixed(4)}
                </Typography.Text>
              </Tooltip>
            )}

            <Dropdown
              menu={{
                items: [
                  { key: "who", label: `${me?.username ?? "…"} · ${me?.role ?? ""}`, disabled: true },
                  { type: "divider" },
                  { key: "signout", icon: <LogoutOutlined />, label: "Sign out", onClick: signOut },
                ],
              }}
            >
              <Button type="text" style={{ paddingInline: 8 }}>
                <Flex align="center" gap={8}>
                  <Typography.Text strong>{me?.username ?? "…"}</Typography.Text>
                  {me?.role && <Tag color={manager ? "warning" : "default"}>{me.role}</Tag>}
                </Flex>
              </Button>
            </Dropdown>
          </Space>
        </Header>

        {/* Keyed on the route so each screen fades up on entry rather than snapping. */}
        <Content style={{ padding: 24 }} className="page-enter" key={location.pathname}>
          <Outlet />
        </Content>

        {/* The assistant is a manager surface (spec §9.8) — reachable from every
            manager page, absent for engineers. */}
        {manager && <ChatbotDrawer />}
      </Layout>
    </Layout>
  );
}
