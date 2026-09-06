"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckIcon,
  ExternalLinkIcon,
  KeyRoundIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  Trash2Icon,
  TriangleAlertIcon,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MODELS_QUERY_KEY } from "@/core/models/hooks";
import {
  QUICKSTART_STATUS_QUERY_KEY,
  deleteLLMProvider,
  discoverProviderModels,
  resetToolProvider,
  saveLLMProvider,
  saveToolProvider,
  setDefaultModel,
  useQuickstartCatalog,
  useQuickstartStatus,
  verifyProvider,
} from "@/core/quickstart";
import type {
  QuickstartConfiguredProvider,
  QuickstartLLMProviderSpec,
  QuickstartModelInput,
  QuickstartModelPreset,
  QuickstartStatus,
  QuickstartToolProviderSpec,
} from "@/core/quickstart";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

/** A model row in the picker: a preset, a discovered id, or a hand-typed one. */
type ModelChoice = QuickstartModelPreset & {
  source: "preset" | "discovered" | "custom";
};

function presetToChoice(preset: QuickstartModelPreset): ModelChoice {
  return { ...preset, source: "preset" };
}

export function ProvidersSettingsPage() {
  const queryClient = useQueryClient();
  const status = useQuickstartStatus();
  const catalog = useQuickstartCatalog();

  const [addingProvider, setAddingProvider] = useState<string | null>(null);
  const [editingProvider, setEditingProvider] = useState<string | null>(null);

  // Every mutation returns the fresh status, and every one of them can change
  // which models exist — so the chat UI's model list is invalidated too.
  const applyStatus = useCallback(
    (next: QuickstartStatus) => {
      queryClient.setQueryData(QUICKSTART_STATUS_QUERY_KEY, next);
      void queryClient.invalidateQueries({ queryKey: MODELS_QUERY_KEY });
      setAddingProvider(null);
      setEditingProvider(null);
    },
    [queryClient],
  );

  const removeProvider = useMutation({
    mutationFn: deleteLLMProvider,
    onSuccess: (next) => {
      applyStatus(next);
      toast.success("Provider removed");
    },
    onError: (error) =>
      toast.error(errorMessage(error, "Could not remove the provider")),
  });

  const chooseDefaultModel = useMutation({
    mutationFn: setDefaultModel,
    onSuccess: (next) => {
      applyStatus(next);
      toast.success("Default model updated");
    },
    onError: (error) =>
      toast.error(errorMessage(error, "Could not set the default model")),
  });

  if (status.isLoading || catalog.isLoading) {
    return (
      <p
        role="status"
        className="text-muted-foreground py-8 text-center text-sm"
      >
        Loading providers…
      </p>
    );
  }

  if (status.error || catalog.error || !status.data || !catalog.data) {
    return (
      <div className="border-destructive/40 bg-destructive/5 text-destructive flex items-start gap-3 rounded-lg border p-4 text-sm">
        <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" />
        <div className="space-y-1">
          <p className="font-medium">Provider settings are unavailable.</p>
          <p className="opacity-80">
            {errorMessage(
              status.error ?? catalog.error,
              "Only administrators can view or change provider credentials.",
            )}
          </p>
        </div>
      </div>
    );
  }

  const data = status.data;
  const specs = catalog.data;
  const configuredIds = new Set(data.providers.map((p) => p.provider_id));
  const allModels = data.providers.flatMap((provider) =>
    provider.models.map((model) => ({
      name: model.name,
      label: `${model.label ?? model.id} (${provider.label})`,
    })),
  );

  return (
    <div className="space-y-10">
      <SettingsSection
        title="Model providers"
        description="Add an API key here and its models become available immediately — no environment variables, no redeploy."
      >
        <StatusSummary status={data} />

        <div className="mt-4 space-y-3">
          {data.providers.length === 0 && (
            <p className="text-muted-foreground rounded-lg border border-dashed p-6 text-center text-sm">
              No model provider is configured yet. Add one below to start
              chatting.
            </p>
          )}
          {data.providers.map((provider) => {
            const spec = specs.llm.find((s) => s.id === provider.provider_id);
            return editingProvider === provider.provider_id && spec ? (
              <ProviderForm
                key={provider.provider_id}
                spec={spec}
                existing={provider}
                onCancel={() => setEditingProvider(null)}
                onSaved={applyStatus}
              />
            ) : (
              <ConfiguredProviderCard
                key={provider.provider_id}
                provider={provider}
                onEdit={() => setEditingProvider(provider.provider_id)}
                onRemove={() => removeProvider.mutate(provider.provider_id)}
                removing={
                  removeProvider.isPending &&
                  removeProvider.variables === provider.provider_id
                }
              />
            );
          })}
        </div>

        <AddProviderPicker
          specs={specs.llm}
          configuredIds={configuredIds}
          selected={addingProvider}
          onSelect={setAddingProvider}
          onSaved={applyStatus}
        />
      </SettingsSection>

      {allModels.length > 0 && (
        <SettingsSection
          title="Default model"
          description="The model new conversations start with."
        >
          <Select
            value={data.default_model ?? undefined}
            onValueChange={(value) => chooseDefaultModel.mutate(value)}
          >
            <SelectTrigger className="w-[360px]">
              <SelectValue placeholder="Pick a model" />
            </SelectTrigger>
            <SelectContent>
              {allModels.map((model) => (
                <SelectItem key={model.name} value={model.name}>
                  {model.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </SettingsSection>
      )}

      <ToolProviderSection
        slot="search"
        title="Web search"
        description="DeerFlow searches with DuckDuckGo out of the box. Swap in a keyed provider for better results."
        specs={specs.search}
        configured={data.search}
        onSaved={applyStatus}
      />

      <ToolProviderSection
        slot="fetch"
        title="Web page fetch"
        description="How the agent reads a page it found. The default needs no key."
        specs={specs.fetch}
        configured={data.fetch}
        onSaved={applyStatus}
      />
    </div>
  );
}

function StatusSummary({ status }: { status: QuickstartStatus }) {
  return (
    <div className="text-muted-foreground bg-muted/30 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border px-4 py-3 text-xs">
      <span>
        <strong className="text-foreground">{status.model_count}</strong> model
        {status.model_count === 1 ? "" : "s"} available
      </span>
      <span>
        Stored in{" "}
        <strong className="text-foreground">
          {status.settings_backend === "database"
            ? "the database"
            : "a local file"}
        </strong>
      </span>
      <span>
        {status.credentials_encrypted
          ? "Keys encrypted at rest"
          : "Keys stored unencrypted — set DEER_FLOW_QUICKSTART_SECRET"}
      </span>
      {!status.managed_config && (
        <span className="text-amber-600 dark:text-amber-500">
          config.yaml is hand-managed; changes here are stored but not applied
        </span>
      )}
    </div>
  );
}

function ConfiguredProviderCard({
  provider,
  onEdit,
  onRemove,
  removing,
}: {
  provider: QuickstartConfiguredProvider;
  onEdit: () => void;
  onRemove: () => void;
  removing: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border p-4">
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{provider.label}</span>
          {!provider.known_provider && (
            <Badge variant="destructive">Unknown provider</Badge>
          )}
          {provider.has_api_key && (
            <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
              <KeyRoundIcon className="size-3" />
              {provider.api_key_masked}
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {provider.models.map((model) => (
            <Badge
              key={model.name}
              variant="secondary"
              className="font-mono text-[11px]"
            >
              {model.id}
            </Badge>
          ))}
        </div>
        {provider.base_url && (
          <p className="text-muted-foreground truncate font-mono text-xs">
            {provider.base_url}
          </p>
        )}
      </div>
      <div className="flex shrink-0 gap-2">
        <Button variant="outline" size="sm" onClick={onEdit}>
          Edit
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onRemove}
          disabled={removing}
          aria-label={`Remove ${provider.label}`}
        >
          {removing ? (
            <Loader2Icon className="size-4 animate-spin" />
          ) : (
            <Trash2Icon className="size-4" />
          )}
        </Button>
      </div>
    </div>
  );
}

function AddProviderPicker({
  specs,
  configuredIds,
  selected,
  onSelect,
  onSaved,
}: {
  specs: QuickstartLLMProviderSpec[];
  configuredIds: Set<string>;
  selected: string | null;
  onSelect: (id: string | null) => void;
  onSaved: (status: QuickstartStatus) => void;
}) {
  const [filter, setFilter] = useState("");

  const available = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return specs.filter((spec) => {
      if (configuredIds.has(spec.id)) return false;
      if (!needle) return true;
      return (
        spec.label.toLowerCase().includes(needle) ||
        spec.description.toLowerCase().includes(needle) ||
        spec.tags.some((tag) => tag.includes(needle)) ||
        spec.presets.some((preset) => preset.id.toLowerCase().includes(needle))
      );
    });
  }, [specs, configuredIds, filter]);

  const selectedSpec = specs.find((spec) => spec.id === selected) ?? null;

  if (selectedSpec) {
    return (
      <div className="mt-4">
        <ProviderForm
          spec={selectedSpec}
          existing={null}
          onCancel={() => onSelect(null)}
          onSaved={onSaved}
        />
      </div>
    );
  }

  return (
    <div className="mt-6 space-y-3">
      <div className="relative">
        <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
        <Input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Search providers — OpenAI, Anthropic, OpenRouter, Ollama…"
          className="pl-9"
          aria-label="Search providers"
        />
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {available.map((spec) => (
          <button
            key={spec.id}
            type="button"
            onClick={() => onSelect(spec.id)}
            className="hover:border-primary hover:bg-accent/40 flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors"
          >
            <span className="flex flex-wrap items-center gap-1.5">
              <PlusIcon className="size-3.5" />
              <span className="text-sm font-medium">{spec.label}</span>
              {spec.tags.map((tag) => (
                <Badge key={tag} variant="outline" className="text-[10px]">
                  {tag}
                </Badge>
              ))}
            </span>
            <span className="text-muted-foreground text-xs">
              {spec.description}
            </span>
          </button>
        ))}
        {available.length === 0 && (
          <p className="text-muted-foreground col-span-full py-4 text-center text-sm">
            No provider matches “{filter}”.
          </p>
        )}
      </div>
    </div>
  );
}

function ProviderForm({
  spec,
  existing,
  onCancel,
  onSaved,
}: {
  spec: QuickstartLLMProviderSpec;
  existing: QuickstartConfiguredProvider | null;
  onCancel: () => void;
  onSaved: (status: QuickstartStatus) => void;
}) {
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(
    existing?.base_url ?? spec.default_base_url ?? "",
  );
  const [customModel, setCustomModel] = useState("");
  const [choices, setChoices] = useState<ModelChoice[]>(() => {
    const presets = spec.presets.map(presetToChoice);
    if (!existing) return presets;
    // Keep every model the operator already picked, even one that is no longer
    // a preset, so editing a provider never silently drops a model.
    const extra: ModelChoice[] = existing.models
      .filter((model) => !presets.some((preset) => preset.id === model.id))
      .map((model) => ({
        id: model.id,
        label: model.label ?? model.id,
        context_window: model.context_window,
        max_tokens: model.max_tokens,
        supports_vision: model.supports_vision,
        supports_thinking: model.supports_thinking,
        source: "custom",
      }));
    return [...presets, ...extra];
  });
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(existing?.models.map((model) => model.id) ?? []),
  );

  const hasStoredKey = Boolean(existing?.has_api_key);
  const effectiveKey = apiKey.trim() || null;
  const keyMissing = spec.requires_api_key && !effectiveKey && !hasStoredKey;
  const baseUrlMissing =
    spec.requires_base_url && !baseUrl.trim() && !spec.default_base_url;

  const toggle = (id: string) =>
    setSelectedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const discover = useMutation({
    mutationFn: () =>
      discoverProviderModels(spec.id, {
        api_key: effectiveKey,
        base_url: baseUrl.trim() || null,
      }),
    onSuccess: (result) => {
      setChoices((previous) => {
        const known = new Set(previous.map((choice) => choice.id));
        const discovered: ModelChoice[] = result.models
          .filter((model) => !known.has(model.id))
          .map((model) => ({
            id: model.id,
            label: model.label,
            context_window: null,
            max_tokens: null,
            supports_vision: false,
            supports_thinking: false,
            source: "discovered",
          }));
        return [...previous, ...discovered];
      });
      toast.success(`${result.models.length} model(s) found`);
    },
    onError: (error) =>
      toast.error(errorMessage(error, "Could not list the provider's models")),
  });

  const verify = useMutation({
    mutationFn: () =>
      verifyProvider(spec.id, {
        api_key: effectiveKey,
        base_url: baseUrl.trim() || null,
      }),
    onSuccess: (result) =>
      result.ok ? toast.success(result.detail) : toast.error(result.detail),
    onError: (error) =>
      toast.error(errorMessage(error, "Could not check the credential")),
  });

  const save = useMutation({
    mutationFn: () => {
      const models: QuickstartModelInput[] = choices
        .filter((choice) => selectedIds.has(choice.id))
        .map((choice) => ({
          id: choice.id,
          label: choice.label,
          context_window: choice.context_window,
          max_tokens: choice.max_tokens,
          supports_vision: choice.supports_vision,
          supports_thinking: choice.supports_thinking,
        }));
      return saveLLMProvider(spec.id, {
        api_key: effectiveKey,
        base_url: baseUrl.trim() || null,
        models,
      });
    },
    onSuccess: (next) => {
      onSaved(next);
      toast.success(`${spec.label} saved`);
    },
    onError: (error) =>
      toast.error(errorMessage(error, "Could not save the provider")),
  });

  const addCustomModel = () => {
    const id = customModel.trim();
    if (!id) return;
    setChoices((previous) =>
      previous.some((choice) => choice.id === id)
        ? previous
        : [
            ...previous,
            {
              id,
              label: id,
              context_window: null,
              max_tokens: null,
              supports_vision: false,
              supports_thinking: false,
              source: "custom",
            },
          ],
    );
    setSelectedIds((previous) => new Set(previous).add(id));
    setCustomModel("");
  };

  return (
    <div className="space-y-4 rounded-lg border p-4">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{spec.label}</span>
          {spec.signup_url && (
            <a
              href={spec.signup_url}
              target="_blank"
              rel="noreferrer"
              className="text-primary inline-flex items-center gap-1 text-xs hover:underline"
            >
              Get an API key <ExternalLinkIcon className="size-3" />
            </a>
          )}
        </div>
        <p className="text-muted-foreground text-xs">{spec.description}</p>
        {spec.requires_extra && (
          <p className="text-xs text-amber-600 dark:text-amber-500">
            Needs the <code>{spec.requires_extra}</code> extra in the backend
            image (rebuild with UV_EXTRAS={spec.requires_extra}).
          </p>
        )}
      </div>

      {(spec.requires_api_key || spec.presets.length > 0) && (
        <label className="block space-y-1.5">
          <span className="text-sm font-medium">
            API key{spec.requires_api_key ? "" : " (optional)"}
          </span>
          <Input
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={
              hasStoredKey
                ? `Stored: ${existing?.api_key_masked} — leave blank to keep it`
                : "Paste the key"
            }
          />
        </label>
      )}

      {spec.base_url_field && (
        <label className="block space-y-1.5">
          <span className="text-sm font-medium">
            Base URL{spec.requires_base_url ? "" : " (optional)"}
          </span>
          <Input
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            placeholder={spec.default_base_url ?? "https://…/v1"}
            className="font-mono text-xs"
          />
        </label>
      )}

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm font-medium">Models</span>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => verify.mutate()}
              disabled={verify.isPending || keyMissing || baseUrlMissing}
            >
              {verify.isPending ? (
                <Loader2Icon className="size-3.5 animate-spin" />
              ) : (
                <CheckIcon className="size-3.5" />
              )}
              Test key
            </Button>
            {spec.supports_discovery && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => discover.mutate()}
                disabled={discover.isPending || keyMissing || baseUrlMissing}
              >
                {discover.isPending ? (
                  <Loader2Icon className="size-3.5 animate-spin" />
                ) : (
                  <RefreshCwIcon className="size-3.5" />
                )}
                Load available models
              </Button>
            )}
          </div>
        </div>

        <div className="max-h-64 space-y-1 overflow-y-auto rounded-md border p-2">
          {choices.map((choice) => {
            const checked = selectedIds.has(choice.id);
            return (
              <button
                key={choice.id}
                type="button"
                onClick={() => toggle(choice.id)}
                aria-pressed={checked}
                className={cn(
                  "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors",
                  checked ? "bg-primary/10" : "hover:bg-accent/50",
                )}
              >
                <span
                  className={cn(
                    "flex size-4 shrink-0 items-center justify-center rounded border",
                    checked &&
                      "bg-primary border-primary text-primary-foreground",
                  )}
                >
                  {checked && <CheckIcon className="size-3" />}
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-xs">
                  {choice.id}
                </span>
                {choice.supports_thinking && (
                  <Badge variant="outline" className="text-[10px]">
                    thinking
                  </Badge>
                )}
                {choice.supports_vision && (
                  <Badge variant="outline" className="text-[10px]">
                    vision
                  </Badge>
                )}
              </button>
            );
          })}
          {choices.length === 0 && (
            <p className="text-muted-foreground px-2 py-3 text-xs">
              No presets for this provider. Load the available models or type an
              id below.
            </p>
          )}
        </div>

        <div className="flex gap-2">
          <Input
            value={customModel}
            onChange={(event) => setCustomModel(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addCustomModel();
              }
            }}
            placeholder="Add a model id by hand"
            className="font-mono text-xs"
          />
          <Button variant="outline" size="sm" onClick={addCustomModel}>
            Add
          </Button>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 border-t pt-3">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          size="sm"
          onClick={() => save.mutate()}
          disabled={
            save.isPending ||
            keyMissing ||
            baseUrlMissing ||
            selectedIds.size === 0
          }
        >
          {save.isPending && <Loader2Icon className="size-3.5 animate-spin" />}
          Save provider
        </Button>
      </div>
    </div>
  );
}

