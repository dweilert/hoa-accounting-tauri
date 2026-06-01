import { type ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useCurrentUser } from "../contexts/AuthContext";

export function RequireAdmin({ children }: { children: ReactNode }) {
  const user = useCurrentUser();
  if (user?.role !== "admin") return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}
