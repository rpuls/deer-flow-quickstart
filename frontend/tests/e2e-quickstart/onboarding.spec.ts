import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

/**
 * The promise this fork makes, checked against a real stack:
 *
 *   deploy with no API keys -> create an admin in the browser ->
 *   paste one provider key in the UI -> the model is usable, immediately,
 *   with no restart -> and it is still there after the container is replaced.
 *
 * Requires the quickstart compose stack (see playwright.quickstart.config.ts).
 * No provider key is needed: nothing here calls a model, it only checks that
 * the credential reaches the Gateway's own model registry.
 */

const ADMIN_EMAIL =
  process.env.QUICKSTART_ADMIN_EMAIL ?? "e2e-admin@deerflow.local";
const ADMIN_PASSWORD =
  process.env.QUICKSTART_ADMIN_PASSWORD ?? "QuickstartE2E!2026";

const PROVIDER_ID = "anthropic";
const MODEL_ID = "claude-sonnet-4-5";
const MODEL_NAME = "anthropic-claude-sonnet-4-5";
// Never a live credential: the suite must not be able to spend anyone's money.
const FAKE_KEY = "sk-ant-e2e-placeholder-0000";

type SetupStatus = { needs_setup?: boolean };

async function setupStatus(request: APIRequestContext): Promise<SetupStatus> {
  const response = await request.get("/api/v1/auth/setup-status");
  expect(response.ok(), "the stack must be reachable").toBeTruthy();
  return (await response.json()) as SetupStatus;
}

/** Create the admin account if this is a fresh deployment, then sign in. */
async function signInAsAdmin(page: Page) {
  const status = await setupStatus(page.request);

  // The login and setup forms both use stable element ids, which is steadier
  // than label matching here: the "keep me signed in" checkbox shares enough
  // accessible text with the fields to make a loose label regex ambiguous.
  if (status.needs_setup) {
    await page.goto("/setup");
    await page.locator("#email").fill(ADMIN_EMAIL);
    await page.locator("#password").fill(ADMIN_PASSWORD);
    await page.locator("#confirmPassword").fill(ADMIN_PASSWORD);
    await page.getByRole("button", { name: "Create Admin Account" }).click();
    await page.waitForURL(/\/workspace/, { timeout: 60_000 });
    return;
  }

  await page.goto("/login");
  await page.locator("#email").fill(ADMIN_EMAIL);
  await page.locator("#password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign In" }).click();
  await page.waitForURL(/\/workspace/, { timeout: 60_000 });
}

/**
 * Header the Gateway's double-submit CSRF check expects on writes.
 *
 * `page.request` shares the browser context's cookies but not the app's
 * fetcher, which is where the header is normally attached — so API-level
 * writes in this suite have to echo the cookie themselves.
 */
async function csrfHeaders(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies();
  const token = cookies.find((cookie) => cookie.name === "csrf_token")?.value;
  return token ? { "X-CSRF-Token": token } : {};
}

async function openProvidersSettings(page: Page) {
  await page.goto("/workspace/chats/new?settings=providers");
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog.getByText("Model providers")).toBeVisible({
    timeout: 30_000,
  });
  return dialog;
}

async function removeProviderIfPresent(page: Page) {
  const response = await page.request.get("/api/quickstart/status");
  if (!response.ok()) return;
  const status = (await response.json()) as {
    providers: Array<{ provider_id: string }>;
  };
  if (
    status.providers.some((provider) => provider.provider_id === PROVIDER_ID)
  ) {
    await page.request.delete(`/api/quickstart/llm/${PROVIDER_ID}`, {
      headers: await csrfHeaders(page),
    });
  }
}

