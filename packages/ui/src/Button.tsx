import type { ButtonHTMLAttributes } from "react";

import { cx } from "./cx";

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-brand text-brand-ink hover:opacity-90",
  secondary: "border border-line text-ink hover:bg-brand-soft",
  danger: "border border-line text-danger hover:bg-brand-soft",
  ghost: "text-ink hover:bg-brand-soft",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md";
}

/** The one button. Always type="button" unless told otherwise, so it never submits by accident. */
export function Button({ variant = "secondary", size = "md", className, type = "button", ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(
        "rounded-md font-medium disabled:cursor-not-allowed disabled:opacity-40",
        size === "sm" ? "px-3 py-1.5 text-sm" : "px-4 py-2",
        VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
}
