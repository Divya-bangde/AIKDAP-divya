import { Fragment, type ReactNode } from "react";

import type { Citation } from "@/types/citation";

/** Matches the `[c1]`-style markers the synthesis prompt asks the model
 * to emit, and `**bold**` spans. Capturing, so `split` keeps both. */
const INLINE = /(\*\*[^*]+\*\*|\[[A-Za-z0-9_-]{1,16}\])/g;
const MARKER = /^\[([A-Za-z0-9_-]{1,16})\]$/;
const BOLD = /^\*\*([^*]+)\*\*$/;

/** Renders one line's inline spans: bold text, citation markers that
 * resolve to a real citation, and everything else verbatim. */
function inlineNodes(
  line: string,
  byId: Map<string, { citation: Citation; index: number }>,
  onSelect: (citation: Citation, index: number) => void,
): ReactNode[] {
  return line.split(INLINE).map((part, index) => {
    const bold = part.match(BOLD);
    if (bold) {
      return (
        <strong key={index} className="font-semibold text-foreground">
          {bold[1]}
        </strong>
      );
    }

    const marker = part.match(MARKER);
    if (marker) {
      const match = byId.get(marker[1]);
      // A marker with no matching citation is left exactly as the model
      // wrote it — never given the appearance of a real source.
      if (!match) return <Fragment key={index}>{part}</Fragment>;

      return (
        <button
          key={index}
          type="button"
          onClick={() => onSelect(match.citation, match.index)}
          aria-label={`View evidence for citation ${marker[1]}`}
          className="mx-0.5 inline-flex h-5 translate-y-[1px] items-center rounded border border-accent-foreground/20 bg-accent px-1.5 align-baseline font-mono text-[11px] font-semibold text-accent-foreground transition-colors hover:border-primary hover:bg-primary hover:text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {marker[1]}
        </button>
      );
    }

    return <Fragment key={index}>{part}</Fragment>;
  });
}

/** Renders the backend's final answer.
 *
 * The synthesis prompt asks the model for Markdown, so the stored
 * answer really does contain `##` headings, `**bold**` spans and `-`
 * bullets. Painting those control characters literally on screen was
 * the honest-but-unpolished default; this renders them as the
 * structure they already are.
 *
 * Three constraints this holds to:
 *
 * - **No content is added, removed, reordered or summarised.** Only the
 *   Markdown control characters themselves are consumed; every other
 *   character the model produced is rendered.
 * - **A citation marker only becomes interactive when its id matches a
 *   citation the backend actually returned.** A marker the validator
 *   rejected stays inert text rather than gaining the appearance of a
 *   source.
 * - **Deliberately not a general Markdown engine.** It handles the
 *   three constructs this prompt actually produces; anything else falls
 *   through as plain text rather than being silently transformed by a
 *   dependency whose behaviour we would not control. */
export function AnswerBody({
  answer,
  citations,
  onSelect,
}: {
  answer: string;
  citations: Citation[];
  onSelect: (citation: Citation, index: number) => void;
}) {
  const byId = new Map<string, { citation: Citation; index: number }>();
  citations.forEach((citation, index) => {
    if (citation.id) byId.set(citation.id, { citation, index });
  });

  const lines = answer.split("\n");

  return (
    <div className="flex flex-col gap-2 text-[15px] leading-[1.75] text-foreground">
      {lines.map((line, index) => {
        const trimmed = line.trim();
        if (trimmed === "") return null;

        const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
        if (heading) {
          return (
            <p
              key={index}
              className="mt-2 text-label uppercase text-muted-foreground first:mt-0"
            >
              {inlineNodes(heading[2], byId, onSelect)}
            </p>
          );
        }

        const bullet = trimmed.match(/^[-*•]\s+(.*)$/);
        if (bullet) {
          return (
            <div key={index} className="flex gap-2.5">
              <span aria-hidden="true" className="mt-[0.6em] h-1 w-1 shrink-0 rounded-full bg-ai" />
              <p className="min-w-0 flex-1">{inlineNodes(bullet[1], byId, onSelect)}</p>
            </div>
          );
        }

        return <p key={index}>{inlineNodes(trimmed, byId, onSelect)}</p>;
      })}
    </div>
  );
}
