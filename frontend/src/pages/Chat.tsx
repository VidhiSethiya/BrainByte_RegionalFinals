import { DislikeOutlined, LikeOutlined, SendOutlined } from "@ant-design/icons";
import { App, Button, Card, Empty, Flex, Input, Skeleton, Space, Tag, Tooltip, Typography } from "antd";
import { useRef, useState } from "react";
import Markdown from "react-markdown";

import { api, type ChatResponse, type Citation } from "../api/client";
import { GroundednessTag } from "../components/SeverityTag";
import VoiceButton from "../components/VoiceButton";

interface Turn {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  messageId?: string;
  groundedness?: number | null;
  latencyMs?: number;
  tokens?: number;
  blocked?: boolean;
  /** Set when the answer came from the deterministic SQL tool rather than the model. */
  countedFromDatabase?: boolean;
}

const STARTERS = [
  "How many S1 tickets were raised this week?",
  "Which team has the oldest open ticket?",
  "What is the first action for an RDS failover loop?",
];

export default function Chat() {
  const { message: toast } = App.useApp();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [sessionId, setSessionId] = useState<string>();
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  async function send(text: string) {
    const question = text.trim();
    if (!question || pending) return;

    setTurns((prev) => [...prev, { role: "user", content: question }]);
    setDraft("");
    setSuggestions([]);
    setPending(true);

    try {
      const { data } = await api.chat(question, sessionId);
      applyResponse(data);
    } catch (error: any) {
      toast.error(error.message ?? "Request failed");
      setTurns((prev) => [
        ...prev,
        { role: "assistant", content: "The request failed. Check the backend log.", blocked: true },
      ]);
    } finally {
      setPending(false);
      requestAnimationFrame(() => bottom.current?.scrollIntoView({ behavior: "smooth" }));
    }
  }

  function applyResponse(data: ChatResponse & { tool_used?: string | null }) {
    setSessionId(data.session_id);
    setSuggestions(data.suggestions ?? []);
    setTurns((prev) => [
      ...prev,
      {
        role: "assistant",
        content: data.blocked ? data.blocked_reason ?? data.answer : data.answer,
        citations: data.citations,
        messageId: data.message_id,
        groundedness: data.groundedness,
        latencyMs: data.latency_ms,
        tokens: data.total_tokens,
        blocked: data.blocked,
        countedFromDatabase: data.tool_used === "ticket_stats",
      },
    ]);
  }

  async function rate(messageId: string, rating: 1 | -1) {
    try {
      await api.feedback(messageId, rating);
      toast.success("Thanks — logged for review");
    } catch {
      toast.error("Could not record feedback");
    }
  }

  return (
    <Flex vertical gap={16} style={{ height: "calc(100vh - 104px)" }}>
      <Flex vertical gap={4}>
        <h1 className="page-title">Assistant</h1>
        <p className="page-subtitle">
          Ask the ticket history and the runbooks. Every answer carries its sources.
        </p>
      </Flex>

      <Card styles={{ body: { flex: 1, overflowY: "auto" } }} style={{ flex: 1, overflow: "hidden" }}>
        {turns.length === 0 && !pending && (
          <Flex vertical gap={16} align="center" justify="center" style={{ height: "100%" }}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="Ask a question about the ticket history or the indexed runbooks."
            />
            <Space wrap>
              {STARTERS.map((starter) => (
                <Button key={starter} size="small" onClick={() => send(starter)}>
                  {starter}
                </Button>
              ))}
            </Space>
          </Flex>
        )}

        <Flex vertical gap={16}>
          {turns.map((turn, index) => (
            <div
              key={index}
              style={{ alignSelf: turn.role === "user" ? "flex-end" : "flex-start", maxWidth: "80%" }}
            >
              <div
                className={`bubble fade-in ${
                  turn.role === "user" ? "bubble-user" : turn.blocked ? "bubble-blocked" : "bubble-assistant"
                }`}
              >
                <div className="markdown-body">
                  <Markdown>{turn.content}</Markdown>
                </div>

                {turn.role === "assistant" && turn.blocked && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    Blocked before generation. Nothing was sent to the model and nothing was written.
                  </Typography.Text>
                )}

                {turn.role === "assistant" && !turn.blocked && (
                  <>
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
                              {citation.page ? ` p.${citation.page}` : ""}
                            </Tag>
                          </Tooltip>
                        ))}
                      </Space>
                    )}

                    <Flex align="center" gap={8} style={{ marginTop: 8 }} wrap>
                      <GroundednessTag score={turn.groundedness} />
                      <Typography.Text type="secondary" className="tabular" style={{ fontSize: 12 }}>
                        {turn.latencyMs}ms · {turn.tokens} tokens
                      </Typography.Text>
                      {turn.messageId && (
                        <Space size={0}>
                          <Button
                            type="text"
                            size="small"
                            aria-label="Helpful"
                            icon={<LikeOutlined />}
                            onClick={() => rate(turn.messageId!, 1)}
                          />
                          <Button
                            type="text"
                            size="small"
                            aria-label="Not helpful"
                            icon={<DislikeOutlined />}
                            onClick={() => rate(turn.messageId!, -1)}
                          />
                        </Space>
                      )}
                    </Flex>
                  </>
                )}
              </div>
            </div>
          ))}

          {pending && (
            <div style={{ alignSelf: "flex-start", maxWidth: "80%", width: 320 }}>
              <div className="bubble bubble-assistant">
                <Skeleton active paragraph={{ rows: 2 }} title={false} />
              </div>
            </div>
          )}
          <div ref={bottom} />
        </Flex>
      </Card>

      {!!suggestions.length && (
        <Space wrap>
          {suggestions.map((suggestion) => (
            <Button key={suggestion} size="small" onClick={() => send(suggestion)}>
              {suggestion}
            </Button>
          ))}
        </Space>
      )}

      <Flex gap={8} align="flex-end">
        <Input.TextArea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              send(draft);
            }
          }}
          autoSize={{ minRows: 1, maxRows: 4 }}
          placeholder="Ask a question…  (Shift+Enter for a new line)"
          maxLength={4000}
        />
        {/* Read-only questions may run on release; the transcript still lands in the
            field first so it can be edited. */}
        <VoiceButton onTranscript={(text) => setDraft((current) => `${current} ${text}`.trim())} />
        <Button type="primary" icon={<SendOutlined />} loading={pending} onClick={() => send(draft)}>
          Send
        </Button>
      </Flex>
    </Flex>
  );
}
