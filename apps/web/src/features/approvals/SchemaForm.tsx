import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { JsonSchema } from "./types";

export type FormValues = Record<string, unknown>;

interface SchemaFormProps {
  schema: JsonSchema;
  values: FormValues;
  onChange: (values: FormValues) => void;
  readOnly: boolean;
}

/** The single field type behind a Pydantic `X | None` (anyOf with null). */
function unwrap(schema: JsonSchema): JsonSchema {
  const options = schema.anyOf?.filter((s) => s.type !== "null");
  if (options?.length !== 1 || !options[0]) return schema;
  return { ...options[0], ...(schema.title ? { title: schema.title } : {}) };
}

function asText(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function isLongText(name: string, schema: JsonSchema): boolean {
  return name === "body" || (schema.maxLength ?? 0) > 500;
}

/** Edits a tool call's arguments, generated from the tool's JSON Schema. Lists of strings (e.g.
 * recipients) are edited as comma-separated text; ids are shown but never editable. */
export function SchemaForm({ schema, values, onChange, readOnly }: SchemaFormProps) {
  const { t } = useTranslation();
  const formId = useId();
  const all = schema.properties ?? {};
  const order = schema["x-order"] ?? Object.keys(all);
  const properties = order.flatMap((name) => (all[name] ? [[name, all[name]] as const] : []));
  // What the person typed into list fields, so a trailing comma survives until the next item.
  const [listText, setListText] = useState<Record<string, string>>({});

  const set = (name: string, value: unknown) => {
    onChange({ ...values, [name]: value });
  };

  return (
    <div className="grid gap-3">
      {properties.map(([name, raw]) => {
        const field = unwrap(raw);
        const id = `${formId}-${name}`;
        const label = t(`approvals.fields.${name}`, { defaultValue: field.title ?? name });
        const value = values[name];
        const common = {
          id,
          disabled: readOnly,
          className:
            "w-full rounded-md border border-line bg-paper px-3 py-2 text-ink disabled:border-transparent disabled:bg-transparent disabled:px-0",
        };

        let control;
        if (field.format === "uuid" || (field.type === "array" && field.items?.format === "uuid")) {
          control = (
            <code id={id} dir="ltr" className="block truncate text-xs text-muted">
              {Array.isArray(value) ? value.join(", ") : asText(value)}
            </code>
          );
        } else if (field.enum) {
          control = (
            <select
              {...common}
              value={asText(value ?? field.default)}
              onChange={(e) => {
                set(name, e.target.value);
              }}
            >
              {field.enum.map((option) => (
                <option key={option} value={option}>
                  {t(`approvals.options.${option}`, { defaultValue: option })}
                </option>
              ))}
            </select>
          );
        } else if (field.type === "array") {
          control = (
            <input
              {...common}
              dir="ltr"
              value={listText[name] ?? (Array.isArray(value) ? value.join(", ") : "")}
              onChange={(e) => {
                const raw = e.target.value;
                setListText((current) => ({ ...current, [name]: raw }));
                set(
                  name,
                  raw
                    .split(",")
                    .map((part) => part.trim())
                    .filter(Boolean),
                );
              }}
            />
          );
        } else if (field.type === "integer" || field.type === "number") {
          control = (
            <input
              {...common}
              type="number"
              value={typeof value === "number" ? value : ""}
              onChange={(e) => {
                set(name, e.target.value === "" ? undefined : Number(e.target.value));
              }}
            />
          );
        } else if (isLongText(name, field)) {
          control = (
            <textarea
              {...common}
              dir="auto"
              rows={readOnly ? Math.min(12, asText(value).split("\n").length + 1) : 6}
              value={asText(value)}
              onChange={(e) => {
                set(name, e.target.value);
              }}
              // A decided request shows all of its text: grow to fit instead of scrolling.
              className={`${common.className} whitespace-pre-wrap ${readOnly ? "resize-none [field-sizing:content]" : ""}`}
            />
          );
        } else {
          control = (
            <input
              {...common}
              dir="auto"
              value={asText(value)}
              onChange={(e) => {
                set(name, e.target.value);
              }}
            />
          );
        }

        return (
          <div key={name} className="grid gap-1 sm:grid-cols-[8rem_1fr] sm:items-start">
            <label htmlFor={id} className="pt-2 text-sm text-muted">
              {label}
            </label>
            {control}
          </div>
        );
      })}
    </div>
  );
}

/** Values that differ from the original, or null when nothing changed. */
export function changes(original: FormValues, edited: FormValues): FormValues | null {
  return JSON.stringify(original) === JSON.stringify(edited) ? null : edited;
}
