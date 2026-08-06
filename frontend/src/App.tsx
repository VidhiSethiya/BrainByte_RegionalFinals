import { Navigate, Route, Routes } from "react-router-dom";

import { auth } from "./api/client";
import AppLayout from "./layouts/AppLayout";
import Audit from "./pages/Audit";
import Chat from "./pages/Chat";
import Dashboard from "./pages/Dashboard";
import Documents from "./pages/Documents";
import Evals from "./pages/Evals";
import Login from "./pages/Login";

function Protected({ children }: { children: React.ReactNode }) {
  return auth.get() ? <>{children}</> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <Protected>
            <AppLayout />
          </Protected>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="chat" element={<Chat />} />
        <Route path="documents" element={<Documents />} />
        <Route path="evals" element={<Evals />} />
        <Route path="audit" element={<Audit />} />
        {/* [PLACEHOLDER: DOMAIN_PAGES — add the workflow screens the problem
            statement needs, e.g. a case review or approval queue] */}
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
