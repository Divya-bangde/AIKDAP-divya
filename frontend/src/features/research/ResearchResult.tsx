import { motion } from "motion/react";
import { SearchX, ShieldAlert, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";

import { StatusBadge } from "@/components/common/StatusBadge";
import { TechnicalDetails } from "@/components/common/TechnicalDetails";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AnswerBody } from "@/features/research/AnswerBody";
import { CitationList } from "@/features/research/CitationList";
import { EvidenceDrawer } from "@/features/research/EvidenceDrawer";
import { EvidenceFunnel } from "@/features/research/EvidenceFunnel";
import { fadeUp } from "@/lib/motion";
import { asSynthesisOutput } from "@/types/research-meta";
import { asCitation, type Citation } from "@/types/citation";
import type { components } from "@/types/api";

type ResearchRunDetail = components["schemas"]["ResearchRunDetail"];

/** Renders exactly what the backend decided — `grounding_status` is
 * never recomputed or reinterpreted here, and an
 * `insufficient_evidence` result is presented as a deliberate safety
 * outcome, not an error. No fallback answer is ever generated
 * client-side. */
export function ResearchResult({ run }: { run: ResearchRunDetail }) {
  const [selected, setSelected] = useState<{ citation: Citation; index: number } | null>(null);

  const citations = (run.citations ?? []).map(asCitation);
  const steps = run.steps ?? [];
  const synthesisStep = steps.find((step) => step.node_name === "synthesis");
  const synthesis = asSynthesisOutput(synthesisStep?.output_payload ?? null);

  const openEvidence = (citation: Citation, index: number) => setSelected({ citation, index });

  if (run.grounding_status === "insufficient_evidence") {
    return (
      <>
        <motion.div initial="hidden" animate="visible" variants={fadeUp} className="flex flex-col gap-4">
          {/* The run's query is the page `h1`; the cards below use `h3`
           * (CardTitle). This bridges the level so headings still step
           * by one for a screen reader. */}
          <h2 className="sr-only">Research outcome</h2>
          {/* Styled as a considered outcome rather than a failure: no
           * destructive colour, no error iconography. The platform
           * declining to answer is the feature. */}
          <Card className="overflow-hidden border-warning/30" role="status">
            <div className="h-1 w-full bg-gradient-to-r from-warning/60 to-warning/20" />
            <CardHeader>
              <div className="flex items-center gap-2.5">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-warning/10 text-warning">
                  <ShieldAlert className="h-4.5 w-4.5" />
                </div>
                <div>
                  <p className="text-label uppercase text-muted-foreground">Safety outcome</p>
                  <CardTitle className="mt-0.5">Insufficient Evidence</CardTitle>
                </div>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <p className="max-w-2xl text-sm leading-relaxed text-foreground">
                The available knowledge base did not contain enough relevant evidence to answer
                this question. AIKDAP does not generate an answer when it cannot ground one in
                your documents.
              </p>
              <div className="flex flex-wrap gap-6 rounded-lg border border-border bg-sunken px-4 py-3 text-sm">
                <span className="text-muted-foreground">
                  Evidence found: <span className="tabular font-medium text-foreground">{citations.length}</span>
                </span>
                <span className="text-muted-foreground">
                  Providers used:{" "}
                  <span className="font-mono font-medium text-foreground">
                    {synthesis?.provider ?? "None"}
                  </span>
                </span>
              </div>
            </CardContent>
          </Card>

          <EvidenceFunnel steps={steps} citations={citations} />
        </motion.div>

        <EvidenceDrawer
          citation={selected?.citation ?? null}
          index={selected?.index ?? null}
          onClose={() => setSelected(null)}
        />
      </>
    );
  }

  return (
    <>
      <motion.div initial="hidden" animate="visible" variants={fadeUp} className="flex flex-col gap-4">
        <h2 className="sr-only">Research result</h2>
        <Card className="overflow-hidden">
          <div className="h-1 w-full bg-gradient-to-r from-primary via-ai to-primary/30" />
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
            <div className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                <Sparkles className="h-4.5 w-4.5" />
              </div>
              <div>
                <p className="text-label uppercase text-muted-foreground">Research Result</p>
                <CardTitle className="mt-0.5">Grounded Intelligence</CardTitle>
              </div>
            </div>
            {run.grounding_status && (
              <StatusBadge domain="grounding" value={run.grounding_status} />
            )}
          </CardHeader>

          <CardContent className="flex flex-col gap-5">
            {run.final_answer ? (
              /* A single reveal of the complete answer the backend
               * already returned. Deliberately NOT word-by-word: the
               * model did not stream this response, and animating it as
               * though it did would misrepresent how it was produced. */
              <AnswerBody
                answer={run.final_answer}
                citations={citations}
                onSelect={openEvidence}
              />
            ) : (
              <p className="text-sm text-muted-foreground">No answer was generated.</p>
            )}

            {/* A real, counted statement of what backs this answer —
             * never shown for zero citations, since "supported by 0
             * evidence items" would read as reassurance for an answer
             * that has none (Sprint 9K.8, Phase 6). */}
            {citations.length > 0 && (
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5 text-success" />
                Supported by {citations.length} evidence item{citations.length === 1 ? "" : "s"}
              </p>
            )}

            {/* Provider, model and fallback detail move behind the same
             * technical disclosure the pipeline steps use (Sprint 9K.8,
             * Phase 8): this is exactly the row that used to sit here
             * unconditionally, relocated rather than removed — an
             * executive reading the answer no longer has to look past
             * "gemini-flash-latest" and "Fallback used: No" to get to
             * the point, and a technical reader is one click away from
             * the same real fields as before. */}
            {synthesis && (synthesis.provider || synthesis.model || synthesis.fallback_used !== undefined) && (
              <TechnicalDetails id={`answer-${run.id}`} className="border-t border-border pt-4">
                <div className="flex flex-col gap-2 text-xs">
                  <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
                    {synthesis.provider && (
                      <span className="text-muted-foreground">
                        Provider:{" "}
                        <span className="font-mono font-medium text-foreground">
                          {synthesis.provider}
                        </span>
                      </span>
                    )}
                    {synthesis.model && (
                      <span className="text-muted-foreground">
                        Model:{" "}
                        <span className="font-mono text-foreground">{synthesis.model}</span>
                      </span>
                    )}
                    {synthesis.fallback_used !== undefined && (
                      <span className="text-muted-foreground">
                        Fallback used:{" "}
                        <span className="font-medium text-foreground">
                          {synthesis.fallback_used ? "Yes" : "No"}
                        </span>
                      </span>
                    )}
                  </div>

                  {/* Only when the backend actually reports a fallback —
                   * never inferred, never claimed by default. */}
                  {synthesis.fallback_used === true && synthesis.provider && (
                    <p className="text-muted-foreground">
                      Primary provider was unavailable
                      {synthesis.primary_error_type ? ` (${synthesis.primary_error_type})` : ""}{" "}
                      — this answer was completed using {synthesis.provider}.
                    </p>
                  )}
                </div>
              </TechnicalDetails>
            )}
          </CardContent>
        </Card>

        <EvidenceFunnel steps={steps} citations={citations} />

        {citations.length > 0 ? (
          <CitationList citations={citations} onSelect={openEvidence} />
        ) : (
          <Card>
            <CardContent className="flex items-center gap-3 p-5">
              <SearchX className="h-4 w-4 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">No relevant evidence was found.</p>
            </CardContent>
          </Card>
        )}
      </motion.div>

      <EvidenceDrawer
        citation={selected?.citation ?? null}
        index={selected?.index ?? null}
        onClose={() => setSelected(null)}
      />
    </>
  );
}
