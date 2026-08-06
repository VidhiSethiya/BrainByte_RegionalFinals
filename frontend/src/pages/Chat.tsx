import { DislikeOutlined, LikeOutlined, SendOutlined } from "@ant-design/icons";
import { App, Button, Card, Empty, Flex, Input, Space, Spin, Tag, Tooltip, Typography } from "antd";
import { useRef, useState } from "react";
import Markdown from "react-markdown";

import { api, type ChatResponse, type Citation } from "../api/client";

interface Turn {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  messageId?: string;
  groundedness?: number | null;
  latencyMs?: number;
  tokens?: number;
  blocked?: boolean;
}

/** Groundedness is the number judges look for — show it, don't bury it. */
function GroundednessTag({ score }: { score?: number | null }) {
  if (score === undefined || score === null) return null;
  const color = score >= 0.75 ? "green" : score >= 0.5 ? "gold" : "red";
  return (
    <Tooltip title="Share of the answer's claims supported by the retrieved sources">
      <Tag color={color}>grounded {(score * 100).toFixed(0)}%</Tag>
    </Tooltip>
  );
}

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

  function applyResponse(data: ChatResponse) {
    setSessionId(data.session_id);
    setSuggestions(data.suggestions ?? []);
    setTurns((prev) => [
      ...prev,
      {
        role: "assistant",
        content: data.answer,
        citations: data.citations,
        messageId: data.message_id,
        groundedness: data.groundedness,
        latencyMs: data.latency_ms,
        tokens: data.total_tokens,
        blocked: data.blocked,
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
    <Flex vertical gap={12} style={{ height: "calc(100vh - 104px)" }}>
      <Card styles={{ body: { flex: 1, overflowY: "auto" } }} style={{ flex: 1, overflow: "hidden" }}>
        {turns.length === 0 && (
          <Empty
            description={
              /* [PLACEHOLDER: EMPTY_STATE_COPY — name 2-3 real questions from the
                 problem statement so a judge can click straight into a good demo] */
              "Ask a question about the indexed corpus"
            }
          />
        )}

        <Flex vertical gap={16}>
          {turns.map((turn, index) => (
            <div key={index} style={{ alignSelf: turn.role === "user" ? "flex-end" : "flex-start", maxWidth: "80%" }}>
              <Card
                size="small"
                style={{
                  background: turn.role === "user" ? "#e6f4ff" : turn.blocked ? "#fff2f0" : "#fafafa",
                }}
              >
                <Markdown>{turn.content}</Markdown>

                {turn.role === "assistant" && !turn.blocked && (
                  <>
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

                    <Flex align="center" gap={8} style={{ marginTop: 8 }}>
                      <GroundednessTag score={turn.groundedness} />
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {turn.latencyMs}ms · {turn.tokens} tokens
                      </Typography.Text>
                      {turn.messageId && (
                        <Space size={0}>
                          <Button type="text" size="small" icon={<LikeOutlined />}
                                  onClick={() => rate(turn.messageId!, 1)} />
                          <Button type="text" size="small" icon={<DislikeOutlined />}
                                  onClick={() => rate(turn.messageId!, -1)} />
                        </Space>
                      )}
                    </Flex>
                  </>
                )}
              </Card>
            </div>
          ))}
          {pending && <Spin style={{ alignSelf: "flex-start" }} />}
          <div ref={bottom} />
        </Flex>
      </Card>

      {!!suggestions.length && (
        <Space wrap>
          {suggestions.map((suggestion) => (
            <Tag key={suggestion} style={{ cursor: "pointer" }} onClick={() => send(suggestion)}>
              {suggestion}
            </Tag>
          ))}
        </Space>
      )}

      <Space.Compact style={{ width: "100%" }}>
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
        <Button type="primary" icon={<SendOutlined />} loading={pending} onClick={() => send(draft)}>
          Send
        </Button>
      </Space.Compact>
    </Flex>
  );
}
