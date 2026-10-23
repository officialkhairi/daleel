/** Browser tracing (only when built with VITE_OTEL=true, i.e. `make obs`). Every same-origin
 * fetch carries a W3C traceparent header, so the API continues the browser's trace: one trace
 * from the click to the model server and the database. Spans go to the collector via /otel. */
export async function startTracing(): Promise<void> {
  if (import.meta.env.VITE_OTEL !== "true") return;
  const [{ WebTracerProvider, BatchSpanProcessor }, { OTLPTraceExporter }, { registerInstrumentations }, { FetchInstrumentation }, { resourceFromAttributes }] =
    await Promise.all([
      import("@opentelemetry/sdk-trace-web"),
      import("@opentelemetry/exporter-trace-otlp-http"),
      import("@opentelemetry/instrumentation"),
      import("@opentelemetry/instrumentation-fetch"),
      import("@opentelemetry/resources"),
    ]);
  const provider = new WebTracerProvider({
    resource: resourceFromAttributes({ "service.name": "daleel-web" }),
    spanProcessors: [new BatchSpanProcessor(new OTLPTraceExporter({ url: "/otel/v1/traces" }))],
  });
  provider.register();
  registerInstrumentations({
    instrumentations: [
      new FetchInstrumentation({
        // Don't trace the trace exports themselves, or the identity provider.
        ignoreUrls: [/\/otel\//, /\/realms\//],
        propagateTraceHeaderCorsUrls: [],
      }),
    ],
  });
}
