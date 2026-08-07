/**
 * Two consoles, one file.
 *
 * `/login` is the team console, `/manager/login` the manager console. Same form,
 * different copy and a different default landing — duplicating the file is how the
 * two drift apart. The team picker prefills a username as a convenience; the actual
 * authority is the role in the JWT, which is what decides the redirect.
 */

import { App, Button, Card, Flex, Form, Input, Select, Typography } from "antd";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, auth, type Team } from "../api/client";
import Logo from "../components/Logo";
import { TEAM_OPTIONS } from "../components/SeverityTag";

const TAGLINE = "An enterprise AI ticket intelligence platform";

const MODES = {
  team: {
    title: "TicketSphere — Team Console",
    subtitle: "Sign in to your team queue",
    hint: "Demo account: aws1 / aws123",
    initial: { username: "aws1", password: "aws123" },
    switchTo: "/manager/login",
    switchLabel: "Sign in to the manager console",
  },
  manager: {
    title: "TicketSphere — Manager Console",
    subtitle: "Queue oversight, approvals and history",
    hint: "Demo account: manager / manager123",
    initial: { username: "manager", password: "manager123" },
    switchTo: "/login",
    switchLabel: "Sign in to a team console",
  },
} as const;

/** The role in the token decides the landing page — never the route they arrived on. */
function landingFor(role: string) {
  return role === "manager" || role === "admin" ? "/control" : "/queue";
}

export default function Login({ mode = "team" }: { mode?: "team" | "manager" }) {
  const navigate = useNavigate();
  const { message: toast } = App.useApp();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const copy = MODES[mode];

  async function onFinish(values: { username: string; password: string }) {
    setLoading(true);
    try {
      const { data } = await api.login(values.username, values.password);
      auth.set(data.token);
      toast.success(`Signed in as ${data.user.username} · ${data.user.role}`);
      navigate(landingFor(data.user.role), { replace: true });
    } catch (error: any) {
      toast.error(error.message ?? "Sign in failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Flex
      align="center"
      justify="center"
      style={{ minHeight: "100vh", background: "var(--bg-app)", padding: 24 }}
    >
      <Card style={{ width: 380, boxShadow: "var(--shadow-card)" }}>
        <Flex vertical gap={24}>
          <Flex vertical gap={8}>
            <Logo size={40} />
            <Typography.Title level={3} style={{ margin: 0 }}>
              {copy.title}
            </Typography.Title>
            <span className="label">{TAGLINE}</span>
            <Typography.Text type="secondary">{copy.subtitle}</Typography.Text>
          </Flex>

          <Form
            form={form}
            layout="vertical"
            onFinish={onFinish}
            initialValues={copy.initial}
            requiredMark={false}
          >
            {mode === "team" && (
              <Form.Item
                name="team"
                label={<span className="label">Team</span>}
                extra="Prefills the demo username. Access is granted by your token, not this picker."
              >
                <Select
                  allowClear
                  placeholder="Select your team"
                  options={TEAM_OPTIONS}
                  onChange={(team: Team) =>
                    form.setFieldsValue(
                      team ? { username: `${team}1`, password: `${team}123` } : { username: "", password: "" }
                    )
                  }
                />
              </Form.Item>
            )}

            <Form.Item
              name="username"
              label={<span className="label">Username</span>}
              rules={[{ required: true, min: 3, message: "At least 3 characters" }]}
            >
              <Input autoComplete="username" autoFocus />
            </Form.Item>

            <Form.Item
              name="password"
              label={<span className="label">Password</span>}
              rules={[{ required: true, min: 6, message: "At least 6 characters" }]}
            >
              <Input.Password autoComplete="current-password" />
            </Form.Item>

            <Button type="primary" htmlType="submit" block loading={loading}>
              Sign in
            </Button>
          </Form>

          <Flex justify="space-between" align="center" wrap gap={8}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {copy.hint}
            </Typography.Text>
            <Link to={copy.switchTo} style={{ fontSize: 12 }}>
              {copy.switchLabel}
            </Link>
          </Flex>
        </Flex>
      </Card>
    </Flex>
  );
}
