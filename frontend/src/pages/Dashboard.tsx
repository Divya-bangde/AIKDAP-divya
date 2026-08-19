import { useQuery } from "@tanstack/react-query";
import { Activity, FileText, FolderKanban, Plus, Search, Upload } from "lucide-react";
import { Link } from "react-router-dom";

import { EmptyState } from "@/components/common/EmptyState";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SummaryCard } from "@/features/command-center/SummaryCard";
import { formatRelativeTime } from "@/lib/format";
import * as assetsService from "@/services/assets";
import * as healthService from "@/services/health";
import * as projectsService from "@/services/projects";
import * as researchService from "@/services/research";

export function Dashboard() {
  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: projectsService.listProjects });
  const assetsQuery = useQuery({ queryKey: ["assets", "all"], queryFn: () => assetsService.listAssets() });
  const runsQuery = useQuery({
    queryKey: ["research", "runs", "all"],
    queryFn: () => researchService.listResearchRuns(),
  });
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: healthService.getHealth,
    refetchOnWindowFocus: false,
  });

  const recentProjects = projectsQuery.data?.slice(0, 3) ?? [];
  const recentRuns = runsQuery.data?.slice(0, 5) ?? [];

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          What&apos;s happening across your AIKDAP workspace.
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
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

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          icon={FolderKanban}
          label="Projects"
          value={projectsQuery.data?.length}
          isLoading={projectsQuery.isLoading}
          isError={projectsQuery.isError}
        />
        <SummaryCard
          icon={FileText}
          label="Documents"
          value={assetsQuery.data?.length}
          isLoading={assetsQuery.isLoading}
          isError={assetsQuery.isError}
        />
        <SummaryCard
          icon={Search}
          label="Research Runs"
          value={runsQuery.data?.length}
          isLoading={runsQuery.isLoading}
          isError={runsQuery.isError}
        />
        <Card>
          <CardContent className="flex items-center gap-4 p-5">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-accent">
              <Activity className="h-5 w-5 text-accent-foreground" />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                System Status
              </p>
              {healthQuery.isSuccess ? (
                <StatusBadge domain="overallHealth" value={healthQuery.data.status} />
              ) : (
                <p className="text-sm text-muted-foreground">
                  {healthQuery.isLoading ? "Checking…" : "Unavailable"}
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recent Projects</CardTitle>
          </CardHeader>
          <CardContent>
            {recentProjects.length === 0 ? (
              <EmptyState icon={FolderKanban} title="No research projects yet." />
            ) : (
              <ul className="flex flex-col gap-3">
                {recentProjects.map((project) => (
                  <li key={project.id}>
                    <Link
                      to={`/projects/${project.id}`}
                      className="flex items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-secondary"
                    >
                      <span className="font-medium">{project.name}</span>
                      <span className="text-xs text-muted-foreground">
                        {formatRelativeTime(project.updated_at)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recent Research Runs</CardTitle>
          </CardHeader>
          <CardContent>
            {recentRuns.length === 0 ? (
              <EmptyState icon={Search} title="Ask your first research question." />
            ) : (
              <ul className="flex flex-col gap-3">
                {recentRuns.map((run) => (
                  <li key={run.id}>
                    <Link
                      to={`/research/${run.id}`}
                      className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-secondary"
                    >
                      <span className="line-clamp-1 font-medium">{run.query}</span>
                      <StatusBadge domain="researchRun" value={run.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
