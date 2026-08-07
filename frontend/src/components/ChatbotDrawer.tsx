import { MessageOutlined, ReloadOutlined, SendOutlined } from "@ant-design/icons";
import {
  App,
  Button,
  Drawer,
  Empty,
  Flex,
  FloatButton,
  Input,
  Skeleton,
  Space,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";

import { api, type Citation } from "../api/client";
import { GroundednessTag } from "./SeverityTag";
import VoiceButton from "./VoiceButton";

interface Turn {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  blocked?: boolean;
  groundedness?: number | null;
  /** True when the number came from the SQL tool rather than the model. */
  countedFromDatabase?: boolean;
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
          content: data.blocked ? data.blocked_reason ?? data.answer : data.answer,
          citations: data.citations,
          blocked: data.blocked,
          groundedness: data.groundedness,
          countedFromDatabase: (data as { tool_used?: string | null }).tool_used === "ticket_stats",
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
      <FloatButton
        className="chatbot-fab-blink"
        icon={<MessageOutlined />}
        type="primary"
        tooltip="Ask the knowledge base"
        onClick={() => setOpen(true)}
      />

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
        styles={{ body: { display: "flex", flexDirection: "column", gap: 12 }, wrapper: { boxShadow: "var(--shadow-float)" } }}
      >
        <div style={{ flex: 1, overflowY: "auto" }}>
          {turns.length === 0 && !pending && (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="Ask anything about the indexed runbooks and ticket history."
            />
          )}

          <Flex vertical gap={12}>
            {turns.map((turn, index) => (
              <div
                key={index}
                style={{ alignSelf: turn.role === "user" ? "flex-end" : "flex-start", maxWidth: "90%" }}
              >
                <div
                  className={`bubble fade-in ${
                    turn.role === "user"
                      ? "bubble-user"
                      : turn.blocked
                        ? "bubble-blocked"
                        : "bubble-assistant"
                  }`}
                >
                  <div className="markdown-body">
                    <Markdown>{turn.content}</Markdown>
                  </div>

                  {turn.role === "assistant" && turn.blocked && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      Blocked before generation. Nothing was sent to the model.
                    </Typography.Text>
                  )}

                  {turn.countedFromDatabase && (
                    <Tooltip title="This number is a SQL aggregate over the ticket table — the model did not produce it.">
                      <Tag color="processing" style={{ marginTop: 8 }}>
                        Counted from the database, not generated
                      </Tag>
                    </Tooltip>
                  )}

                  {!!turn.citations?.length && (
                    <Space size={4} wrap style={{ marginTop: 8 }}>
                      {turn.citations.map((citation) => (
                        <Tooltip key={citation.label} title={citation.snippet}>
                          <Tag>
                            {citation.label} · {citation.filename}
                          </Tag>
                        </Tooltip>
                      ))}
                    </Space>
                  )}

                  {turn.role === "assistant" && !turn.blocked && turn.groundedness !== undefined && (
                    <Flex style={{ marginTop: 8 }}>
                      <GroundednessTag score={turn.groundedness} />
                    </Flex>
                  )}
                </div>
              </div>
            ))}
            {pending && (
              <div className="bubble bubble-assistant" style={{ alignSelf: "flex-start", width: 240 }}>
                <Skeleton active paragraph={{ rows: 2 }} title={false} />
              </div>
            )}
            <div ref={bottom} />
          </Flex>
        </div>

        <Flex gap={8}>
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onPressEnter={send}
            placeholder="Ask a question…"
            maxLength={4000}
          />
          {/* Transcript lands in the field, editable — sending is still a deliberate act. */}
          <VoiceButton onTranscript={(text) => setDraft((current) => `${current} ${text}`.trim())} />
          <Button type="primary" icon={<SendOutlined />} loading={pending} onClick={send} aria-label="Send" />
        </Flex>
      </Drawer>
    </>
  );
}
