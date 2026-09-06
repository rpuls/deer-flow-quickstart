import { useQuery } from "@tanstack/react-query";

import { UnauthorizedError } from "@/core/api/errors";

import { loadQuickstartCatalog, loadQuickstartStatus } from "./api";

export const QUICKSTART_STATUS_QUERY_KEY = ["quickstart", "status"] as const;
export const QUICKSTART_CATALOG_QUERY_KEY = ["quickstart", "catalog"] as const;

/** A 403 means "not an admin", which is a permanent answer, not a blip. */
function retryUnlessDenied(failureCount: number, error: unknown) {
  if (error instanceof UnauthorizedError) return false;
  if (error instanceof Error && error.message.includes("403")) return false;
  return failureCount < 1;
}

export function useQuickstartStatus({ enabled = true } = {}) {
  return useQuery({
    queryKey: QUICKSTART_STATUS_QUERY_KEY,
    queryFn: loadQuickstartStatus,
    enabled,
    retry: retryUnlessDenied,
    refetchOnWindowFocus: false,
  });
}

export function useQuickstartCatalog({ enabled = true } = {}) {
  return useQuery({
    queryKey: QUICKSTART_CATALOG_QUERY_KEY,
    queryFn: loadQuickstartCatalog,
    enabled,
    retry: retryUnlessDenied,
    refetchOnWindowFocus: false,
    // The catalog is compiled into the Gateway image; it cannot change while
    // the tab is open.
    staleTime: Infinity,
  });
}
