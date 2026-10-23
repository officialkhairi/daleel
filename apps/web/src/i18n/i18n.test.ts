import { describe, expect, it } from "vitest";

import ar from "./ar.json";
import en from "./en.json";

type Tree = { [key: string]: string | Tree };

/** Keys with plural suffixes (_one, _other, _few…) are compared by their base name. */
function keys(tree: Tree, prefix = ""): Set<string> {
  const out = new Set<string>();
  for (const [key, value] of Object.entries(tree)) {
    const path = `${prefix}${key.replace(/_(zero|one|two|few|many|other)$/, "")}`;
    if (typeof value === "string") out.add(path);
    else for (const child of keys(value, `${path}.`)) out.add(child);
  }
  return out;
}

describe("translations", () => {
  it("every English string has an Arabic one, and the other way round", () => {
    const english = keys(en);
    const arabic = keys(ar);
    expect([...english].filter((k) => !arabic.has(k))).toEqual([]);
    expect([...arabic].filter((k) => !english.has(k))).toEqual([]);
  });

  it("interpolations match", () => {
    const vars = (s: string) => [...s.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort();
    const flat = (tree: Tree, prefix = ""): [string, string][] =>
      Object.entries(tree).flatMap(([k, v]) => (typeof v === "string" ? [[`${prefix}${k}`, v] as [string, string]] : flat(v, `${prefix}${k}.`)));
    const arabic = new Map(flat(ar));
    for (const [key, value] of flat(en)) {
      const other = arabic.get(key) ?? arabic.get(key.replace(/_(one|other)$/, "_other"));
      if (other === undefined || key.endsWith("_one")) continue;
      expect(vars(other), key).toEqual(vars(value));
    }
  });
});
