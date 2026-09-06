// Shapes returned by the Gateway's /api/quickstart routes. They mirror
// backend/app/quickstart/router.py; keep the two in step.

export type QuickstartModelPreset = {
  id: string;
  label: string;
  context_window: number | null;
  max_tokens: number | null;
  supports_vision: boolean;
  supports_thinking: boolean;
};

export type QuickstartLLMProviderSpec = {
  id: string;
  label: string;
  description: string;
  api_key_field: string;
  base_url_field: string | null;
  default_base_url: string | null;
  requires_api_key: boolean;
  requires_base_url: boolean;
  supports_discovery: boolean;
  supports_thinking: boolean;
  requires_extra: string | null;
  signup_url: string | null;
  docs_url: string | null;
  tags: string[];
  presets: QuickstartModelPreset[];
};

export type QuickstartToolProviderSpec = {
  id: string;
  label: string;
  description: string;
  tool_name: string;
  requires_api_key: boolean;
  base_url_field: string | null;
  default_base_url: string | null;
  requires_base_url: boolean;
  signup_url: string | null;
  tags: string[];
};

export type QuickstartCatalog = {
  llm: QuickstartLLMProviderSpec[];
  search: QuickstartToolProviderSpec[];
  fetch: QuickstartToolProviderSpec[];
};

export type QuickstartConfiguredModel = {
  id: string;
  label: string | null;
  /** `models[].name` in config.yaml — what the chat UI selects on. */
  name: string;
  context_window: number | null;
  max_tokens: number | null;
  supports_vision: boolean;
  supports_thinking: boolean;
};

export type QuickstartConfiguredProvider = {
  provider_id: string;
  label: string;
  enabled: boolean;
  base_url: string | null;
  api_key_masked: string | null;
  has_api_key: boolean;
  known_provider: boolean;
  models: QuickstartConfiguredModel[];
};

export type QuickstartConfiguredTool = {
  provider_id: string;
  label: string;
  base_url: string | null;
  api_key_masked: string | null;
  has_api_key: boolean;
  known_provider: boolean;
};

export type QuickstartStatus = {
  managed_config: boolean;
  settings_backend: "database" | "file";
  credentials_encrypted: boolean;
  model_count: number;
  needs_onboarding: boolean;
  default_model: string | null;
  providers: QuickstartConfiguredProvider[];
  search: QuickstartConfiguredTool | null;
  fetch: QuickstartConfiguredTool | null;
};

export type QuickstartDiscoveredModel = {
  id: string;
  label: string;
};

export type QuickstartVerifyResult = {
  ok: boolean;
  verified: boolean;
  detail: string;
};

export type QuickstartModelInput = {
  id: string;
  label?: string | null;
  context_window?: number | null;
  max_tokens?: number | null;
  supports_vision?: boolean;
  supports_thinking?: boolean;
};
