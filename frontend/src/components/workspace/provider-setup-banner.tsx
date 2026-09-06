"use client";

import { SparklesIcon } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useModels } from "@/core/models/hooks";
import { useQuickstartStatus } from "@/core/quickstart";

import { openSettingsDialog } from "./settings";

/**
 * First-run nudge for a deployment that has no LLM provider yet.
 *
 * A one-click deploy of this fork starts with zero credentials on purpose, so
 * the very first thing a new operator sees must be the way to fix that. The
 * banner reads the models list (already loaded elsewhere in the workspace) and
 * only asks the Gateway for quickstart status once that list comes back empty -
 * a non-admin gets a 403 there, which is exactly when the banner should stay
 * hidden because they cannot act on it anyway.
 */
export function ProviderSetupBanner() {
  const {
    models,
    isLoading: modelsLoading,
    error: modelsError,
  } = useModels({
    enabled: false,
  });
  const noModels = !modelsLoading && !modelsError && models.length === 0;
  const { data } = useQuickstartStatus({ enabled: noModels });

  if (!noModels || !data?.needs_onboarding) {
    return null;
  }

  return (
    <Alert className="rounded-none border-x-0 border-t-0 border-amber-500/30 bg-amber-500/10 px-4 py-2">
      <AlertDescription className="flex w-full items-center justify-between gap-3 text-amber-900 dark:text-amber-200">
        <span className="flex min-w-0 items-center gap-2">
          <SparklesIcon className="size-4 shrink-0" />
          <span className="min-w-0">
            No model provider is configured yet. Add an API key to start
            chatting.
          </span>
        </span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => openSettingsDialog("providers")}
          className="h-7 shrink-0 border-amber-500/40 bg-transparent px-3 text-xs shadow-none hover:bg-amber-500/10 dark:bg-transparent"
        >
          Set up a provider
        </Button>
      </AlertDescription>
    </Alert>
  );
}
