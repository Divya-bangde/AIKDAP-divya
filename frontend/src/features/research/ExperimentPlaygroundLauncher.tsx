import { useState } from "react";
import { FlaskConical, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ExperimentPlaygroundPanel } from "@/features/research/ExperimentPlaygroundPanel";
import {
  createExperimentFromEquation,
  createExperimentFromUnderstanding,
  type ExperimentPlan,
} from "@/services/experiments";
import type { components } from "@/types/api";

type AssetRead = components["schemas"]["AssetRead"];

/**
 * Entry point into the Experiment Plan Engine (Sprint 16 Phase 6) from
 * a selected document. Two starting points, matching the two real
 * creation paths the backend supports: from the asset's own stored
 * research understanding (if it has been analyzed already), or from a
 * bare equation typed in directly (Scenario 1) -- never both silently
 * merged.
 */
export function ExperimentPlaygroundLauncher({ asset }: { asset: AssetRead }) {
  const [plan, setPlan] = useState<ExperimentPlan | null>(null);
  const [equation, setEquation] = useState("");
  const [equationInputs, setEquationInputs] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasUnderstanding = Boolean(
    (asset.metadata as Record<string, unknown> | undefined)?.research_understanding
  );

  async function handleCreateFromUnderstanding() {
    setCreating(true);
    setError(null);
    try {
      const created = await createExperimentFromUnderstanding({
        project_id: asset.project_id,
        title: `${asset.title} — Experiment Plan`,
        source_asset_id: asset.id,
        goal: "understanding",
      });
      setPlan(created);
    } catch (err: any) {
      setError(err.message || "Could not create an experiment plan from this document.");
    } finally {
      setCreating(false);
    }
  }

  async function handleCreateFromEquation() {
    if (!equation.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const knownInputs = equationInputs
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const created = await createExperimentFromEquation({
        project_id: asset.project_id,
        title: `${asset.title} — ${equation}`,
        expression: equation,
        goal: "understanding",
        known_inputs: knownInputs.length > 0 ? knownInputs : undefined,
        source_asset_id: asset.id,
      });
      setPlan(created);
    } catch (err: any) {
      setError(err.message || "Could not parse that equation.");
    } finally {
      setCreating(false);
    }
  }

  if (plan) {
    return <ExperimentPlaygroundPanel plan={plan} />;
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2 space-y-0">
        <FlaskConical className="h-4 w-4 text-primary" />
        <CardTitle className="text-sm">Experiment Playground</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {error && <p className="text-sm text-destructive">{error}</p>}

        {hasUnderstanding && (
          <div className="rounded-md border border-border bg-sunken p-3">
            <p className="text-sm text-muted-foreground">
              Build a reviewable experiment plan from this document's stored research
              understanding -- variables, equations, and evaluation metrics it already found.
            </p>
            <Button className="mt-3" size="sm" disabled={creating} onClick={handleCreateFromUnderstanding}>
              {creating && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
              Build Plan From This Document
            </Button>
          </div>
        )}

        <div className="rounded-md border border-border p-3">
          <p className="text-sm text-muted-foreground">
            Or start directly from an equation (e.g. <code className="font-mono">Y = (aX + b) / (cX + d)</code>).
          </p>
          <div className="mt-3 flex flex-col gap-2">
            <div>
              <Label htmlFor="equation-input" className="text-xs">
                Equation
              </Label>
              <Input
                id="equation-input"
                placeholder="Y = (aX + b) / (cX + d)"
                value={equation}
                onChange={(e) => setEquation(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="equation-known-inputs" className="text-xs">
                Known inputs (comma-separated, optional)
              </Label>
              <Input
                id="equation-known-inputs"
                placeholder="X"
                value={equationInputs}
                onChange={(e) => setEquationInputs(e.target.value)}
              />
            </div>
            <Button
              size="sm"
              variant="outline"
              disabled={creating || !equation.trim()}
              onClick={handleCreateFromEquation}
            >
              {creating && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
              Build Plan From Equation
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
