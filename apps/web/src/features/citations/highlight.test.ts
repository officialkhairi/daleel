import { describe, expect, it } from "vitest";

import { highlightRects, pagesOf } from "./highlight";

const boxes = [
  { page: 1, x0: 70, y0: 100, x1: 520, y1: 140 },
  { page: 2, x0: 70, y0: 50, x1: 300, y1: 60 },
];

describe("highlightRects", () => {
  it("scales the boxes on the shown page to pixels, padded", () => {
    expect(highlightRects(boxes, 1, 2, 2)).toEqual([{ left: 138, top: 198, width: 904, height: 84 }]);
  });

  it("returns nothing for pages the passage doesn't touch", () => {
    expect(highlightRects(boxes, 3, 1)).toEqual([]);
  });
});

it("pagesOf lists each page once, in order", () => {
  expect(pagesOf([...boxes, ...boxes].reverse())).toEqual([1, 2]);
});
