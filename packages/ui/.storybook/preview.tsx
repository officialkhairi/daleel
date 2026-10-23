import "./preview.css";

import type { Preview } from "@storybook/react-vite";

const preview: Preview = {
  // Stories can set parameters.direction = "rtl" to render as Arabic layout does.
  decorators: [
    (Story, context) => (
      <div dir={context.parameters.direction === "rtl" ? "rtl" : "ltr"} lang={context.parameters.direction === "rtl" ? "ar" : "en"}>
        <Story />
      </div>
    ),
  ],
  parameters: {
    a11y: { test: "error" }, // fail a story on accessibility violations
  },
};
export default preview;
