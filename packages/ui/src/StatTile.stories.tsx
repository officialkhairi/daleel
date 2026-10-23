import type { Meta, StoryObj } from "@storybook/react-vite";

import { StatTile } from "./StatTile";

const meta: Meta<typeof StatTile> = {
  title: "UI/StatTile",
  component: StatTile,
  decorators: [(Story) => <dl className="max-w-xs"><Story /></dl>],
  args: { label: "Questions asked", value: "1,284", hint: "Last 30 days" },
};
export default meta;
export const Default: StoryObj<typeof StatTile> = {};
export const Arabic: StoryObj<typeof StatTile> = { args: { label: "الأسئلة", value: "١٬٢٨٤", hint: "آخر 30 يومًا" } };
