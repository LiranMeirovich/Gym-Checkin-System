// The customer app's entry point: served by the public FastAPI app, the
// one reachable from the internet. Never imports anything from src/admin.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router";
import "../shared/styles/base.css";
import { App } from "./App";

// A 401 ("not linked") is an answer, not a failure, so it must never be
// retried; the pages say when the connection failed instead.
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root element");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
