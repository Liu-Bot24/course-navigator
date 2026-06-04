import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const styles = readFileSync("frontend/src/styles.css", "utf8");

function cssBlock(selector: string): string {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`).exec(styles);
  return match?.[1] ?? "";
}

describe("course library styles", () => {
  it("keeps category rows compact and only reveals actions on hover", () => {
    expect(cssBlock(".library-list")).toContain("gap: 4px");
    expect(cssBlock(".library-collection-group-head")).toContain("padding: 3px 6px 3px 0");
    expect(cssBlock(".library-collection-group-actions")).toContain("width: 66px");
    expect(cssBlock(".library-collection-group-delete,\n.library-collection-group-move")).toContain("width: 20px");
    expect(cssBlock(".library-collection-group-delete,\n.library-collection-group-move")).toContain("height: 20px");
    expect(cssBlock(".library-collection-group-spacer")).toContain("width: 20px");
    expect(cssBlock(".library-collection-group-spacer")).toContain("height: 20px");
    expect(styles).not.toContain(".library-collection-group-head:focus-within .library-collection-group-actions");
  });
});
