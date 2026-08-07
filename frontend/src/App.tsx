import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "antd";
import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { api, auth } from "./api/client";
import AppLayout, { isManagerRole } from "./layouts/AppLayout";
import History from "./pages/History";
import Login from "./pages/Login";
import Queue from "./pages/Queue";
import Triage from "./pages/Triage";

/**
 * Queue, Triage and History are the daily path and load eagerly. The rest —
 * everything that pulls in Recharts or the markdown renderer — is split out so
 * an engineer who never opens Control never downloads a charting library.
 */
const Audit = lazy(() => import("./pages/Audit"));
const Chat = lazy(() => import("./pages/Chat"));
const Control = lazy(() => import("./pages/Control"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Documents = lazy(() => import("./pages/Documents"));
const Evals = lazy(() => import("./pages/Evals"));

function Protected({ children }: { children: React.ReactNode }) {
  return auth.get() ? <>{children}</> : <Navigate to="/login" replace />;
}

function useRole() {
  const { data: me, isPending } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.me().then((r) => r.data),
    staleTime: 5 * 60_000,
  });
  return { role: me?.role, isPending };
}

/**
 * The landing page follows the role, not the route the user came from.
 * The API is still the boundary — this only avoids showing an engineer a screen
 * that would 403 on them.
 */
function RoleLanding() {
  const { role, isPending } = useRole();
  if (isPending) return <Skeleton active paragraph={{ rows: 4 }} />;
  return <Navigate to={isManagerRole(role) ? "/control" : "/queue"} replace />;
}

/** Convenience only. The API rejects the same requests regardless of this check. */
function ManagerOnly({ children }: { children: React.ReactNode }) {
  const { role, isPending } = useRole();
  if (isPending) return <Skeleton active paragraph={{ rows: 4 }} />;
  return isManagerRole(role) ? <>{children}</> : <Navigate to="/queue" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login mode="team" />} />
      <Route path="/manager/login" element={<Login mode="manager" />} />
      <Route
        path="/"
        element={
          <Protected>
            <AppLayout />
          </Protected>
        }
      >
        <Route index element={<RoleLanding />} />
        <Route path="queue" element={<Queue />} />
        <Route path="triage" element={<Triage />} />
        <Route path="history" element={<History />} />
        <Route
          path="control"
          element={
            <ManagerOnly>
              <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} />}>
                <Control />
              </Suspense>
            </ManagerOnly>
          }
        />
        <Route
          path="dashboard"
          element={
            <ManagerOnly>
              <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} />}>
                <Dashboard />
              </Suspense>
            </ManagerOnly>
          }
        />
        <Route
          path="chat"
          element={
            <ManagerOnly>
              <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} />}>
                <Chat />
              </Suspense>
            </ManagerOnly>
          }
        />
        <Route
          path="documents"
          element={
            <ManagerOnly>
              <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} />}>
                <Documents />
              </Suspense>
            </ManagerOnly>
          }
        />
        <Route
          path="evals"
          element={
            <ManagerOnly>
              <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} />}>
                <Evals />
              </Suspense>
            </ManagerOnly>
          }
        />
        <Route
          path="audit"
          element={
            <ManagerOnly>
              <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} />}>
                <Audit />
              </Suspense>
            </ManagerOnly>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
