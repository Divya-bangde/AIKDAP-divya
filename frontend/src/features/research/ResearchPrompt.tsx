import { useMutation, useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { Loader2, Search, Sparkles } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { messageFor } from "@/lib/api-error";
import { fadeUp } from "@/lib/motion";
import * as projectsService from "@/services/projects";
import * as researchService from "@/services/research";

export function ResearchPrompt() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [projectId, setProjectId] = useState(searchParams.get("project") ?? "");
  const [query, setQuery] = useState("");

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: projectsService.listProjects,
  });

  const submitMutation = useMutation({
    mutationFn: researchService.startResearchRun,
    onSuccess: (accepted) => navigate(`/research/${accepted.run_id}`),
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!projectId || !query.trim()) return;
    submitMutation.mutate({
      project_id: projectId,
      query: query.trim(),
      include_assets: true,
      include_web: true,
      max_results: 5,
    });
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={fadeUp} className="flex flex-col gap-8">
      <div className="max-w-2xl">
        <p className="text-label uppercase text-muted-foreground">Research</p>
        <h1 className="mt-1 font-display text-display">Ask your knowledge base</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          AIKDAP retrieves, reranks and grounds every answer in your own documents — and declines
          to answer when the evidence isn't there.
        </p>
      </div>

      <Card className="overflow-hidden">
        <div className="h-1 w-full bg-gradient-to-r from-primary via-ai to-primary/30" />
        <CardContent className="p-6">
          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <Label htmlFor="research-project">Project</Label>
              <select
                id="research-project"
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
                required
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                <option value="" disabled>
                  {projectsQuery.isLoading ? "Loading projects…" : "Select a project"}
                </option>
                {projectsQuery.data?.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="research-query">Question</Label>
              <Textarea
                id="research-query"
                required
                rows={4}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="What challenges does ABC Poultry face?"
                className="resize-none text-[15px] leading-relaxed"
              />
            </div>

            {submitMutation.isError && (
              <p role="alert" className="text-sm text-destructive">
                {messageFor(submitMutation.error)}
              </p>
            )}

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Sparkles className="h-3.5 w-3.5 text-ai" />
                Answers are grounded in this project's documents only
              </p>
              <Button
                type="submit"
                disabled={submitMutation.isPending || !projectId || !query.trim()}
              >
                {submitMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Search className="h-4 w-4" />
                )}
                {submitMutation.isPending ? "Starting…" : "Research"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </motion.div>
  );
}
