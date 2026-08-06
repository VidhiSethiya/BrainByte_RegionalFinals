import { App, Button, Card, Form, Input, Typography } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, auth } from "../api/client";

export default function Login() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);

  async function onFinish(values: { username: string; password: string }) {
    setLoading(true);
    try {
      const { data } = await api.login(values.username, values.password);
      auth.set(data.token);
      navigate("/dashboard");
    } catch (error: any) {
      message.error(error.message ?? "Sign in failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "100vh", background: "#f5f5f5" }}>
      <Card style={{ width: 380 }}>
        {/* [PLACEHOLDER: PRODUCT_NAME] */}
        <Typography.Title level={4}>Enterprise AI Platform</Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginTop: -8 }}>
          Sign in to continue
        </Typography.Paragraph>

        <Form layout="vertical" onFinish={onFinish} initialValues={{ username: "admin" }}>
          <Form.Item
            name="username"
            label="Username"
            rules={[{ required: true, min: 3, message: "At least 3 characters" }]}
          >
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            label="Password"
            rules={[{ required: true, min: 6, message: "At least 6 characters" }]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            Sign in
          </Button>
        </Form>

        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Demo account: admin / admin123
        </Typography.Text>
      </Card>
    </div>
  );
}
