import { Navigate, Route, Routes } from "react-router-dom";

import { ProtectedRoute } from "@/components/common/ProtectedRoute";
import { AppShell } from "@/layouts/AppShell";
import { Dashboard } from "@/pages/Dashboard";
import { Login } from "@/pages/Login";
import { ProjectDetail } from "@/pages/ProjectDetail";
import { Projects } from "@/pages/Projects";
import { Research } from "@/pages/Research";
import { SystemHealth } from "@/pages/SystemHealth";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/research" element={<Research />} />
          <Route path="/research/:runId" element={<Research />} />
          <Route path="/health" element={<SystemHealth />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
