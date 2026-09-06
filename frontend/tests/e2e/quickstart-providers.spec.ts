import { expect, test, type Page, type Route } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * Fast, backend-free coverage of the Providers settings page - the surface a
 * one-click deployment is onboarded through. The full-stack version of this
 * flow lives in tests/e2e-quickstart, which drives a real Gateway.
 */

type MockStatus = {
  managed_config: boolean;
  settings_backend: "database" | "file";
  credentials_encrypted: boolean;
  model_count: number;
  needs_onboarding: boolean;
  default_model: string | null;
  providers: Array<Record<string, unknown>>;
  search: Record<string, unknown> | null;
  fetch: Record<string, unknown> | null;
};

const EMPTY_STATUS: MockStatus = {
  managed_config: true,
  settings_backend: "database",
  credentials_encrypted: true,
  model_count: 0,
  needs_onboarding: true,
  default_model: null,
  providers: [],
  search: null,
  fetch: null,
};

const CONFIGURED_STATUS: MockStatus = {
  ...EMPTY_STATUS,
  model_count: 1,
  needs_onboarding: false,
  default_model: "anthropic-claude-sonnet-4-5",
  providers: [
    {
      provider_id: "anthropic",
      label: "Anthropic",
      enabled: true,
      base_url: null,
      api_key_masked: "********0000",
      has_api_key: true,
      known_provider: true,
      models: [
        {
          id: "claude-sonnet-4-5",
          label: "Claude Sonnet 4.5",
          name: "anthropic-claude-sonnet-4-5",
          context_window: 200000,
          max_tokens: 16000,
          supports_vision: true,
          supports_thinking: true,
        },
      ],
    },
  ],
};

