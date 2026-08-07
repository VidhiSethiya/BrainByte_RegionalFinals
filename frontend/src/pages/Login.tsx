/**
 * Common login for all roles. Username + password decide identity; the role in
 * the JWT decides the redirect.
 */

import { App, Button, Card, Flex, Form, Input, Typography } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, auth, meQueryKey } from "../api/client";
import Logo from "../components/Logo";

const TAGLINE = "An enterprise AI ticket intelligence platform";

/** The role in the token decides the landing page — never the route they arrived on. */
function landingFor(role: string) {
  return role === "manager" || role === "admin" ? "/control" : "/queue";
}

export default function Login() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { message: toast } = App.useApp();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  async function onFinish(values: { username: string; password: string }) {
    setLoading(true);
    try {
      const { data } = await api.login(values.username, values.password);
      // Wipe previous session caches (nav role, tickets) before binding the new JWT.
      queryClient.clear();
      auth.set(data.token);
      queryClient.setQueryData(meQueryKey(), data.user);
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
              TicketSphere
            </Typography.Title>
            <span className="label">{TAGLINE}</span>
            <Typography.Text type="secondary">Sign in to continue</Typography.Text>
          </Flex>

          <Form form={form} layout="vertical" onFinish={onFinish} requiredMark={false}>
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
        </Flex>
      </Card>
    </Flex>
  );
}