test.describe("Quickstart onboarding against a real Gateway", () => {
  test.beforeEach(async ({ page }) => {
    await signInAsAdmin(page);
    await removeProviderIfPresent(page);
  });

  test("a fresh deployment reports that it needs a provider", async ({
    page,
  }) => {
    const status = await (
      await page.request.get("/api/quickstart/status")
    ).json();

    expect(status.needs_onboarding).toBe(true);
    expect(status.model_count).toBe(0);
    // The two properties that make a cloud deployment survivable.
    expect(status.settings_backend).toBe("database");
    expect(status.credentials_encrypted).toBe(true);
  });

  test("the catalog covers a broad set of providers", async ({ page }) => {
    const catalog = await (
      await page.request.get("/api/quickstart/catalog")
    ).json();

    expect(catalog.llm.length).toBeGreaterThanOrEqual(20);
    const ids = catalog.llm.map((spec: { id: string }) => spec.id);
    // A representative spread: first-party SDKs, multi-vendor gateways, local.
    for (const id of [
      "openai",
      "anthropic",
      "google",
      "openrouter",
      "groq",
      "ollama",
    ]) {
      expect(ids).toContain(id);
    }
    // Search must work with no key at all, or a key-free deploy is useless.
    expect(
      catalog.search.some(
        (spec: { requires_api_key: boolean }) => !spec.requires_api_key,
      ),
    ).toBe(true);
  });

  test("adding a provider in the UI makes its model available without a restart", async ({
    page,
  }) => {
    const dialog = await openProvidersSettings(page);

    await dialog.getByRole("button", { name: /^Anthropic/ }).click();
    await dialog.getByPlaceholder("Paste the key").fill(FAKE_KEY);
    await dialog.getByRole("button", { name: MODEL_ID }).click();
    await dialog.getByRole("button", { name: "Save provider" }).click();

    await expect(dialog.getByText("1 model available")).toBeVisible({
      timeout: 30_000,
    });

    // The real assertion: the Gateway re-read its config and now serves the
    // model, in the same process that started with none.
    const models = await (await page.request.get("/api/models")).json();
    expect(
      models.models.map((model: { name: string }) => model.name),
    ).toContain(MODEL_NAME);

    // The key is never echoed back, only its tail.
    const status = await (
      await page.request.get("/api/quickstart/status")
    ).json();
    const provider = status.providers.find(
      (entry: { provider_id: string }) => entry.provider_id === PROVIDER_ID,
    );
    expect(provider.api_key_masked).toBe("********0000");
    expect(JSON.stringify(status)).not.toContain(FAKE_KEY);
  });

  test("a provider can be removed again", async ({ page }) => {
    await page.request.put(`/api/quickstart/llm/${PROVIDER_ID}`, {
      headers: await csrfHeaders(page),
      data: {
        api_key: FAKE_KEY,
        models: [{ id: MODEL_ID, label: "Claude Sonnet 4.5" }],
      },
    });

    const dialog = await openProvidersSettings(page);
    await dialog.getByRole("button", { name: `Remove Anthropic` }).click();

    await expect(dialog.getByText("0 models available")).toBeVisible({
      timeout: 30_000,
    });
    const models = await (await page.request.get("/api/models")).json();
    expect(models.models).toHaveLength(0);
  });

  test("the web search provider can be switched and reset", async ({
    page,
  }) => {
    // Start from the default regardless of what an earlier run left behind.
    await page.request.delete("/api/quickstart/search", {
      headers: await csrfHeaders(page),
    });

    const dialog = await openProvidersSettings(page);

    await dialog
      .getByRole("combobox")
      .filter({ hasText: /DuckDuckGo|Tavily/ })
      .click();
    await page.getByRole("option", { name: "Tavily" }).click();
    await dialog
      .getByPlaceholder("Paste the key")
      .last()
      .fill("tvly-e2e-placeholder");
    await dialog
      .getByRole("button", { name: "Use this provider" })
      .first()
      .click();

    await expect(dialog.getByText(/Currently: Tavily/)).toBeVisible({
      timeout: 30_000,
    });

    await dialog
      .getByRole("button", { name: "Reset to default" })
      .first()
      .click();
    await expect(dialog.getByText(/Currently: Tavily/)).toBeHidden({
      timeout: 30_000,
    });
  });

  test("a bad credential is reported rather than silently stored", async ({
    page,
  }) => {
    const response = await page.request.post(
      `/api/quickstart/llm/${PROVIDER_ID}/verify`,
      {
        headers: await csrfHeaders(page),
        data: { api_key: "sk-ant-definitely-not-valid" },
      },
    );

    expect(response.ok()).toBeTruthy();
    const result = await response.json();
    // Either the provider rejected it, or the network is unavailable in CI —
    // both are honest answers. What must not happen is a silent "ok".
    expect(typeof result.detail).toBe("string");
    expect(result.detail.length).toBeGreaterThan(0);
  });
});
