/** A PDF box in points with a top-left origin, as stored by the worker. */
export interface Box {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

/** Payload of a `citation` event (also saved on the answer). */
export interface Citation {
  n: number;
  chunk_id: string;
  doc_id: string;
  title: string;
  page: number | null;
  bbox: Box | null;
  bboxes: Box[];
  snippet: string;
}
