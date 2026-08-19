import { useQuery, type QueryKey } from "@tanstack/react-query";

const DEFAULT_INTERVAL_MS = Number(
  import.meta.env.VITE_RESEARCH_POLL_INTERVAL_MS ?? 1500,
);

interface UsePollingOptions<T> {
  queryKey: QueryKey;
  queryFn: () => Promise<T>;
  /** Polling stops (no more requests) once this returns true for the
   * latest fetched data — e.g. `status === "completed" || "failed"`.
   * Never based on elapsed time: only the backend's own reported
   * state ends polling (Phase 19: "Do NOT infer progress based on
   * elapsed time"). */
  isTerminal: (data: T) => boolean;
  intervalMs?: number;
  enabled?: boolean;
}

/** A TanStack Query wrapper that polls on a fixed interval until the
 * caller-supplied predicate says the resource reached a terminal
 * state, then stops automatically — used for research-run status,
 * and reusable for any other future asynchronous resource with the
 * same shape. */
export function usePolling<T>({
  queryKey,
  queryFn,
  isTerminal,
  intervalMs = DEFAULT_INTERVAL_MS,
  enabled = true,
}: UsePollingOptions<T>) {
  return useQuery({
    queryKey,
    queryFn,
    enabled,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data !== undefined && isTerminal(data)) return false;
      return intervalMs;
    },
  });
}
