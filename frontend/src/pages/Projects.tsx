import { useQuery } from "@tanstack/react-query";
import { FolderKanban } from "lucide-react";

import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton } from "@/components/ui/skeleton";
import { CreateProjectDialog } from "@/features/projects/CreateProjectDialog";
import { ProjectCard } from "@/features/projects/ProjectCard";
import * as projectsService from "@/services/projects";

export function Projects() {
  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: projectsService.listProjects,
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
          <p className="text-sm text-muted-foreground">
            Every research project you own, in one place.
          </p>
        </div>
        <CreateProjectDialog />
      </div>

      {projectsQuery.isLoading && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      )}

      {projectsQuery.isError && <ErrorState error={projectsQuery.error} />}

      {projectsQuery.isSuccess && projectsQuery.data.length === 0 && (
        <EmptyState
          icon={FolderKanban}
          title="No research projects yet."
          description="Create a project to start uploading documents and running grounded research."
        />
      )}

      {projectsQuery.isSuccess && projectsQuery.data.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projectsQuery.data.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      )}
    </div>
  );
}
