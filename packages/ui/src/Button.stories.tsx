import type { Meta, StoryObj } from "@storybook/react-vite";

import { Button } from "./Button";

const meta: Meta<typeof Button> = {
  title: "UI/Button",
  component: Button,
  args: { children: "Approve", variant: "primary" },
};
export default meta;
type Story = StoryObj<typeof Button>;

export const Primary: Story = {};
export const Secondary: Story = { args: { variant: "secondary", children: "Try again" } };
export const Danger: Story = { args: { variant: "danger", children: "Reject" } };
export const Ghost: Story = { args: { variant: "ghost", children: "العربية" } };
export const Small: Story = { args: { size: "sm", children: "Sign out", variant: "secondary" } };
export const Disabled: Story = { args: { disabled: true } };
export const Arabic: Story = {
  args: { children: "موافقة" },
  parameters: { direction: "rtl" },
};
