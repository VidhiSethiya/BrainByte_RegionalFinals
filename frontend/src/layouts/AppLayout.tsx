/**
 * The shell: sider (surface-alt), header (white, glass), content (cream).
 *
 * Nav is filtered by role as a courtesy — the security boundary is the API, which
 * scopes every query by the token. An engineer who types `/control` still gets a 403
 * from the server, and that is the check that matters.
 */

import {
  ApartmentOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  HistoryOutlined,
  LogoutOutlined,
  ThunderboltOutlined,
  UnorderedListOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Avatar, Button, Dropdown, Flex, Layout, Menu, Typography } from "antd";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { api, auth, meQueryKey } from "../api/client";
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
  // Triage is manager-only: an engineer works their team queue, they don't
  // submit new tickets for triage or dispatch bulk runs.
  { key: "/triage", icon: <ThunderboltOutlined />, label: "Triage", managerOnly: true },
  { key: "/history", icon: <HistoryOutlined />, label: "History" },
  { key: "/control", icon: <ApartmentOutlined />, label: "Control Tower", managerOnly: true },
  { key: "/documents", icon: <FileTextOutlined />, label: "Knowledge Base", managerOnly: true },
  { key: "/evals", icon: <ExperimentOutlined />, label: "Evaluations", managerOnly: true },
  { key: "/dashboard", icon: <DashboardOutlined />, label: "Usage", managerOnly: true },
];

export function isManagerRole(role?: string) {
  return role === "manager" || role === "admin";
}

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();

  const { data: me } = useQuery({
    queryKey: meQueryKey(),
    queryFn: () => api.me().then((r) => r.data),
    staleTime: 5 * 60_000,
    enabled: !!auth.get(),
  });

  const manager = isManagerRole(me?.role);
  const items = NAV.filter((item) => !item.managerOnly || manager).map(({ managerOnly: _managerOnly, ...item }) => item);

  function signOut() {
    auth.clear();
    // Drop every cached user/ticket so the next session cannot inherit this role's UI.
    queryClient.clear();
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

          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                {
                  key: "profile",
                  disabled: true,
                  label: (
                    <Flex vertical gap={2} style={{ paddingBlock: 4, minWidth: 140 }}>
                      <Typography.Text strong style={{ textTransform: "none" }}>
                        {me?.username ?? "…"}
                      </Typography.Text>
                      <Typography.Text type="secondary" style={{ fontSize: 12, textTransform: "capitalize" }}>
                        {me?.role ?? "…"}
                      </Typography.Text>
                    </Flex>
                  ),
                },
                { type: "divider" },
                { key: "signout", icon: <LogoutOutlined />, label: "Sign out", onClick: signOut },
              ],
            }}
          >
            <Button
              type="text"
              aria-label="Account"
              className="header-profile-btn"
              icon={
                <Avatar size={32} style={{ background: "var(--accent-action)" }} icon={!me ? <UserOutlined /> : undefined}>
                  {me ? me.username.charAt(0).toUpperCase() : null}
                </Avatar>
              }
            />
          </Dropdown>
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
