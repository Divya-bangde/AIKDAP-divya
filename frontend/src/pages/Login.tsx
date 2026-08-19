import { useState } from "react";
import { Navigate } from "react-router-dom";

import { LoginForm } from "@/features/auth/LoginForm";
import { RegisterForm } from "@/features/auth/RegisterForm";
import { useAuthStore } from "@/store/auth-store";

export function Login() {
  const accessToken = useAuthStore((state) => state.accessToken);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [registeredEmail, setRegisteredEmail] = useState<string | null>(null);

  if (accessToken) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-secondary/40 p-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary text-lg font-bold text-primary-foreground">
            A
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">AIKDAP</h1>
            <p className="text-sm text-muted-foreground">
              AI-driven Knowledge Discovery &amp; Analytics Platform
            </p>
          </div>
          <p className="text-sm italic text-muted-foreground">
            "Turn documents into grounded research."
          </p>
        </div>

        <div className="rounded-lg border border-border bg-card p-6 shadow-sm">
          {mode === "login" ? (
            <>
              <LoginForm />
              {registeredEmail && (
                <p className="mt-4 text-center text-sm text-success">
                  Account created for {registeredEmail}. Sign in above.
                </p>
              )}
              <p className="mt-6 text-center text-sm text-muted-foreground">
                Don&apos;t have an account?{" "}
                <button
                  type="button"
                  onClick={() => setMode("register")}
                  className="font-medium text-primary hover:underline"
                >
                  Register
                </button>
              </p>
            </>
          ) : (
            <>
              <RegisterForm
                onRegistered={(email) => {
                  setRegisteredEmail(email);
                  setMode("login");
                }}
              />
              <p className="mt-6 text-center text-sm text-muted-foreground">
                Already have an account?{" "}
                <button
                  type="button"
                  onClick={() => setMode("login")}
                  className="font-medium text-primary hover:underline"
                >
                  Sign in
                </button>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
