import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CornerDownRight, Loader2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { messageFor } from "@/lib/api-error";
import { submitOnEnter } from "@/lib/utils";
import * as researchService from "@/services/research";

/** Ask a follow-up about a completed run ("explain that briefly").
 *
 * Starts a new run linked to this one through `parent_run_id`. The
 * backend answers from the same paper first -- the parent's question and
 * answer frame the follow-up, and retrieval is scoped to the document
 * the parent answer rests on -- and searches the web only when that
 * evidence is insufficient. Nothing is answered client-side. */
export function FollowUpPrompt({ runId, projectId }: { runId: string; projectId: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const fieldId = `follow-up-${runId}`;

  const mutation = useMutation({
    mutationFn: researchService.startResearchRun,
    onSuccess: (accepted) => {
      queryClient.invalidateQueries({ queryKey: ["research", "runs"] });
      setQuery("");
      navigate(`/research/${accepted.run_id}`);
    },
  });

  // The API rejects queries under 3 characters; mirror that here.
  const canSubmit = query.trim().length >= 3 && !mutation.isPending;

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    mutation.mutate({
      project_id: projectId,
      query: query.trim(),
      parent_run_id: runId,
      include_assets: true,
      include_web: true,
      max_results: 5,
    });
  }

  return (
    <Card>
      <CardContent className="p-5">
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <Label htmlFor={fieldId}>Ask a follow-up</Label>
          <Textarea
            id={fieldId}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={submitOnEnter}
            rows={2}
            placeholder="e.g. Explain that briefly — or ask for a chart or diagram of it"
          />
          {mutation.isError && (
            <p role="alert" className="text-sm text-destructive">
              {messageFor(mutation.error)}
            </p>
          )}
          <div className="flex justify-end">
            <Button type="submit" disabled={!canSubmit}>
              {mutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CornerDownRight className="h-4 w-4" />
              )}
              Ask
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
