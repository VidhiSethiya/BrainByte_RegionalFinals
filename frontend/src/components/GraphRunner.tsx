/**
 * The agent pipeline, made visible.
 *
 * Ten nodes as a vertical stepper. When the backend returns a whole run at once we
 * replay it client-side at the *real* per-node latencies — the animation must never
 * claim a timing the data does not contain, so every delay here comes from `node.ms`.
 *
 * The retry edge is the point of the component. A multi-agent system that re-retrieves
 * because its own grader was not satisfied is the strongest evidence on the screen
 * that this is a pipeline and not one prompt; it gets drawn, labelled and left alone.
 *
 * `prefers-reduced-motion` snaps to the final state instead of animating.
 */

import { Flex, Skeleton, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import type { GraphNode } from "../api/client";

const NODE_COPY: Record<GraphNode["name"], string> = {
  normalize: "Strip noise, mask PII, normalise the ticket into a stable shape",
  enrich: "Retrieve precedent tickets and the runbook passages that apply",
  grade: "Score the retrieval — retry if the evidence is too thin to decide on",
  classify: "Assign a category and subcategory from the evidence",
  assess: "Set severity and priority — the highest blast-radius call in the run",
  route: "Pick the owning team from ownership rules and precedent",
  reflect: "Self-check the decision against its own citations",
  verify: "Confirm every citation resolves to an indexed chunk",
  gate: "Decide whether a human must approve before anything moves",
  sync: "Write the outcome back to Jira",
};

const TIER_COLOR = { fast: "default", standard: "processing", deep: "warning" } as const;

function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

interface GraphRunnerProps {
  nodes?: GraphNode[];
  /** Replay the run at its own per-node latencies instead of dumping it. */
  animate?: boolean;
  retries?: number;
  running?: boolean;
}

export default function GraphRunner({ nodes, animate = true, retries = 0, running = false }: GraphRunnerProps) {
  const [revealed, setRevealed] = useState(0);

  useEffect(() => {
    if (!nodes?.length) {
      setRevealed(0);
      return;
    }
    if (!animate || prefersReducedMotion()) {
      setRevealed(nodes.length);
      return;
    }

    setRevealed(0);
    let cancelled = false;
    const timers: number[] = [];
    let elapsed = 0;

    nodes.forEach((node, index) => {
      // Compressed 4× so a 6-second run reads in a demo, but still proportional to
      // the latencies the backend actually reported.
      elapsed += Math.max(120, node.ms / 4);
      timers.push(
        window.setTimeout(() => {
          if (!cancelled) setRevealed(index + 1);
        }, elapsed)
      );
    });

    return () => {
      cancelled = true;
      timers.forEach(window.clearTimeout);
    };
  }, [nodes, animate]);

  if (running && !nodes?.length) {
    return (
      <Flex vertical gap={12}>
        {Array.from({ length: 5 }).map((_, index) => (
          <Skeleton key={index} active paragraph={{ rows: 1 }} title={{ width: 140 }} />
        ))}
      </Flex>
    );
  }

  if (!nodes?.length) {
    return (
      <Flex vertical gap={8} align="center" style={{ padding: 32 }}>
        <Typography.Text type="secondary">The pipeline runs here.</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 13, textAlign: "center" }}>
          Paste a ticket on the left and press Triage — ten agents, each with its own latency,
          token count and model tier.
        </Typography.Text>
      </Flex>
    );
  }

  return (
    <Flex vertical>
      {nodes.map((node, index) => {
        const visible = index < revealed;
        const isCurrent = index === revealed && revealed < nodes.length;
        const status: GraphNode["status"] = visible ? node.status : isCurrent ? "running" : "pending";
        const dotClass =
          status === "done"
            ? "is-done"
            : status === "failed"
              ? "is-failed"
              : status === "skipped"
                ? "is-skipped"
                : status === "running"
                  ? "is-running"
                  : "";

        return (
          <div key={node.name}>
            <div className={`graph-node ${visible ? "fade-in" : ""}`}>
              <div className="graph-rail">
                <span className={`graph-dot ${dotClass}`} aria-hidden="true" />
                {index < nodes.length - 1 && <span className="graph-line" />}
              </div>

              <Flex vertical gap={4} style={{ flex: 1, opacity: status === "pending" ? 0.45 : 1 }}>
                <Flex align="center" justify="space-between" gap={8} wrap>
                  <Flex align="center" gap={8}>
                    <Typography.Text strong style={{ fontSize: 13 }}>
                      {node.name}
                    </Typography.Text>
                    {node.tier && <Tag color={TIER_COLOR[node.tier]}>{node.tier}</Tag>}
                    {status === "skipped" && <Tag>skipped</Tag>}
                    {status === "failed" && <Tag color="error">failed</Tag>}
                  </Flex>
                  {(status === "done" || status === "failed") && (
                    <Typography.Text type="secondary" className="tabular" style={{ fontSize: 12 }}>
                      {node.ms} ms · {node.tokens.toLocaleString()} tok
                    </Typography.Text>
                  )}
                </Flex>

                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {NODE_COPY[node.name]}
                </Typography.Text>

                {visible && node.output_summary && status !== "skipped" && (
                  <Typography.Text style={{ fontSize: 13 }}>{node.output_summary}</Typography.Text>
                )}
              </Flex>
            </div>

            {/* The loop-back edge, drawn only when the run actually retried. */}
            {node.name === "grade" && retries > 0 && index < revealed && (
              <div className="graph-retry fade-in" style={{ marginBlock: 4 }}>
                low retrieval confidence — re-retrieved {retries === 1 ? "once" : `${retries} times`} before
                classifying
              </div>
            )}
          </div>
        );
      })}
    </Flex>
  );
}
