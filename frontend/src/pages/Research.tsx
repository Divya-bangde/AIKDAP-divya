import { useParams } from "react-router-dom";

import { ResearchPrompt } from "@/features/research/ResearchPrompt";
import { ResearchRunView } from "@/features/research/ResearchRunView";

export function Research() {
  const { runId } = useParams<{ runId?: string }>();

  if (runId) {
    return <ResearchRunView runId={runId} />;
  }

  return <ResearchPrompt />;
}
