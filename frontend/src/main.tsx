import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Component, StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 30_000 } },
});

// Shows the error on screen instead of a blank white page if something crashes.
class CrashScreen extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{ padding: 24, fontFamily: "system-ui, sans-serif" }}>
        <h1 style={{ fontSize: 20, fontWeight: 700 }}>Something went wrong</h1>
        <p style={{ marginTop: 8 }}>Please reload the page. If it keeps happening, share this message:</p>
        <pre style={{ marginTop: 12, whiteSpace: "pre-wrap", color: "#b42318" }}>{String(this.state.error?.message ?? this.state.error)}</pre>
      </div>
    );
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <CrashScreen>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
    </CrashScreen>
  </StrictMode>,
);
