/**
 * TicketSphere mark — inline SVG, never an image file.
 *
 * Direction 1 from the brief: a segmented sphere. Four arcs with gaps between them,
 * one per team (Ops / Azure / AWS / GCP), around a single centre node — four groups,
 * one system, tickets converging to one decision. Monochrome by construction, so it
 * survives a favicon, a projector and a greyscale print.
 *
 * Geometry is drawn on the 24px grid: r=9 arcs, 2px stroke, round caps.
 */

interface LogoProps {
  size?: number;
  variant?: "mark" | "full";
  /** Two colours maximum, both from the palette. */
  color?: string;
  accent?: string;
  className?: string;
}

export default function Logo({
  size = 28,
  variant = "mark",
  color = "var(--structural-navy)",
  accent = "var(--accent)",
  className,
}: LogoProps) {
  const standalone = variant === "mark";

  const mark = (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={2}
      strokeLinecap="round"
      role={standalone ? "img" : undefined}
      aria-hidden={standalone ? undefined : true}
      focusable="false"
      style={{ flex: "none", display: "block" }}
    >
      {standalone && <title>TicketSphere</title>}

      {/* Four arcs of one circle (r=9), 6° gaps — the four teams. */}
      <path d="M12 3a9 9 0 0 1 6.36 2.64" />
      <path d="M19.6 7.05A9 9 0 0 1 21 12a9 9 0 0 1-1.4 4.95" />
      <path d="M18.36 18.36A9 9 0 0 1 12 21a9 9 0 0 1-6.36-2.64" />
      <path d="M4.4 16.95A9 9 0 0 1 3 12a9 9 0 0 1 1.4-4.95" />

      {/* Convergence: one inbound ticket drawn to the centre decision. */}
      <path d="M12 7.5v3" stroke={accent} />
      <circle cx="12" cy="13.5" r="1.6" stroke={accent} />
    </svg>
  );

  if (standalone) return <span className={className}>{mark}</span>;

  return (
    <span
      className={className}
      style={{ display: "inline-flex", alignItems: "center", gap: 8 }}
    >
      {mark}
      <span className="brand-wordmark">TicketSphere</span>
    </span>
  );
}
