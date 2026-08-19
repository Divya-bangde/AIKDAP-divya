import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton } from "@/components/ui/skeleton";
import { DocumentsSection } from "@/features/assets/DocumentsSection";
import { ProjectHeader } from "@/features/projects/ProjectHeader";
import * as projectsService from "@/services/projects";

export function ProjectDetail() {
  const { id } = useParams<{ id: string }>();

  const projectQuery = useQuery({
    queryKey: ["projects", id],
    queryFn: () => projectsService.getProject(id!),
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

  return (
    <div className="flex flex-col gap-6">
      <ProjectHeader project={projectQuery.data} />
      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Documents
        </h2>
        <DocumentsSection projectId={projectQuery.data.id} />
      </div>
    </div>
  );
}
