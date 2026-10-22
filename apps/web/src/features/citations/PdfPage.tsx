import "./pdfWorker";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Document, Page } from "react-pdf";

import { highlightRects } from "./highlight";
import type { Box } from "./types";

export interface PdfFile {
  data: Uint8Array;
}

interface PdfPageProps {
  /** Must keep its identity across renders: react-pdf suspends while loading and caches the
   * load by this object, so the caller creates it (once) in an already-mounted component. */
  file: PdfFile;
  page: number;
  boxes: Box[];
  onPageCount: (count: number) => void;
}

/** One PDF page at the panel's width, with the cited passage highlighted. */
export function PdfPage({ file, page, boxes, onPageCount }: PdfPageProps) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement>(null);
  const firstHighlight = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [scale, setScale] = useState<number | null>(null);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    setWidth(Math.floor(element.getBoundingClientRect().width));
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.floor(entry.contentRect.width));
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);

  const rects = scale === null ? [] : highlightRects(boxes, page, scale);

  useEffect(() => {
    firstHighlight.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [rects.length, page]);

  return (
    // PDF pages and their coordinates are physical; keep this box LTR in Arabic layouts.
    <div ref={container} dir="ltr" className="w-full">
      <Document
        file={file}
        onLoadSuccess={(pdf) => {
          onPageCount(pdf.numPages);
        }}
        loading={<p className="p-4 text-muted">{t("citations.loadingPdf")}</p>}
        error={<p className="p-4 text-danger">{t("citations.pdfFailed")}</p>}
      >
        {width > 0 && (
          <div className="relative inline-block shadow">
            <Page
              pageNumber={page}
              width={width}
              renderTextLayer={false}
              renderAnnotationLayer={false}
              onLoadSuccess={(p) => {
                setScale(p.width / p.originalWidth);
              }}
            />
            {rects.map((r, i) => (
              <div
                key={`${String(r.left)}-${String(r.top)}`}
                ref={i === 0 ? firstHighlight : undefined}
                aria-hidden
                data-testid="highlight"
                className="pointer-events-none absolute rounded-sm bg-[var(--color-focus)]/30 ring-2 ring-[var(--color-focus)]"
                style={{ left: r.left, top: r.top, width: r.width, height: r.height }}
              />
            ))}
          </div>
        )}
      </Document>
    </div>
  );
}
