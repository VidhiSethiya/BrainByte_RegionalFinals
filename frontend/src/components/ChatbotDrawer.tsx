import { CheckCircleOutlined, MessageOutlined, ReloadOutlined, SendOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
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

import { api, meQueryKey, type Citation } from "../api/client";
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
  /** Admin-only: ticket ids this answer listed that are still ready for
   * POST /tickets/bulk-approve. Cleared once acted on. */
  actionableTicketIds?: string[];
}

/**
 * The knowledge-base assistant, available from every page.
 *
 * Deliberately single-session: the server pins one thread per user, so this widget
 * never sends or tracks a session_id. That thread is scoped to one browser
 * session, though — see the mount effect below — not carried across a page
 * reload or a fresh login, unlike the Assistant page's saved multi-session
 * threads.
 */
export default function ChatbotDrawer() {
  const { message: toast } = App.useApp();
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [approving, setApproving] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  // Admin-only, same gate as the Assistant page and enforced server-side by
  // POST /tickets/bulk-approve (@require_role("admin")).
  const { data: me } = useQuery({
    queryKey: meQueryKey(),
    queryFn: () => api.me().then((r) => r.data),
    staleTime: 5 * 60_000,
  });
  const isAdmin = me?.role === "admin";

  // AppLayout (this component's only mount point) is remounted by a hard page
  // refresh and by every fresh login, but never by client-side navigation
  // between pages — so this fires exactly once per browser session, clearing
  // whatever the backend's pinned thread (chatbot/session_manager.py::
  // pinned_session) accumulated last time. Without this, that thread — and
  // its rolling memory summary — would otherwise persist forever across
  // reloads and logins, which is no longer the intended behavior.
  useEffect(() => {
    api.resetChatbot().catch(() => undefined);
  }, []);

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
          actionableTicketIds: data.actionable_ticket_ids?.length ? data.actionable_ticket_ids : undefined,
        },
      ]);
    } catch (error: any) {
      toast.error(error.message ?? "Request failed");
    } finally {
      setPending(false);
      requestAnimationFrame(() => bottom.current?.scrollIntoView({ behavior: "smooth" }));
    }
  }

  async function bulkApprove(turnIndex: number, ticketIds: string[]) {
    setApproving(true);
    try {
      const { data, meta } = await api.bulkApprove(ticketIds);
      const approved = (meta as { approved?: number })?.approved ?? data.filter((r) => r.ok).length;
      const failed = ticketIds.length - approved;
      toast.success(
        failed
          ? `Approved and routed ${approved} of ${ticketIds.length} ticket(s) — ${failed} could not be approved.`
          : `Approved and routed ${approved} ticket(s).`
      );
      setTurns((prev) =>
        prev.map((t, i) => (i === turnIndex ? { ...t, actionableTicketIds: undefined } : t))
      );
    } catch (error: any) {
      toast.error(error.message ?? "Bulk approve failed");
    } finally {
      setApproving(false);
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

                  {isAdmin && !!turn.actionableTicketIds?.length && (
                    <Flex style={{ marginTop: 8 }}>
                      <Button
                        type="primary"
                        size="small"
                        icon={<CheckCircleOutlined />}
                        loading={approving}
                        onClick={() => bulkApprove(index, turn.actionableTicketIds!)}
                      >
                        Bulk approve &amp; route ({turn.actionableTicketIds.length})
                      </Button>
                    </Flex>
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
