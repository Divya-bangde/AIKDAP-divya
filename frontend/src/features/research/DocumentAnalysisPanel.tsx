import { useState } from "react";
import { Search, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { analyzeResearchDocument } from "@/services/research";
import type { components } from "@/types/api";

type AssetRead = components["schemas"]["AssetRead"];
type ResearchDocumentUnderstanding = components["schemas"]["ResearchDocumentUnderstanding"];

export function DocumentAnalysisPanel({ asset }: { asset: AssetRead }) {
  const [goalType] = useState("understand");
  const [goalDesc, setGoalDesc] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Local state for immediate feedback; actual persistence is in asset.metadata
  const [localUnderstanding, setLocalUnderstanding] = useState<ResearchDocumentUnderstanding | null>(
    (asset.metadata?.research_understanding as ResearchDocumentUnderstanding | undefined) ?? null
  );

  const handleAnalyze = async () => {
    if (!goalDesc.trim()) return;
    setIsAnalyzing(true);
    setError(null);
    try {
      const result = await analyzeResearchDocument(asset.id, asset.project_id, {
        goal: { type: goalType, description: goalDesc },
      });
      setLocalUnderstanding(result);
    } catch (err: any) {
      setError(err.message || "Failed to analyze document");
    } finally {
      setIsAnalyzing(false);
    }
  };

  return (
    <Card className="sticky top-24 mt-5">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div className="flex items-center gap-2">
          <Search className="h-4 w-4 text-primary" />
          <CardTitle>Research Gap Analysis</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!localUnderstanding ? (
          <div className="flex flex-col gap-3 rounded-lg bg-sunken p-4">
            <p className="text-sm text-muted-foreground">
              Define a research goal to analyze this document for gaps and conflicts.
            </p>
            <Input 
              placeholder="e.g. Reproduce this experiment" 
              value={goalDesc}
              onChange={(e) => setGoalDesc(e.target.value)}
              disabled={isAnalyzing}
            />
            <Button onClick={handleAnalyze} disabled={isAnalyzing || !goalDesc.trim()}>
              {isAnalyzing && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Analyze Document
            </Button>
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
        ) : (
          <div className="flex flex-col gap-5">
            <div>
              <p className="text-sm font-semibold">Goal Assessment</p>
              <div className="mt-2 flex items-center gap-2">
                <Badge variant={localUnderstanding.sufficiency === "sufficient" ? "default" : "destructive"}>
                  {localUnderstanding.sufficiency}
                </Badge>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                {localUnderstanding.sufficiency_reason}
              </p>
            </div>

            {(localUnderstanding.missing_information ?? []).length > 0 && (
              <div>
                <p className="text-sm font-semibold text-destructive">Gaps Detected</p>
                <ul className="mt-2 flex flex-col gap-2">
                  {(localUnderstanding.missing_information ?? []).map((gap, i) => (
                    <li key={i} className="rounded-md border p-2 text-sm">
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{gap.gap_type}</span>
                        <Badge variant="outline">{gap.classification}</Badge>
                      </div>
                      <p className="mt-1 text-muted-foreground">{gap.description}</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            
            {(localUnderstanding.conflicts ?? []).length > 0 && (
              <div>
                <p className="text-sm font-semibold text-destructive">Conflicts Detected</p>
                <ul className="mt-2 flex flex-col gap-2">
                  {(localUnderstanding.conflicts ?? []).map((conflict, i) => (
                    <li key={i} className="rounded-md border border-destructive/50 bg-destructive/10 p-2 text-sm text-destructive-foreground">
                      <p>{conflict.description}</p>
                      <p className="mt-1 text-xs opacity-80">Sources: {conflict.sources.join(", ")}</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <Button variant="outline" onClick={() => setLocalUnderstanding(null)} size="sm">
              Re-analyze against new goal
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
