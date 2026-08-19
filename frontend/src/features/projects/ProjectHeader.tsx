import { useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";
import { FolderKanban, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { layoutSpring } from "@/lib/motion";
import { projectLayoutIds } from "@/features/projects/ProjectCard";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import * as projectsService from "@/services/projects";
import type { components } from "@/types/api";

type ProjectRead = components["schemas"]["ProjectRead"];

export function ProjectHeader({ project }: { project: ProjectRead }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const deleteMutation = useMutation({
    mutationFn: () => projectsService.deleteProject(project.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate("/projects", { replace: true });
    },
  });

  const ids = projectLayoutIds(project.id);

  return (
    <div className="flex flex-col gap-4 border-b border-border pb-6">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-4">
          {/* Shares `layoutId` with the project card on /projects, so
           * arriving here animates that card's icon and title into
           * place rather than swapping one page for another. */}
          <motion.div
            layoutId={ids.icon}
            transition={layoutSpring}
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl shadow-subtle"
            style={{ backgroundColor: project.color ?? "hsl(var(--primary))" }}
          >
            <FolderKanban className="h-5 w-5 text-white" />
          </motion.div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <motion.h1 layoutId={ids.title} transition={layoutSpring} className="font-display text-title">
                {project.name}
              </motion.h1>
              <Badge variant={project.status === "active" ? "success" : "muted"}>
                {project.status}
              </Badge>
            </div>
            <p className="mt-1.5 text-sm text-muted-foreground">
              {project.description ?? "No description."}
            </p>
            <p className="mt-1 text-label uppercase text-muted-foreground">
              {project.project_type.replace(/_/g, " ")} project
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button onClick={() => navigate(`/research?project=${project.id}`)}>
            <Search className="h-4 w-4" />
            Start Research
          </Button>
          <Button variant="outline" size="icon" onClick={() => setConfirmOpen(true)}>
            <Trash2 className="h-4 w-4" />
            <span className="sr-only">Delete project</span>
          </Button>
        </div>
      </div>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete "{project.name}"?</DialogTitle>
            <DialogDescription>
              This permanently deletes the project and every document, embedding, and
              research run inside it. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={deleteMutation.isPending}
              onClick={() => deleteMutation.mutate()}
            >
              {deleteMutation.isPending ? "Deleting…" : "Delete Project"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
