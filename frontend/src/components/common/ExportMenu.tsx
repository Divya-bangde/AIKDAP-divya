import { Download } from "lucide-react";
import { useRef } from "react";

import { downloadFile } from "@/lib/export";

/** "Export" as a native `<details>` disclosure: Markdown, JSON, or PDF
 * through the browser's print dialog. The print styles in `index.css`
 * and `print:hidden` on chrome and controls make the page print as a
 * light-theme document. Closes when focus leaves it. */
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

  /** Browsers name a saved PDF after the document title, so the title is
   * the export's file name for as long as the print dialog is open. */
  function printAsPdf() {
    const title = document.title;
    document.title = filename;
    window.addEventListener(
      "afterprint",
      () => {
        document.title = title;
      },
      { once: true },
    );
    window.print();
  }

  const itemClass =
    "w-full rounded-xl px-3 py-2 text-left text-sm hover:bg-secondary focus-visible:bg-secondary focus-visible:outline-none";

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
      <div className="absolute right-0 z-20 mt-2 flex w-48 flex-col rounded-2xl bg-card p-1.5 shadow-float">
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
        <button type="button" className={itemClass} onClick={() => choose(printAsPdf)}>
          PDF (print)
        </button>
      </div>
    </details>
  );
}
