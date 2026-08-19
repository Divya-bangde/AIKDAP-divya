import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { FileText, Search } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { StatusBadge } from "@/components/common/StatusBadge";
import { PageTransition } from "@/components/motion/PageTransition";
import { AnimatedNumber } from "@/components/motion/AnimatedNumber";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DocumentsSection } from "@/features/assets/DocumentsSection";
import { allSettled, knowledgeState } from "@/features/assets/asset-state";
import { ProjectHeader } from "@/features/projects/ProjectHeader";
import { usePolling } from "@/hooks/usePolling";
import { fadeUp } from "@/lib/motion";
import * as assetsService from "@/services/assets";
import * as projectsService from "@/services/projects";
import * as researchService from "@/services/research";

const TABS = [
  { value: "overview", label: "Overview" },
  { value: "documents", label: "Documents" },
  { value: "research", label: "Research" },
];

/** One real, backend-counted figure about this project's knowledge base. */
function KnowledgeStat({ label, value, detail }: { label: string; value: number; detail: string }) {
  return (
    <div className="rounded-lg border border-border bg-sunken p-4">
      <p className="text-label uppercase text-muted-foreground">{label}</p>
      <AnimatedNumber value={value} className="tabular mt-1 block text-2xl font-semibold" />
      <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">{detail}</p>
    </div>
  );
}

export function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState("overview");

  const projectQuery = useQuery({
    queryKey: ["projects", id],
    queryFn: () => projectsService.getProject(id!),
    enabled: Boolean(id),
  });

  // Same query key and same terminal condition as `DocumentsSection`,
  // so both observers share one cached response and one polling
  // schedule rather than competing.
  const assetsQuery = usePolling({
    queryKey: ["assets", id],
    queryFn: () => assetsService.listAssets(id!),
    isTerminal: allSettled,
    enabled: Boolean(id),
  });

  const runsQuery = useQuery({
    queryKey: ["research", "runs", id],
    queryFn: () => researchService.listResearchRuns(id!),
    enabled: Boolean(id),
  });

  if (projectQuery.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (projectQuery.isError) {
    return <ErrorState error={projectQuery.error} title="Project not found" />;
  }

  if (!projectQuery.data) return null;

  const project = projectQuery.data;
  const assets = assetsQuery.data ?? [];
  const stats = knowledgeState(assets);
  const runs = runsQuery.data ?? [];

  return (
    <PageTransition>
      <ProjectHeader project={project} />

      <Tabs value={tab} onValueChange={setTab} className="flex flex-col gap-6">
        <TabsList>
          {TABS.map((item) => (
            <TabsTrigger key={item.value} value={item.value} isActive={tab === item.value}>
              {item.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview">
          <motion.div
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            className="flex flex-col gap-6"
          >
            <div>
              <h2 className="mb-3 text-section">Knowledge state</h2>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <KnowledgeStat label="Documents" value={stats.total} detail="Uploaded" />
                <KnowledgeStat label="Extracted" value={stats.extracted} detail="Pipeline" />
                <KnowledgeStat label="Understood" value={stats.understood} detail="Qwen 3.5" />
                <KnowledgeStat label="Embedded" value={stats.embedded} detail="BGE-M3" />
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                Counts reflect the backend's reported state for each document.
              </p>
            </div>

            <Card>
              <CardHeader>
                <CardTitle>Ready to research</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap items-center justify-between gap-4">
                <p className="max-w-lg text-sm text-muted-foreground">
                  {stats.embedded > 0
                    ? "This project has embedded knowledge. Ask a question and AIKDAP will retrieve, rerank and ground an answer in these documents."
                    : "Upload and process a document first — AIKDAP only answers from evidence it can cite."}
                </p>
                <Button asChild>
                  <Link to={`/research?project=${project.id}`}>
                    <Search className="h-4 w-4" />
                    Start Research
                  </Link>
                </Button>
              </CardContent>
            </Card>
          </motion.div>
        </TabsContent>

        <TabsContent value="documents">
          <motion.div initial="hidden" animate="visible" variants={fadeUp}>
            <DocumentsSection projectId={project.id} />
          </motion.div>
        </TabsContent>

        <TabsContent value="research">
          <motion.div initial="hidden" animate="visible" variants={fadeUp}>
            {runsQuery.isLoading ? (
              <Skeleton className="h-32" />
            ) : runs.length === 0 ? (
              <EmptyState
                icon={Search}
                title="No research runs in this project yet."
                description="Ask a question to produce a grounded, cited answer."
              />
            ) : (
              <Card>
                <CardContent className="flex flex-col gap-1 p-3">
                  {runs.map((run) => (
                    <Link
                      key={run.id}
                      to={`/research/${run.id}`}
                      className="flex items-center justify-between gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-sunken"
                    >
                      <div className="flex min-w-0 items-center gap-3">
                        <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span className="line-clamp-1 text-sm font-medium">{run.query}</span>
                      </div>
                      {run.grounding_status ? (
                        <StatusBadge domain="grounding" value={run.grounding_status} />
                      ) : (
                        <StatusBadge domain="researchRun" value={run.status} />
                      )}
                    </Link>
                  ))}
                </CardContent>
              </Card>
            )}
          </motion.div>
        </TabsContent>
      </Tabs>
    </PageTransition>
  );
}
