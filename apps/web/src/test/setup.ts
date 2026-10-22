import "@testing-library/jest-dom/vitest";
import "../i18n";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom has no layout, so it doesn't implement scrolling or resize observation.
Element.prototype.scrollIntoView = () => undefined;
// Typed as always present, but jsdom doesn't define it.
globalThis.ResizeObserver = class {
  observe() {
    return undefined;
  }
  unobserve() {
    return undefined;
  }
  disconnect() {
    return undefined;
  }
};

afterEach(() => {
  cleanup();
});
