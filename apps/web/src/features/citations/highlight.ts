import type { Box } from "./types";

export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Boxes on `page`, scaled from PDF points to CSS pixels and padded a little. PDF coordinates are
 * physical (not logical), so callers position these with left/top even in RTL layouts. */
export function highlightRects(boxes: Box[], page: number, scale: number, pad = 2): Rect[] {
  return boxes
    .filter((b) => b.page === page)
    .map((b) => ({
      left: b.x0 * scale - pad,
      top: b.y0 * scale - pad,
      width: (b.x1 - b.x0) * scale + pad * 2,
      height: (b.y1 - b.y0) * scale + pad * 2,
    }));
}

/** Pages a passage touches, in order (a chunk can run across a page break). */
export function pagesOf(boxes: Box[]): number[] {
  return [...new Set(boxes.map((b) => b.page))].sort((a, b) => a - b);
}
