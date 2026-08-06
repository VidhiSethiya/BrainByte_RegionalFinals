import {
  AuditOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  LogoutOutlined,
  MessageOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Layout, Menu, Space, Tag, Typography, Button } from "antd";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { api, auth } from "../api/client";
import ChatbotDrawer from "../components/ChatbotDrawer";

const { Header, Sider, Content } = Layout;

const NAV = [
  { key: "/dashboard", icon: <DashboardOutlined />, label: "Dashboard" },
  { key: "/chat", icon: <MessageOutlined />, label: "Assistant" },
  { key: "/documents", icon: <FileTextOutlined />, label: "Knowledge Base" },
  { key: "/evals", icon: <ExperimentOutlined />, label: "Evaluations" },
  { key: "/audit", icon: <AuditOutlined />, label: "Audit Trail" },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();

  // Health drives the header badge — the fastest way to show a judge whether the
  // demo is on local Ollama or a hosted endpoint.
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => api.health().then((r) => r.data),
    refetchInterval: 30_000,
  });

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider breakpoint="lg" collapsedWidth="60" theme="light">
        <div style={{ padding: 16, fontWeight: 600, fontSize: 15 }}>
          {/* [PLACEHOLDER: PRODUCT_NAME] */}
          Enterprise AI
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={NAV}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>

      <Layout>
        <Header
          style={{
            background: "#fff",
            borderBottom: "1px solid #f0f0f0",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            paddingInline: 20,
          }}
        >
          <Typography.Text type="secondary">
            {/* [PLACEHOLDER: TAGLINE — one line describing what the system does] */}
            Grounded, governed answers over your enterprise corpus
          </Typography.Text>

          <Space>
            {health && (
              <>
                <Tag color={health.provider === "hosted" ? "blue" : "green"}>
                  {health.provider} · {health.chat_model}
                </Tag>
                <Tag color="purple">{health.retrieval_mode} retrieval</Tag>
                <Tag>{health.indexed_chunks} chunks</Tag>
              </>
            )}
            <Button
              icon={<LogoutOutlined />}
              size="small"
              onClick={() => {
                auth.clear();
                navigate("/login");
              }}
            >
              Sign out
            </Button>
          </Space>
        </Header>

        <Content style={{ padding: 20, background: "#f5f5f5" }}>
          <Outlet />
        </Content>

        {/* Single-session knowledge-base assistant, reachable from every page. */}
        <ChatbotDrawer />
      </Layout>
    </Layout>
  );
}
