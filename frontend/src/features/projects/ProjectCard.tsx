import { FolderKanban } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatRelativeTime } from "@/lib/format";
import type { components } from "@/types/api";

type ProjectRead = components["schemas"]["ProjectRead"];

const STATUS_VARIANT: Record<string, "success" | "muted"> = {
  active: "success",
  archived: "muted",
};

export function ProjectCard({ project }: { project: ProjectRead }) {
  return (
    <Link to={`/projects/${project.id}`}>
      <Card className="h-full transition-colors hover:border-primary/50">
        <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
          <div className="flex items-center gap-3">
            <div
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md"
              style={{ backgroundColor: project.color ?? "hsl(var(--accent))" }}
            >
              <FolderKanban className="h-4 w-4 text-white" />
            </div>
            <CardTitle className="line-clamp-1 text-base">{project.name}</CardTitle>
          </div>
          <Badge variant={STATUS_VARIANT[project.status] ?? "outline"}>
            {project.status}
          </Badge>
        </CardHeader>
        <CardContent>
          <p className="line-clamp-2 text-sm text-muted-foreground">
            {project.description ?? "No description."}
          </p>
          <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
            <span className="capitalize">{project.project_type.replace(/_/g, " ")}</span>
            <span>Updated {formatRelativeTime(project.updated_at)}</span>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
