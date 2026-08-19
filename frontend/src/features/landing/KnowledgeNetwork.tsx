import { motion } from "motion/react";

import { knowledgeLink, knowledgeNode } from "@/lib/motion";

/** Three tiers: scattered sources converge through an interpretation
 * layer into a single point of intelligence. Hand-placed rather than
 * generated, so the composition is deliberate at every viewport. */
const SOURCES = [
  { x: 40, y: 34 },
  { x: 96, y: 18 },
  { x: 150, y: 40 },
  { x: 214, y: 20 },
  { x: 268, y: 38 },
  { x: 322, y: 24 },
];

const MIDDLE = [
  { x: 104, y: 104 },
  { x: 182, y: 118 },
  { x: 262, y: 104 },
];

const APEX = { x: 182, y: 190 };

/** Which source feeds which interpretation node. */
const SOURCE_LINKS: [number, number][] = [
  [0, 0],
  [1, 0],
  [2, 0],
  [2, 1],
  [3, 1],
  [3, 2],
  [4, 2],
  [5, 2],
];

/**
 * AIKDAP's visual motif: many sources → interpretation → one grounded
 * conclusion.
 *
 * **This is a brand illustration, not telemetry.** The nodes are fixed
 * coordinates in this file; they are not documents, not chunks, not
 * embeddings, and not connected to any API. Nothing here is labelled
 * or presented as live system data, and the landing page states what
 * the real numbers are elsewhere. Kept as inline SVG animated by
 * Motion so it costs one paint and no runtime library.
 */
export function KnowledgeNetwork() {
  return (
    <svg
      viewBox="0 0 364 210"
      fill="none"
      role="img"
      aria-label="Illustration: many knowledge sources converging through interpretation into a single grounded conclusion"
      className="h-auto w-full max-w-lg"
    >
      <defs>
        <linearGradient id="aikdap-link" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="hsl(210 40% 90%)" stopOpacity="0.28" />
          <stop offset="100%" stopColor="hsl(187 88% 56%)" stopOpacity="0.55" />
        </linearGradient>
        <linearGradient id="aikdap-link-core" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="hsl(187 88% 56%)" stopOpacity="0.5" />
          <stop offset="100%" stopColor="hsl(243 80% 70%)" stopOpacity="0.9" />
        </linearGradient>
      </defs>

      {SOURCE_LINKS.map(([from, to], index) => (
        <motion.path
          key={`s-${from}-${to}`}
          d={`M ${SOURCES[from].x} ${SOURCES[from].y} C ${SOURCES[from].x} ${SOURCES[from].y + 40}, ${MIDDLE[to].x} ${MIDDLE[to].y - 40}, ${MIDDLE[to].x} ${MIDDLE[to].y}`}
          stroke="url(#aikdap-link)"
          strokeWidth="1"
          variants={knowledgeLink(index)}
        />
      ))}

      {MIDDLE.map((node, index) => (
        <motion.path
          key={`m-${index}`}
          d={`M ${node.x} ${node.y} C ${node.x} ${node.y + 40}, ${APEX.x} ${APEX.y - 45}, ${APEX.x} ${APEX.y}`}
          stroke="url(#aikdap-link-core)"
          strokeWidth="1.25"
          variants={knowledgeLink(SOURCE_LINKS.length + index)}
        />
      ))}

      {SOURCES.map((node, index) => (
        <motion.rect
          key={`sn-${index}`}
          x={node.x - 3.5}
          y={node.y - 3.5}
          width="7"
          height="7"
          rx="1.5"
          fill="hsl(210 30% 88%)"
          fillOpacity="0.55"
          variants={knowledgeNode(index)}
          style={{ originX: "50%", originY: "50%", transformBox: "fill-box" }}
        />
      ))}

      {MIDDLE.map((node, index) => (
        <motion.circle
          key={`mn-${index}`}
          cx={node.x}
          cy={node.y}
          r="5"
          fill="hsl(187 88% 56%)"
          fillOpacity="0.8"
          variants={knowledgeNode(SOURCES.length + index)}
          style={{ originX: "50%", originY: "50%", transformBox: "fill-box" }}
        />
      ))}

      {/* Deliberately not a Motion element: it carries the CSS breathing
       * animation, and a variant-driven sibling would have Motion's
       * inline `opacity` fighting the keyframes for the same property. */}
      <circle
        cx={APEX.x}
        cy={APEX.y}
        r="24"
        fill="hsl(243 80% 70%)"
        fillOpacity="0.1"
        className="landing-pulse"
      />
      <motion.circle
        cx={APEX.x}
        cy={APEX.y}
        r="16"
        fill="hsl(243 80% 70%)"
        fillOpacity="0.14"
        variants={knowledgeNode(SOURCES.length + MIDDLE.length)}
        style={{ originX: "50%", originY: "50%", transformBox: "fill-box" }}
      />
      <motion.circle
        cx={APEX.x}
        cy={APEX.y}
        r="7.5"
        fill="hsl(243 80% 70%)"
        variants={knowledgeNode(SOURCES.length + MIDDLE.length + 1)}
        style={{ originX: "50%", originY: "50%", transformBox: "fill-box" }}
      />
    </svg>
  );
}
