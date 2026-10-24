import { lazy, Suspense } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { EmptyState, Skeleton } from "./components/ui";
import { AlertsPage } from "./pages/AlertsPage";
import { ComparePage } from "./pages/ComparePage";
import { PurchasesPage } from "./pages/PurchasesPage";
import { HomePage } from "./pages/HomePage";
import { SearchPage } from "./pages/SearchPage";
import { WatchlistPage } from "./pages/WatchlistPage";

// Chart-heavy pages are loaded on demand to keep the first page light.
const ProductPage = lazy(() => import("./pages/ProductPage").then((m) => ({ default: m.ProductPage })));
const AdminPage = lazy(() => import("./pages/AdminPage").then((m) => ({ default: m.AdminPage })));

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="product/:id" element={<Suspense fallback={<Skeleton className="h-96 w-full" />}><ProductPage /></Suspense>} />
        <Route path="compare" element={<ComparePage />} />
        <Route path="watchlist" element={<WatchlistPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="purchases" element={<PurchasesPage />} />
        <Route path="admin" element={<Suspense fallback={<Skeleton className="h-96 w-full" />}><AdminPage /></Suspense>} />
        <Route path="*" element={<EmptyState title="Page not found"><Link to="/" className="text-brand underline">Go to the home page</Link></EmptyState>} />
      </Route>
    </Routes>
  );
}
