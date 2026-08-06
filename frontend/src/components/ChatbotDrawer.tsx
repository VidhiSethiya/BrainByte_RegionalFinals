import { MessageOutlined, ReloadOutlined, SendOutlined } from "@ant-design/icons";
import { App, Button, Drawer, Empty, Flex, FloatButton, Input, Space, Spin, Tag, Tooltip } from "antd";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";

import { api, type Citation } from "../api/client";

interface Turn {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  blocked?: boolean;
}

/**
 * The knowledge-base assistant, available from every page.
 *
 * Deliberately single-session: the server pins one thread per user, so this widget
 * never sends or tracks a session_id and its context carries across the whole demo.
 * The Assistant page is the multi-session surface; this is the always-there one.
 */
export default function ChatbotDrawer() {
  const { message: toast } = App.useApp();
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  // Replay the pinned thread on first open so a page reload does not lose it.
  useEffect(() => {
    if (!open || turns.length) return;
    api
      .chatbotHistory()
      .then(({ data }) =>
        setTurns(
          data.map((m: any) => ({
            role: m.role,
            content: m.content,
            citations: m.citations,
            blocked: !!m.blocked_reason,
          }))
        )
      )
      .catch(() => undefined);
  }, [open, turns.length]);

  async function send() {
    const question = draft.trim();
    if (!question || pending) return;

    setTurns((prev) => [...prev, { role: "user", content: question }]);
    setDraft("");
    setPending(true);
    try {
      const { data } = await api.chatbot(question);
      setTurns((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.answer,
          citations: data.citations,
          blocked: data.blocked,
        },
      ]);
    } catch (error: any) {
      toast.error(error.message ?? "Request failed");
    } finally {
      setPending(false);
      requestAnimationFrame(() => bottom.current?.scrollIntoView({ behavior: "smooth" }));
    }
  }

  async function reset() {
    await api.resetChatbot();
    setTurns([]);
  }

  return (
    <>
      <FloatButton icon={<MessageOutlined />} type="primary" onClick={() => setOpen(true)} />

      <Drawer
        title="Knowledge Base Assistant"
        open={open}
        onClose={() => setOpen(false)}
        width={420}
        extra={
          <Tooltip title="Clear this conversation">
            <Button size="small" icon={<ReloadOutlined />} onClick={reset} />
          </Tooltip>
        }
        styles={{ body: { display: "flex", flexDirection: "column", gap: 12 } }}
      >
        <div style={{ flex: 1, overflowY: "auto" }}>
          {turns.length === 0 && <Empty description="Ask anything about the indexed documents" />}

          <Flex vertical gap={12}>
            {turns.map((turn, index) => (
              <div
                key={index}
                style={{
                  alignSelf: turn.role === "user" ? "flex-end" : "flex-start",
                  maxWidth: "90%",
                  padding: "8px 12px",
                  borderRadius: 8,
                  background:
                    turn.role === "user" ? "#e6f4ff" : turn.blocked ? "#fff2f0" : "#fafafa",
                }}
              >
                <Markdown>{turn.content}</Markdown>
                {!!turn.citations?.length && (
                  <Space size={4} wrap style={{ marginTop: 6 }}>
                    {turn.citations.map((citation) => (
                      <Tooltip key={citation.label} title={citation.snippet}>
                        <Tag>{citation.filename}</Tag>
                      </Tooltip>
                    ))}
                  </Space>
                )}
              </div>
            ))}
            {pending && <Spin style={{ alignSelf: "flex-start" }} />}
            <div ref={bottom} />
          </Flex>
        </div>

        <Space.Compact style={{ width: "100%" }}>
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onPressEnter={send}
            placeholder="Ask a question…"
            maxLength={4000}
          />
          <Button type="primary" icon={<SendOutlined />} loading={pending} onClick={send} />
        </Space.Compact>
      </Drawer>
    </>
  );
}
