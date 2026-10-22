import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ErrorBoundary } from "../../ErrorBoundary";
import { useDocumentFile } from "../documents/api";
import { pagesOf } from "./highlight";
import type { Citation } from "./types";

// pdf.js is large; load it only when a citation is opened.
const PdfPage = lazy(() => import("./PdfPage").then((m) => ({ default: m.PdfPage })));

export function CitationPanel({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const { t } = useTranslation();
  const isPdf = citation.page !== null && citation.bboxes.length > 0;
  const file = useDocumentFile(isPdf ? citation.doc_id : null);
  const [page, setPage] = useState(citation.page ?? 1);
  const [pageCount, setPageCount] = useState<number | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const passagePages = pagesOf(citation.bboxes);
  // Created here, in a mounted component, so it keeps its identity while PdfPage suspends (see
  // PdfPage). pdf.js detaches the buffer it is given, hence the copy.
  const pdfFile = useMemo(() => (file.data ? { data: file.data.slice() } : null), [file.data]);

  // The parent keys this panel by citation, so state starts fresh for each one.
  useEffect(() => {
    closeButton.current?.focus();
  }, []);

  return (
    <aside
      aria-labelledby="citation-title"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
      className="flex min-h-0 w-full flex-col border-line bg-surface md:w-[min(560px,45vw)] md:border-s"
    >
      <header className="flex items-start gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 id="citation-title" className="truncate font-semibold text-ink" dir="auto">
            <span className="me-2 rounded bg-brand-soft px-1.5 text-sm text-brand">{citation.n}</span>
            {citation.title}
          </h2>
          {isPdf && (
            <p className="text-sm text-muted">
              {t("citations.pageOf", { page, count: pageCount ?? "…" })}
              {passagePages.length > 1 && ` · ${t("citations.spans", { pages: passagePages.join(", ") })}`}
            </p>
          )}
        </div>
        <button
          ref={closeButton}
          type="button"
          onClick={onClose}
          className="rounded-md border border-line px-3 py-1 text-sm text-ink hover:bg-brand-soft"
        >
          {t("citations.close")}
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <blockquote dir="auto" className="mb-4 border-s-2 border-[var(--color-focus)] ps-3 text-sm text-muted">
          {citation.snippet}
        </blockquote>
        {isPdf && file.isPending && <p className="text-muted">{t("citations.loadingPdf")}</p>}
        {isPdf && file.isError && (
          <p role="alert" className="text-danger">
            {t("citations.fileFailed", { message: file.error.message })}
          </p>
        )}
        {isPdf && pdfFile && (
          <ErrorBoundary
            fallback={() => (
              <p role="alert" className="text-danger">
                {t("citations.pdfFailed")}
              </p>
            )}
          >
            <Suspense fallback={<p className="text-muted">{t("citations.loadingPdf")}</p>}>
              <PdfPage file={pdfFile} page={page} boxes={citation.bboxes} onPageCount={setPageCount} />
            </Suspense>
          </ErrorBoundary>
        )}
      </div>

      {isPdf && (
        <nav aria-label={t("citations.pages")} className="flex items-center justify-between border-t border-line px-4 py-2">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => {
              setPage((p) => p - 1);
            }}
            className="rounded-md px-3 py-1 text-sm text-ink hover:bg-brand-soft disabled:opacity-40"
          >
            {t("citations.previous")}
          </button>
          {citation.page !== null && page !== citation.page && (
            <button
              type="button"
              onClick={() => {
                setPage(citation.page ?? 1);
              }}
              className="rounded-md px-3 py-1 text-sm text-brand hover:bg-brand-soft"
            >
              {t("citations.backToPassage")}
            </button>
          )}
          <button
            type="button"
            disabled={pageCount !== null && page >= pageCount}
            onClick={() => {
              setPage((p) => p + 1);
            }}
            className="rounded-md px-3 py-1 text-sm text-ink hover:bg-brand-soft disabled:opacity-40"
          >
            {t("citations.next")}
          </button>
        </nav>
      )}
    </aside>
  );
}
