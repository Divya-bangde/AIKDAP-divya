import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import {
  ArrowRight,
  FileText,
  FolderKanban,
  Plus,
  Quote,
  Search,
  Upload,
} from "lucide-react";
import { Link } from "react-router-dom";

import { EmptyState } from "@/components/common/EmptyState";
import { StatusBadge } from "@/components/common/StatusBadge";
import { PageTransition, Stagger, StaggerItem } from "@/components/motion/PageTransition";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PipelineOverview } from "@/features/command-center/PipelineOverview";
import { SummaryCard } from "@/features/command-center/SummaryCard";
import { formatRelativeTime } from "@/lib/format";
import { hoverLift } from "@/lib/motion";
import * as assetsService from "@/services/assets";
import * as projectsService from "@/services/projects";
import * as researchService from "@/services/research";

export function Dashboard() {
  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: projectsService.listProjects });
  const assetsQuery = useQuery({
    queryKey: ["assets", "all"],
    queryFn: () => assetsService.listAssets(),
  });
  const runsQuery = useQuery({
    queryKey: ["research", "runs", "all"],
    queryFn: () => researchService.listResearchRuns(),
  });

  const recentProjects = projectsQuery.data?.slice(0, 4) ?? [];
  const recentRuns = runsQuery.data?.slice(0, 5) ?? [];

  // Counted from the real `grounding_status` the backend stores on each
  // run — not inferred from `status`, which only says the run finished.
  const groundedRuns = runsQuery.data?.filter(
    (run) => run.grounding_status === "grounded",
  ).length;

  return (
    <PageTransition>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-label uppercase text-muted-foreground">Command Center</p>
          <h1 className="mt-1 font-display text-display">Your intelligence workspace</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Every project, document and grounded research run in AIKDAP, in one place.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild>
            <Link to="/projects">
              <Plus className="h-4 w-4" />
              Create Project
            </Link>
          </Button>
          <Button variant="outline" asChild>
            <Link to="/projects">
              <Upload className="h-4 w-4" />
              Upload Document
            </Link>
          </Button>
          <Button variant="outline" asChild>
            <Link to="/research">
              <Search className="h-4 w-4" />
              Start Research
            </Link>
          </Button>
        </div>
      </div>

      <h2 className="sr-only">Workspace overview</h2>
      <Stagger className="grid grid-cols-1 items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StaggerItem className="h-full">
          <SummaryCard
            icon={FolderKanban}
            label="Projects"
            value={projectsQuery.data?.length}
            isLoading={projectsQuery.isLoading}
            isError={projectsQuery.isError}
          />
        </StaggerItem>
        <StaggerItem className="h-full">
          <SummaryCard
            icon={FileText}
            label="Documents"
            value={assetsQuery.data?.length}
            isLoading={assetsQuery.isLoading}
            isError={assetsQuery.isError}
            tone="ai"
          />
        </StaggerItem>
        <StaggerItem className="h-full">
          <SummaryCard
            icon={Search}
            label="Research Runs"
            value={runsQuery.data?.length}
            isLoading={runsQuery.isLoading}
            isError={runsQuery.isError}
          />
        </StaggerItem>
        <StaggerItem className="h-full">
          <SummaryCard
            icon={Quote}
            label="Grounded Answers"
            value={groundedRuns}
            isLoading={runsQuery.isLoading}
            isError={runsQuery.isError}
            tone="success"
            detail="Backed by cited evidence"
          />
        </StaggerItem>
      </Stagger>

      <PipelineOverview />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-section">Recent Projects</CardTitle>
            <Link
              to="/projects"
              className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              View all
              <ArrowRight className="h-3 w-3" />
            </Link>
          </CardHeader>
          <CardContent>
            {recentProjects.length === 0 ? (
              <EmptyState icon={FolderKanban} title="No research projects yet." />
            ) : (
              <Stagger className="flex flex-col gap-1">
                {recentProjects.map((project) => (
                  <StaggerItem key={project.id}>
                    <motion.div {...hoverLift}>
                      <Link
                        to={`/projects/${project.id}`}
                        className="group flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-sunken"
                      >
                        <div
                          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md"
                          style={{ backgroundColor: project.color ?? "hsl(var(--accent))" }}
                        >
                          <FolderKanban className="h-3.5 w-3.5 text-white" />
                        </div>
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">
                          {project.name}
                        </span>
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {formatRelativeTime(project.updated_at)}
                        </span>
                      </Link>
                    </motion.div>
                  </StaggerItem>
                ))}
              </Stagger>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-section">Recent Research Runs</CardTitle>
            <Link
              to="/research"
              className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              New run
              <ArrowRight className="h-3 w-3" />
            </Link>
          </CardHeader>
          <CardContent>
            {recentRuns.length === 0 ? (
              <EmptyState icon={Search} title="Ask your first research question." />
            ) : (
              <Stagger className="flex flex-col gap-1">
                {recentRuns.map((run) => (
                  <StaggerItem key={run.id}>
                    <Link
                      to={`/research/${run.id}`}
                      className="flex items-center justify-between gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-sunken"
                    >
                      <span className="line-clamp-1 min-w-0 flex-1 text-sm font-medium">
                        {run.query}
                      </span>
                      <div className="flex shrink-0 items-center gap-2">
                        {run.grounding_status ? (
                          <StatusBadge domain="grounding" value={run.grounding_status} />
                        ) : (
                          <StatusBadge domain="researchRun" value={run.status} />
                        )}
                      </div>
                    </Link>
                  </StaggerItem>
                ))}
              </Stagger>
            )}
          </CardContent>
        </Card>
      </div>
    </PageTransition>
  );
}
