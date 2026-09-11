import { Download } from "lucide-react";
import { useRef } from "react";

import { downloadFile } from "@/lib/export";

/** "Export" as a native `<details>` disclosure: Markdown, JSON, or PDF
 * through the browser's print dialog (the app chrome is `print:hidden`,
 * so only the page content prints). Closes when focus leaves it. */
export function ExportMenu({
  filename,
  toMarkdown,
  toJson,
}: {
  filename: string;
  toMarkdown: () => string;
  toJson: () => unknown;
}) {
  const detailsRef = useRef<HTMLDetailsElement>(null);

  function choose(action: () => void) {
    detailsRef.current?.removeAttribute("open");
    action();
  }

  const itemClass =
    "w-full rounded-md px-3 py-2 text-left text-sm hover:bg-secondary focus-visible:bg-secondary focus-visible:outline-none";

  return (
    <details
      ref={detailsRef}
      className="relative print:hidden"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          event.currentTarget.removeAttribute("open");
        }
      }}
    >
      <summary className="press flex h-9 cursor-pointer list-none items-center gap-2 rounded-md border border-input bg-background px-3 text-sm font-medium hover:bg-secondary [&::-webkit-details-marker]:hidden">
        <Download className="h-4 w-4" />
        Export
      </summary>
      <div className="absolute right-0 z-20 mt-1 flex w-44 flex-col rounded-lg border border-border bg-card p-1 shadow-raised">
        <button
          type="button"
          className={itemClass}
          onClick={() =>
            choose(() => downloadFile(`${filename}.md`, toMarkdown(), "text/markdown"))
          }
        >
          Markdown (.md)
        </button>
        <button
          type="button"
          className={itemClass}
          onClick={() =>
            choose(() =>
              downloadFile(
                `${filename}.json`,
                JSON.stringify(toJson(), null, 2),
                "application/json",
              ),
            )
          }
        >
          JSON (.json)
        </button>
        <button type="button" className={itemClass} onClick={() => choose(() => window.print())}>
          PDF (print)
        </button>
      </div>
    </details>
  );
}
