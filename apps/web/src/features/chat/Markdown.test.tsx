import * as Tooltip from "@radix-ui/react-tooltip";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Citation } from "../citations/types";
import { Markdown } from "./Markdown";

const citation: Citation = {
  n: 1,
  chunk_id: "c1",
  doc_id: "d1",
  title: "سياسة المشتريات",
  page: 1,
  bbox: null,
  bboxes: [],
  snippet: "العقود التي تتجاوز 500,000 درهم تعرض على لجنة المشتريات",
};

describe("Markdown citations", () => {
  it("turns known markers into chips and leaves unknown ones as text", async () => {
    const onCite = vi.fn();
    render(
      <Tooltip.Provider>
        <Markdown text="Committee approval is needed [1]. See also [4]." citations={[citation]} onCite={onCite} />
      </Tooltip.Provider>,
    );
    const chip = screen.getByRole("button", { name: "Source 1: سياسة المشتريات, page 1" });
    expect(screen.getByText(/See also \[4\]/)).toBeInTheDocument();
    await userEvent.click(chip);
    expect(onCite).toHaveBeenCalledWith(citation);
  });

  it("shows the snippet on focus", async () => {
    render(
      <Tooltip.Provider>
        <Markdown text="Yes [1]." citations={[citation]} onCite={vi.fn()} />
      </Tooltip.Provider>,
    );
    await userEvent.tab();
    expect((await screen.findAllByText(/لجنة المشتريات/)).length).toBeGreaterThan(0);
  });

  it("keeps markers as plain text without a handler", () => {
    render(<Markdown text="Plain [1]." />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("Plain [1].")).toBeInTheDocument();
  });
});