const CATALOG = {
  llm: [
    {
      id: "anthropic",
      label: "Anthropic",
      description: "Claude models with extended thinking.",
      api_key_field: "api_key",
      base_url_field: "base_url",
      default_base_url: null,
      requires_api_key: true,
      requires_base_url: false,
      supports_discovery: true,
      supports_thinking: true,
      requires_extra: null,
      signup_url: "https://console.anthropic.com/settings/keys",
      docs_url: null,
      tags: ["popular"],
      presets: [
        {
          id: "claude-sonnet-4-5",
          label: "Claude Sonnet 4.5",
          context_window: 200000,
          max_tokens: 16000,
          supports_vision: true,
          supports_thinking: true,
        },
      ],
    },
    {
      id: "openrouter",
      label: "OpenRouter",
      description: "One key, hundreds of models from every major lab.",
      api_key_field: "api_key",
      base_url_field: "base_url",
      default_base_url: "https://openrouter.ai/api/v1",
      requires_api_key: true,
      requires_base_url: false,
      supports_discovery: true,
      supports_thinking: false,
      requires_extra: null,
      signup_url: "https://openrouter.ai/keys",
      docs_url: null,
      tags: ["popular", "gateway"],
      presets: [],
    },
  ],
  search: [
    {
      id: "ddg",
      label: "DuckDuckGo",
      description: "Default. Works with no API key at all.",
      tool_name: "web_search",
      requires_api_key: false,
      base_url_field: null,
      default_base_url: null,
      requires_base_url: false,
      signup_url: null,
      tags: ["free", "default"],
    },
    {
      id: "tavily",
      label: "Tavily",
      description: "Search built for agents. Free tier available.",
      tool_name: "web_search",
      requires_api_key: true,
      base_url_field: null,
      default_base_url: null,
      requires_base_url: false,
      signup_url: "https://app.tavily.com/home",
      tags: ["recommended", "free-tier"],
    },
  ],
  fetch: [
    {
      id: "jina_ai",
      label: "Jina AI Reader",
      description: "Default. Works with no API key.",
      tool_name: "web_fetch",
      requires_api_key: false,
      base_url_field: null,
      default_base_url: null,
      requires_base_url: false,
      signup_url: null,
      tags: ["free", "default"],
    },
  ],
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function mockQuickstartAPI(
  page: Page,
  options: {
    status?: MockStatus;
    onSaveProvider?: (providerId: string, payload: unknown) => void;
    discoverError?: { status: number; detail: string };
  } = {},
) {
  let status = options.status ?? EMPTY_STATUS;

  void page.route("**/api/quickstart/catalog", (route) => json(route, CATALOG));
  void page.route("**/api/quickstart/status", (route) => json(route, status));

  void page.route("**/api/quickstart/llm/*/verify", (route) => {
    // `verify` answers 200 with ok:false on a bad credential — the failure is
    // the provider's, not the request's, so the UI shows it as a message.
    if (options.discoverError) {
      return json(route, {
        ok: false,
        verified: true,
        detail: options.discoverError.detail,
      });
    }
    return json(route, {
      ok: true,
      verified: true,
      detail: "Reached Anthropic; 3 model(s) available.",
    });
  });

  void page.route("**/api/quickstart/llm/*/discover", (route) => {
    if (options.discoverError) {
      return json(
        route,
        { detail: options.discoverError.detail },
        options.discoverError.status,
      );
    }
    return json(route, {
      provider_id: "anthropic",
      models: [
        { id: "claude-opus-4-5", label: "Claude Opus 4.5" },
        { id: "claude-haiku-4-5", label: "Claude Haiku 4.5" },
      ],
    });
  });

  void page.route("**/api/quickstart/llm/*", (route) => {
    const method = route.request().method();
    if (method === "PUT") {
      const providerId =
        /\/llm\/([^/?]+)/.exec(route.request().url())?.[1] ?? "";
      options.onSaveProvider?.(providerId, route.request().postDataJSON());
      status = CONFIGURED_STATUS;
      return json(route, status);
    }
    if (method === "DELETE") {
      status = EMPTY_STATUS;
      return json(route, status);
    }
    return route.continue();
  });

  void page.route("**/api/quickstart/search", (route) => {
    status = {
      ...status,
      search: {
        provider_id: "tavily",
        label: "Tavily",
        base_url: null,
        api_key_masked: "********1234",
        has_api_key: true,
        known_provider: true,
      },
    };
    return json(route, status);
  });
}

async function openProvidersSettings(page: Page) {
  const sidebar = page.locator("[data-sidebar='sidebar']");
  await sidebar
    .getByRole("button", { name: /Settings and more/ })
    .click({ timeout: 15_000 });
  await page.getByRole("menuitem", { name: "Settings" }).click();
  await page.getByRole("button", { name: "Providers" }).click();
  return page.getByRole("dialog", { name: "Settings" });
}

test.describe("Quickstart provider onboarding", () => {
  test("an unconfigured deployment prompts for a provider", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    mockQuickstartAPI(page);

    await page.goto("/workspace/chats/new");

    await expect(
      page.getByText("No model provider is configured yet"),
    ).toBeVisible({ timeout: 15_000 });

    // The banner is the onboarding entry point: it must open the right page.
    await page.getByRole("button", { name: "Set up a provider" }).click();
    const dialog = page.getByRole("dialog", { name: "Settings" });
    await expect(dialog.getByText("Model providers")).toBeVisible();
  });

  test("a provider can be added from the catalog", async ({ page }) => {
    const saved: Array<{ providerId: string; payload: unknown }> = [];
    mockLangGraphAPI(page);
    mockQuickstartAPI(page, {
      onSaveProvider: (providerId, payload) =>
        saved.push({ providerId, payload }),
    });

    await page.goto("/workspace/chats/new");
    const dialog = await openProvidersSettings(page);

    await expect(dialog.getByText("0 models available")).toBeVisible();
    await dialog.getByRole("button", { name: /Anthropic/ }).click();

    await dialog.getByPlaceholder("Paste the key").fill("sk-ant-test-0000");
    await dialog.getByRole("button", { name: "claude-sonnet-4-5" }).click();
    await dialog.getByRole("button", { name: "Save provider" }).click();

    expect(saved).toHaveLength(1);
    expect(saved[0]?.providerId).toBe("anthropic");
    expect(saved[0]?.payload).toMatchObject({
      api_key: "sk-ant-test-0000",
      models: [{ id: "claude-sonnet-4-5", supports_thinking: true }],
    });
    await expect(dialog.getByText("********0000")).toBeVisible();
  });

  test("saving is blocked until a key and a model are supplied", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    mockQuickstartAPI(page);

    await page.goto("/workspace/chats/new");
    const dialog = await openProvidersSettings(page);
    await dialog.getByRole("button", { name: /Anthropic/ }).click();

    const save = dialog.getByRole("button", { name: "Save provider" });
    await expect(save).toBeDisabled();

    await dialog.getByPlaceholder("Paste the key").fill("sk-ant-test-0000");
    // A key alone is not enough — a provider with no model produces no config.
    await expect(save).toBeDisabled();

    await dialog.getByRole("button", { name: "claude-sonnet-4-5" }).click();
    await expect(save).toBeEnabled();
  });

  test("live discovery adds the models the provider actually serves", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    mockQuickstartAPI(page);

    await page.goto("/workspace/chats/new");
    const dialog = await openProvidersSettings(page);
    await dialog.getByRole("button", { name: /Anthropic/ }).click();
    await dialog.getByPlaceholder("Paste the key").fill("sk-ant-test-0000");

    await dialog.getByRole("button", { name: "Load available models" }).click();

    await expect(
      dialog.getByRole("button", { name: "claude-opus-4-5" }),
    ).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: "claude-haiku-4-5" }),
    ).toBeVisible();
  });

  test("a rejected key is reported instead of being saved", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    mockQuickstartAPI(page, {
      discoverError: {
        status: 400,
        detail: "Anthropic rejected the credential (HTTP 401).",
      },
    });

    await page.goto("/workspace/chats/new");
    const dialog = await openProvidersSettings(page);
    await dialog.getByRole("button", { name: /Anthropic/ }).click();
    await dialog.getByPlaceholder("Paste the key").fill("sk-ant-wrong");
    await dialog.getByRole("button", { name: "Test key" }).click();

    await expect(page.getByText(/rejected the credential/)).toBeVisible();
  });

  test("a model id can be typed in for a provider with no presets", async ({
    page,
  }) => {
    const saved: Array<{ providerId: string; payload: unknown }> = [];
    mockLangGraphAPI(page);
    mockQuickstartAPI(page, {
      onSaveProvider: (providerId, payload) =>
        saved.push({ providerId, payload }),
    });

    await page.goto("/workspace/chats/new");
    const dialog = await openProvidersSettings(page);
    await dialog.getByRole("button", { name: /OpenRouter/ }).click();
    await dialog.getByPlaceholder("Paste the key").fill("sk-or-test");
    await dialog
      .getByPlaceholder("Add a model id by hand")
      .fill("qwen/qwen3-max");
    await dialog.getByRole("button", { name: "Add", exact: true }).click();
    await dialog.getByRole("button", { name: "Save provider" }).click();

    expect(saved[0]?.payload).toMatchObject({
      models: [{ id: "qwen/qwen3-max" }],
    });
  });

  test("the search provider can be switched away from the default", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    mockQuickstartAPI(page, { status: CONFIGURED_STATUS });

    await page.goto("/workspace/chats/new");
    const dialog = await openProvidersSettings(page);

    await dialog
      .getByRole("combobox")
      .filter({ hasText: "DuckDuckGo" })
      .click();
    await page.getByRole("option", { name: "Tavily" }).click();
    await dialog.getByPlaceholder("Paste the key").fill("tvly-test-1234");
    await dialog
      .getByRole("button", { name: "Use this provider" })
      .first()
      .click();

    await expect(dialog.getByText(/Currently: Tavily/)).toBeVisible();
  });
});
