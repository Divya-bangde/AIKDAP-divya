import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { RefreshCw } from "lucide-react";

import { ErrorState } from "@/components/common/ErrorState";
import { StatusBadge } from "@/components/common/StatusBadge";
import { PageTransition, Stagger, StaggerItem } from "@/components/motion/PageTransition";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import * as healthService from "@/services/health";

/** Groups the components the backend reports into the layers an
 * operator actually thinks in.
 *
 * This is presentation only: the grouping never changes, adds, or
 * hides a component. Anything the backend reports that isn't named
 * here falls into "Platform", so a new component added server-side
 * still appears without a frontend change. */
const GROUPS: { title: string; keys: string[] }[] = [
  { title: "Data", keys: ["postgres", "redis"] },
  { title: "Execution", keys: ["worker"] },
  { title: "Retrieval", keys: ["reranker"] },
  { title: "Synthesis", keys: ["gemini", "groq", "openrouter", "deepseek"] },
];

const DOT: Record<string, string> = {
  healthy: "bg-success",
  configured: "bg-primary",
  degraded: "bg-warning",
  rate_limited: "bg-warning",
  loading: "bg-warning",
  unavailable: "bg-destructive",
  quota_exhausted: "bg-destructive",
  configuration_error: "bg-destructive",
  not_configured: "bg-muted-foreground",
  disabled: "bg-muted-foreground",
  unknown: "bg-muted-foreground",
};

type Component = { status: string; detail?: string | null; latency_ms?: number | null; meta?: Record<string, unknown> };

function ComponentCard({ name, component }: { name: string; component: Component }) {
  return (
    <Card className="h-full transition-shadow duration-200 hover:shadow-raised">
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className={cn("h-2 w-2 shrink-0 rounded-full", DOT[component.status] ?? "bg-muted-foreground")} />
          <CardTitle className="truncate text-sm font-medium capitalize">{name}</CardTitle>
        </div>
        <StatusBadge domain="health" value={component.status} />
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {component.detail && <p className="text-xs text-muted-foreground">{component.detail}</p>}
        {component.latency_ms !== null && component.latency_ms !== undefined && (
          <p className="tabular font-mono text-xs text-muted-foreground">
            {component.latency_ms} ms
          </p>
        )}
        {component.meta && Object.keys(component.meta).length > 0 && (
          <div className="flex flex-wrap gap-1 pt-0.5">
            {Object.entries(component.meta).map(([key, value]) =>
              value === null || value === undefined || value === "" ? null : (
                <Badge key={key} variant="outline" className="max-w-full font-mono text-[10px] font-normal">
                  <span className="truncate">
                    {key}: {String(value)}
                  </span>
                </Badge>
              ),
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** `GET /health` is fetched only on mount and on explicit refresh —
 * never on an interval, so opening this page never becomes a
 * background poller. The endpoint is free by design (it reads the
 * Redis-backed provider breaker rather than calling any provider), and
 * this page keeps it that way. */
export function SystemHealth() {
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: healthService.getHealth,
    refetchOnWindowFocus: false,
  });

  const services = healthQuery.data?.services ?? {};
  const named = new Set(GROUPS.flatMap((group) => group.keys));
  const ungrouped = Object.keys(services).filter((key) => !named.has(key));
  const groups = [...GROUPS, ...(ungrouped.length > 0 ? [{ title: "Platform", keys: ungrouped }] : [])];

  return (
    <PageTransition>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-label uppercase text-muted-foreground">Observability</p>
          <h1 className="mt-1 font-display text-display">System Health</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Live status reported by the backend. Opening this page calls no AI provider.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => healthQuery.refetch()}
          disabled={healthQuery.isFetching}
        >
          <RefreshCw className={cn("h-4 w-4", healthQuery.isFetching && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {healthQuery.isLoading && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      )}

      {healthQuery.isError && (
        <ErrorState error={healthQuery.error} title="Unable to retrieve system health." />
      )}

      {healthQuery.isSuccess && (
        <>
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
            className="flex flex-wrap items-center gap-4 rounded-xl border border-border bg-card p-5 shadow-subtle"
          >
            <span
              className={cn(
                "h-3 w-3 shrink-0 rounded-full",
                DOT[healthQuery.data.status] ?? "bg-muted-foreground",
              )}
            />
            <div>
              <p className="text-label uppercase text-muted-foreground">Overall status</p>
              <p className="mt-0.5 font-display text-title capitalize">{healthQuery.data.status}</p>
            </div>
            <div className="ml-auto text-right">
              <p className="font-mono text-xs text-muted-foreground">
                {healthQuery.data.app} v{healthQuery.data.version}
              </p>
              <p className="font-mono text-xs text-muted-foreground">
                {healthQuery.data.environment}
              </p>
            </div>
            <StatusBadge domain="overallHealth" value={healthQuery.data.status} />
          </motion.div>

          <h2 className="sr-only">Service status</h2>

          <div className="flex flex-col gap-6">
            {groups.map((group) => {
              const present = group.keys.filter((key) => key in services);
              if (present.length === 0) return null;

              return (
                <section key={group.title}>
                  <h3 className="mb-3 text-label uppercase text-muted-foreground">
                    {group.title}
                  </h3>
                  <Stagger className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {present.map((key) => (
                      <StaggerItem key={key} className="h-full">
                        <ComponentCard name={key} component={services[key] as Component} />
                      </StaggerItem>
                    ))}
                  </Stagger>
                </section>
              );
            })}
          </div>
        </>
      )}
    </PageTransition>
  );
}