function ToolProviderSection({
  slot,
  title,
  description,
  specs,
  configured,
  onSaved,
}: {
  slot: "search" | "fetch";
  title: string;
  description: string;
  specs: QuickstartToolProviderSpec[];
  configured: QuickstartStatus["search"];
  onSaved: (status: QuickstartStatus) => void;
}) {
  const defaultSpec =
    specs.find((spec) => spec.tags.includes("default")) ?? specs[0];
  const [providerId, setProviderId] = useState(
    configured?.provider_id ?? defaultSpec?.id ?? "",
  );
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(configured?.base_url ?? "");

  const spec = specs.find((candidate) => candidate.id === providerId);
  const isConfigured = configured?.provider_id === providerId;
  const keyMissing =
    Boolean(spec?.requires_api_key) &&
    !apiKey.trim() &&
    !(isConfigured && configured?.has_api_key);

  const save = useMutation({
    mutationFn: () =>
      saveToolProvider(slot, {
        provider_id: providerId,
        api_key: apiKey.trim() || null,
        base_url: baseUrl.trim() || null,
      }),
    onSuccess: (next) => {
      setApiKey("");
      onSaved(next);
      toast.success(`${title} provider saved`);
    },
    onError: (error) =>
      toast.error(errorMessage(error, "Could not save the provider")),
  });

  const reset = useMutation({
    mutationFn: () => resetToolProvider(slot),
    onSuccess: (next) => {
      setApiKey("");
      onSaved(next);
      toast.success(`${title} reset to the default provider`);
    },
    onError: (error) =>
      toast.error(errorMessage(error, "Could not reset the provider")),
  });

  return (
    <SettingsSection title={title} description={description}>
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={providerId} onValueChange={setProviderId}>
            <SelectTrigger className="w-[280px]">
              <SelectValue placeholder="Pick a provider" />
            </SelectTrigger>
            <SelectContent>
              {specs.map((candidate) => (
                <SelectItem key={candidate.id} value={candidate.id}>
                  {candidate.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {configured && (
            <span className="text-muted-foreground text-xs">
              Currently: {configured.label}
              {configured.has_api_key ? ` (${configured.api_key_masked})` : ""}
            </span>
          )}
        </div>

        {spec && (
          <p className="text-muted-foreground text-xs">{spec.description}</p>
        )}

        {spec?.requires_api_key && (
          <div className="flex flex-wrap items-end gap-2">
            <label className="min-w-[260px] flex-1 space-y-1.5">
              <span className="text-sm font-medium">API key</span>
              <Input
                type="password"
                autoComplete="off"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={
                  isConfigured && configured?.has_api_key
                    ? `Stored: ${configured.api_key_masked} — leave blank to keep it`
                    : "Paste the key"
                }
              />
            </label>
            {spec.signup_url && (
              <a
                href={spec.signup_url}
                target="_blank"
                rel="noreferrer"
                className="text-primary inline-flex items-center gap-1 pb-2.5 text-xs hover:underline"
              >
                Get a key <ExternalLinkIcon className="size-3" />
              </a>
            )}
          </div>
        )}

        {spec?.base_url_field && (
          <label className="block space-y-1.5">
            <span className="text-sm font-medium">
              URL{spec.requires_base_url ? "" : " (optional)"}
            </span>
            <Input
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder={spec.default_base_url ?? ""}
              className="font-mono text-xs"
            />
          </label>
        )}

        <div className="flex gap-2">
          <Button
            size="sm"
            onClick={() => save.mutate()}
            disabled={save.isPending || !providerId || keyMissing}
          >
            {save.isPending && (
              <Loader2Icon className="size-3.5 animate-spin" />
            )}
            Use this provider
          </Button>
          {configured && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => reset.mutate()}
              disabled={reset.isPending}
            >
              Reset to default
            </Button>
          )}
        </div>
      </div>
    </SettingsSection>
  );
}
