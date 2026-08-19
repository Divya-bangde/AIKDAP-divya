import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, Search } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { messageFor } from "@/lib/api-error";
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
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Research</h1>
        <p className="text-sm text-muted-foreground">
          Ask AIKDAP anything about your knowledge base.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4 rounded-lg border border-border bg-card p-5">
        <div className="flex flex-col gap-2">
          <Label htmlFor="research-project">Project</Label>
          <select
            id="research-project"
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
            required
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
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
            rows={3}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="What challenges does ABC Poultry face?"
          />
        </div>

        {submitMutation.isError && (
          <p role="alert" className="text-sm text-destructive">
            {messageFor(submitMutation.error)}
          </p>
        )}

        <Button
          type="submit"
          disabled={submitMutation.isPending || !projectId || !query.trim()}
          className="self-end"
        >
          {submitMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Search className="h-4 w-4" />
          )}
          {submitMutation.isPending ? "Starting…" : "Research"}
        </Button>
      </form>
    </div>
  );
}
