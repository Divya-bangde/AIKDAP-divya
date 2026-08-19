import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { StatusBadge } from "@/components/common/StatusBadge";
import { ErrorState } from "@/components/common/ErrorState";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import * as healthService from "@/services/health";

/** Phase 24/38: `GET /health` is fetched only on mount and on explicit
 * refresh — never on an interval, so opening this page never becomes
 * a background poller against a real, non-free health check. */
export function SystemHealth() {
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: healthService.getHealth,
    refetchOnWindowFocus: false,
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">System Health</h1>
          <p className="text-sm text-muted-foreground">Live status from the backend.</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => healthQuery.refetch()}
          disabled={healthQuery.isFetching}
        >
          <RefreshCw className={`h-4 w-4 ${healthQuery.isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {healthQuery.isLoading && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      )}

      {healthQuery.isError && (
        <ErrorState error={healthQuery.error} title="Unable to retrieve system health." />
      )}

      {healthQuery.isSuccess && (
        <>
          <div className="flex items-center gap-3 rounded-lg border border-border bg-card p-4">
            <span className="text-sm font-medium">Overall status</span>
            <StatusBadge domain="overallHealth" value={healthQuery.data.status} />
            <span className="ml-auto text-xs text-muted-foreground">
              {healthQuery.data.app} v{healthQuery.data.version} · {healthQuery.data.environment}
            </span>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(healthQuery.data.services).map(([name, component]) => (
              <Card key={name}>
                <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium capitalize">{name}</CardTitle>
                  <StatusBadge domain="health" value={component.status} />
                </CardHeader>
                <CardContent className="flex flex-col gap-1.5 text-xs text-muted-foreground">
                  {component.detail && <p>{component.detail}</p>}
                  {component.latency_ms !== null && component.latency_ms !== undefined && (
                    <p>{component.latency_ms} ms</p>
                  )}
                  {component.meta && Object.keys(component.meta).length > 0 && (
                    <div className="flex flex-wrap gap-1 pt-1">
                      {Object.entries(component.meta).map(([key, value]) =>
                        value === null || value === undefined || value === "" ? null : (
                          <Badge key={key} variant="outline" className="font-normal">
                            {key}: {String(value)}
                          </Badge>
                        ),
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
