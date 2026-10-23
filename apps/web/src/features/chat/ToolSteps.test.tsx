import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import i18n from "../../i18n";
import { ToolSteps } from "./ToolSteps";

const search = (passages: number, documents: number) => ({
  callId: "c1",
  tool: "search_documents",
  summary: "Found",
  ok: true,
  data: { passages, documents },
});

describe("ToolSteps", () => {
  afterEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("pluralizes each count on its own", () => {
    render(<ToolSteps steps={[search(6, 1)]} />);
    expect(screen.getByText(/Found 6 passages in 1 document$/)).toBeInTheDocument();
  });

  it("uses Arabic plural forms", async () => {
    await i18n.changeLanguage("ar");
    render(<ToolSteps steps={[search(6, 1), { ...search(2, 2), callId: "c2" }]} />);
    expect(screen.getByText(/عُثر على 6 مقاطع في مستند واحد$/)).toBeInTheDocument();
    expect(screen.getByText(/عُثر على مقطعين في مستندين$/)).toBeInTheDocument();
  });
});
