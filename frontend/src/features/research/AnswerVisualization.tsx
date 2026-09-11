import { lazy, Suspense } from "react";

/** The chart/diagram spec the backend validated before storing it
 * (`schemas.Visualization`). Produced only when the question asked for a
 * visual, so most answers carry none. */
export interface VisualizationSpec {
  kind: "chart2d" | "chart3d" | "diagram";
  title?: string;
  data?: Record<string, unknown>[];
  layout?: Record<string, unknown>;
  mermaid?: string | null;
}

// Both renderers are multi-megabyte and most answers have no visual, so
// each is split into its own chunk and loaded only when one is needed.
const PlotlyVisualization = lazy(() => import("@/features/research/PlotlyVisualization"));
const MermaidDiagram = lazy(() => import("@/features/research/MermaidDiagram"));

export function AnswerVisualization({ spec }: { spec: VisualizationSpec }) {
  return (
    <figure className="flex flex-col gap-3 rounded-lg bg-sunken/40 p-4">
      {spec.title && (
        <figcaption className="text-sm font-medium text-foreground">{spec.title}</figcaption>
      )}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading visualization…</p>}>
        {spec.kind === "diagram" ? (
          <MermaidDiagram source={spec.mermaid ?? ""} />
        ) : (
          <PlotlyVisualization data={spec.data ?? []} layout={spec.layout ?? {}} />
        )}
      </Suspense>
    </figure>
  );
}
