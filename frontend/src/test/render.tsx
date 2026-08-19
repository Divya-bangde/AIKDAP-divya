import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

/** Wraps a component with the same providers `main.tsx` supplies in
 * the real app (QueryClient + Router), so component tests exercise
 * real TanStack Query state transitions rather than a stub. Retries
 * are disabled — a test that mocks one failed response should see
 * exactly one failure, not wait through React Query's retry/backoff. */
export function renderWithProviders(
  ui: ReactElement,
  { route = "/" }: { route?: string } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}
