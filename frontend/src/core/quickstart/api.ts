import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  QuickstartCatalog,
  QuickstartDiscoveredModel,
  QuickstartModelInput,
  QuickstartStatus,
  QuickstartVerifyResult,
} from "./types";

function url(path: string) {
  return `${getBackendBaseURL()}/api/quickstart${path}`;
}

async function request<T>(
  path: string,
  init?: RequestInit & { failureMessage?: string },
): Promise<T> {
  const { failureMessage, ...requestInit } = init ?? {};
  const response = await fetch(url(path), {
    ...requestInit,
    headers: {
      ...(requestInit.body ? { "Content-Type": "application/json" } : {}),
      ...requestInit.headers,
    },
  });
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      failureMessage ??
        `Request failed: ${response.status} ${response.statusText}`.trim(),
    );
  }
  return (await response.json()) as T;
}

export function loadQuickstartCatalog(): Promise<QuickstartCatalog> {
  return request<QuickstartCatalog>("/catalog", {
    failureMessage: "Could not load the provider catalog",
  });
}

export function loadQuickstartStatus(): Promise<QuickstartStatus> {
  return request<QuickstartStatus>("/status", {
    failureMessage: "Could not load the provider configuration",
  });
}

export function saveLLMProvider(
  providerId: string,
  payload: {
    api_key?: string | null;
    base_url?: string | null;
    models: QuickstartModelInput[];
    enabled?: boolean;
  },
): Promise<QuickstartStatus> {
  return request<QuickstartStatus>(`/llm/${encodeURIComponent(providerId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
    failureMessage: "Could not save the provider",
  });
}

export function deleteLLMProvider(
  providerId: string,
): Promise<QuickstartStatus> {
  return request<QuickstartStatus>(`/llm/${encodeURIComponent(providerId)}`, {
    method: "DELETE",
    failureMessage: "Could not remove the provider",
  });
}

export function discoverProviderModels(
  providerId: string,
  payload: { api_key?: string | null; base_url?: string | null },
): Promise<{ provider_id: string; models: QuickstartDiscoveredModel[] }> {
  return request(`/llm/${encodeURIComponent(providerId)}/discover`, {
    method: "POST",
    body: JSON.stringify(payload),
    failureMessage: "Could not list the provider's models",
  });
}

export function verifyProvider(
  providerId: string,
  payload: { api_key?: string | null; base_url?: string | null },
): Promise<QuickstartVerifyResult> {
  return request<QuickstartVerifyResult>(
    `/llm/${encodeURIComponent(providerId)}/verify`,
    {
      method: "POST",
      body: JSON.stringify(payload),
      failureMessage: "Could not check the credential",
    },
  );
}

export function setDefaultModel(
  modelName: string | null,
): Promise<QuickstartStatus> {
  return request<QuickstartStatus>("/default-model", {
    method: "PUT",
    body: JSON.stringify({ model_name: modelName }),
    failureMessage: "Could not set the default model",
  });
}

export function saveToolProvider(
  slot: "search" | "fetch",
  payload: {
    provider_id: string;
    api_key?: string | null;
    base_url?: string | null;
  },
): Promise<QuickstartStatus> {
  return request<QuickstartStatus>(`/${slot}`, {
    method: "PUT",
    body: JSON.stringify(payload),
    failureMessage: "Could not save the provider",
  });
}

export function resetToolProvider(
  slot: "search" | "fetch",
): Promise<QuickstartStatus> {
  return request<QuickstartStatus>(`/${slot}`, {
    method: "DELETE",
    failureMessage: "Could not reset the provider",
  });
}
