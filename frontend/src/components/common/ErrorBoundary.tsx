import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("[ErrorBoundary]", error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="flex min-h-[400px] flex-col items-center justify-center gap-4 p-8 text-center">
          <AlertTriangle className="h-12 w-12 text-[hsl(var(--chart-negative))]" />
          <h2 className="text-xl font-semibold text-text">页面出现错误</h2>
          <p className="max-w-md text-sm text-text-muted">
            {this.state.error?.message || "发生了未知错误，请刷新页面重试。"}
          </p>
          <div className="flex gap-3">
            <Button variant="outline" onClick={this.handleReset}>
              重试
            </Button>
            <Button variant="outline" onClick={() => window.location.assign("/")}>
              返回首页
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
