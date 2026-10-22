import "@testing-library/jest-dom/vitest";
import "../i18n";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom has no layout, so it doesn't implement scrolling.
Element.prototype.scrollIntoView = () => undefined;

afterEach(() => {
  cleanup();
});
