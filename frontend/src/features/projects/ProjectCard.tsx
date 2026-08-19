import { motion } from "motion/react";
import { ArrowUpRight, FileText, FolderKanban, Quote } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatRelativeTime } from "@/lib/format";
import { hoverLift, layoutSpring } from "@/lib/motion";
import type { components } from "@/types/api";

type ProjectRead = components["schemas"]["ProjectRead"];

/** Real counts for one project, or `undefined` where not yet known.
 * `undefined` is rendered as nothing — never as zero. */
export interface ProjectStats {
  documents?: number;
  groundedAnswers?: number;
}

const STATUS_VARIANT: Record<string, "success" | "muted"> = {
  active: "success",
  archived: "muted",
};

/** Stable across the card and the project workspace header, so Motion
 * animates one element between the two routes instead of cross-fading
 * two unrelated ones. Derived from the project id, so two cards never
 * share an id and the wrong pair can never be matched. */
export function projectLayoutIds(projectId: string) {
  return {
    icon: `project-icon-${projectId}`,
    title: `project-title-${projectId}`,
  };
}

function Stat({
  icon: Icon,
  value,
  singular,
  plural,
}: {
  icon: typeof FileText;
  value: number | undefined;
  singular: string;
  plural: string;
}) {
  if (value === undefined) return null;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <Icon className="h-3.5 w-3.5" />
      <span className="tabular font-medium text-foreground">{value}</span>
      {value === 1 ? singular : plural}
    </span>
  );
}

export function ProjectCard({
  project,
  stats,
}: {
  project: ProjectRead;
  stats?: ProjectStats;
}) {
  const ids = projectLayoutIds(project.id);

  return (
    <motion.div {...hoverLift} className="h-full">
      <Link to={`/projects/${project.id}`} className="block h-full">
        <Card className="group relative h-full overflow-hidden transition-all duration-200 hover:border-border-strong hover:shadow-raised">
          {/* A hairline that lights up on hover — enough to register as
           * interactive without moving or recolouring the card. */}
          <span
            aria-hidden="true"
            className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/60 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100"
          />

          <CardContent className="flex h-full flex-col gap-4 p-5">
            <div className="flex items-start justify-between gap-3">
              <motion.div
                layoutId={ids.icon}
                transition={layoutSpring}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg shadow-subtle"
                style={{ backgroundColor: project.color ?? "hsl(var(--primary))" }}
              >
                <FolderKanban className="h-4.5 w-4.5 text-white" />
              </motion.div>
              <div className="flex items-center gap-2">
                <Badge variant={STATUS_VARIANT[project.status] ?? "outline"}>
                  {project.status}
                </Badge>
                <ArrowUpRight className="h-4 w-4 text-muted-foreground opacity-0 transition-all duration-200 group-hover:translate-x-0.5 group-hover:opacity-100" />
              </div>
            </div>

            <div className="min-w-0 flex-1">
              <motion.h3
                layoutId={ids.title}
                transition={layoutSpring}
                className="line-clamp-1 text-section"
              >
                {project.name}
              </motion.h3>
              <p className="mt-1.5 line-clamp-2 text-sm text-muted-foreground">
                {project.description ?? "No description."}
              </p>
            </div>

            {(stats?.documents !== undefined || stats?.groundedAnswers !== undefined) && (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                <Stat
                  icon={FileText}
                  value={stats?.documents}
                  singular="document"
                  plural="documents"
                />
                <Stat
                  icon={Quote}
                  value={stats?.groundedAnswers}
                  singular="grounded answer"
                  plural="grounded answers"
                />
              </div>
            )}

            <div className="flex items-center justify-between border-t border-border pt-3 text-xs text-muted-foreground">
              <span className="capitalize">{project.project_type.replace(/_/g, " ")}</span>
              <span>Updated {formatRelativeTime(project.updated_at)}</span>
            </div>
          </CardContent>
        </Card>
      </Link>
    </motion.div>
  );
}
