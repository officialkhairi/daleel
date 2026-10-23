import type { Meta, StoryObj } from "@storybook/react-vite";

import { Badge } from "./Badge";

const meta: Meta<typeof Badge> = { title: "UI/Badge", component: Badge, args: { children: "Low risk" } };
export default meta;
type Story = StoryObj<typeof Badge>;

export const Brand: Story = { args: { tone: "brand" } };
export const Warning: Story = { args: { tone: "warning", children: "Medium risk" } };
export const Danger: Story = { args: { tone: "danger", children: "High risk" } };
export const Arabic: Story = { args: { tone: "danger", children: "خطورة عالية" } };
