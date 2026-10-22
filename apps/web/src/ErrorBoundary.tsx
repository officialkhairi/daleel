import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  fallback: (reset: () => void) => ReactNode;
  children: ReactNode;
}

/** Keeps a failure in one part of the page (say, the PDF viewer) from blanking everything. */
export class ErrorBoundary extends Component<Props, { failed: boolean }> {
  override state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("UI error", error, info.componentStack);
  }

  override render(): ReactNode {
    if (this.state.failed) {
      return this.props.fallback(() => {
        this.setState({ failed: false });
      });
    }
    return this.props.children;
  }
}
