import { act, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { setLanguage } from "../../i18n";
import { ProfileCard } from "./ProfileCard";
import type { Me } from "./useMe";

const officer: Me = {
  id: "1",
  sub: "sub-1",
  username: "officer",
  name: "Compliance Officer",
  email: "officer@daleel.local",
  locale: "en",
  tenant: "acme",
  roles: ["approver", "editor"],
};

afterEach(() => {
  act(() => {
    setLanguage("en");
  });
});

describe("ProfileCard", () => {
  it("shows the user's name, tenant and roles", () => {
    render(<ProfileCard me={officer} />);
    expect(screen.getByRole("heading", { name: "Compliance Officer" })).toBeInTheDocument();
    expect(screen.getByText("acme")).toBeInTheDocument();
    const roles = within(screen.getByRole("list", { name: "Roles" })).getAllByRole("listitem");
    expect(roles.map((r) => r.textContent)).toEqual(["Approver", "Editor"]);
  });

  it("explains what to do with no roles", () => {
    render(<ProfileCard me={{ ...officer, roles: [] }} />);
    expect(screen.getByText(/Ask an administrator/)).toBeInTheDocument();
  });

  it("renders in Arabic", () => {
    act(() => {
      setLanguage("ar");
    });
    render(<ProfileCard me={officer} />);
    expect(screen.getByText("الأدوار")).toBeInTheDocument();
    expect(screen.getByText("مُعتمِد")).toBeInTheDocument();
  });
});
