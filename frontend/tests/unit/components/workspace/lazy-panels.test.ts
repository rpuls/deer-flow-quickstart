import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

const FRONTEND_ROOT = path.resolve(__dirname, "../../../..");
const read = (relativePath: string) =>
  readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");

describe("interaction-only bundle boundaries", () => {
  it("does not import the settings dialog until its store is open", () => {
    const host = read(
      "src/components/workspace/settings/settings-dialog-host.tsx",
    );
    expect(host).toContain("dynamic(");
    expect(host).toContain("if (!open)");
    expect(host).not.toContain(
      'import { SettingsDialog } from "./settings-dialog"',
    );
  });

  it("loads each settings page from its active section", () => {
    const dialog = read(
      "src/components/workspace/settings/settings-dialog.tsx",
    );
    // Assert the boundary itself rather than a page count: every settings page
    // the dialog renders must resolve to a dynamic() import, and every dynamic
    // import must actually be rendered. A hard-coded total has to be edited
    // whenever a section is added, which fails the build for a reason that has
    // nothing to do with the bundle boundary this test exists to protect.
    const lazy = [
      ...dialog.matchAll(/const (\w+SettingsPage) = dynamic\(/g),
    ].map((match) => match[1]);
    const rendered = [...dialog.matchAll(/<(\w+SettingsPage)[\s/>]/g)].map(
      (match) => match[1],
    );
    expect(lazy.length).toBeGreaterThanOrEqual(10);
    expect([...new Set(rendered)].sort()).toEqual([...new Set(lazy)].sort());
    expect(dialog).not.toMatch(
      /import \{ \w+SettingsPage \} from "@\/components\/workspace\/settings\//,
    );
  });

  it("keeps right-panel implementations behind dynamic imports", () => {
    const chatBox = read("src/components/workspace/chats/chat-box.tsx");
    expect(chatBox).toContain('import dynamic from "next/dynamic"');
    expect(chatBox).not.toMatch(
      /import \{ (?:ArtifactFileDetail|ArtifactFileList|BrowserViewPanel|SidecarPanel)/,
    );
    expect(chatBox.match(/dynamic\(/g)?.length).toBeGreaterThanOrEqual(4);
  });
});
