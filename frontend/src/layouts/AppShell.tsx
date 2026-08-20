import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { Activity, FolderKanban, LayoutDashboard, LogOut, Search } from "lucide-react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { AikdapMark } from "@/components/common/AikdapMark";
import { ThemeToggle } from "@/components/common/ThemeToggle";
import { RoutedPage } from "@/layouts/RoutedPage";
import { cn } from "@/lib/utils";
import { fadeIn, layoutSpring } from "@/lib/motion";
import { useAuth } from "@/hooks/useAuth";
import * as healthService from "@/services/health";

const NAV_ITEMS: { to: string; label: string; icon: typeof LayoutDashboard; end: boolean }[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/projects", label: "Projects", icon: FolderKanban, end: false },
  { to: "/research", label: "Research", icon: Search, end: false },
  { to: "/health", label: "System Health", icon: Activity, end: false },
];

/** Colour for the topbar's status dot. Derived only from the overall
 * status the backend reports — never computed from the individual
 * component statuses, which is the backend's job, not the UI's. */
const STATUS_DOT: Record<string, string> = {
  healthy: "bg-success",
  degraded: "bg-warning",
  unhealthy: "bg-destructive",
};

/** A live system-status pill in the topbar.
 *
 * Shares the `["health"]` query key with the Dashboard and the System
 * Health page, so TanStack Query serves all three from one cached
 * response rather than three separate polls. Renders nothing at all
 * until real data arrives — an unknown status is not drawn as a
 * healthy one. */
function SystemStatusPill() {
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: healthService.getHealth,
    refetchOnWindowFocus: false,
  });

  if (!healthQuery.isSuccess) return null;

  const status = healthQuery.data.status;

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={fadeIn}
      className="hidden items-center gap-2 rounded-full border border-border bg-sunken px-3 py-1.5 sm:flex"
    >
      <span className="relative flex h-2 w-2">
        <span
          className={cn(
            "absolute inline-flex h-full w-full rounded-full opacity-60",
            STATUS_DOT[status] ?? "bg-muted-foreground",
            status === "healthy" && "animate-ping",
          )}
        />
        <span
          className={cn(
            "relative inline-flex h-2 w-2 rounded-full",
            STATUS_DOT[status] ?? "bg-muted-foreground",
          )}
        />
      </span>
      <span className="text-label uppercase text-muted-foreground">System</span>
      <span className="text-xs font-medium capitalize text-foreground">{status}</span>
    </motion.div>
  );
}

function NavItems({ compact = false }: { compact?: boolean }) {
  const location = useLocation();

  return (
    <>
      {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => {
        const isActive = end
          ? location.pathname === to
          : location.pathname.startsWith(to);

        return (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={cn(
              "group relative flex shrink-0 items-center gap-3 rounded-md font-medium transition-colors",
              compact ? "px-3 py-1.5 text-xs" : "px-3 py-2 text-sm",
              isActive ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {/* One shared `layoutId` across all four links, so Motion
             * animates a single indicator sliding between them rather
             * than cross-fading four separate backgrounds. */}
            {isActive && (
              <motion.span
                layoutId={compact ? "nav-indicator-compact" : "nav-indicator"}
                transition={layoutSpring}
                className="absolute inset-0 rounded-md bg-accent"
              />
            )}
            <Icon
              className={cn(
                "relative z-10 transition-transform duration-200 group-hover:scale-110",
                compact ? "h-3.5 w-3.5" : "h-4 w-4",
                isActive && "text-accent-foreground",
              )}
            />
            <span className={cn("relative z-10", isActive && "text-accent-foreground")}>
              {label}
            </span>
          </NavLink>
        );
      })}
    </>
  );
}

/** The application shell every protected route renders inside — one
 * sidebar, one topbar, and the routed page in between. Built once so
 * navigation, branding, and logout live in exactly one place. */
export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  /** Signing out returns the user to the public entry experience, not
   * to a login form (Sprint 9K.4, Phase 10). `/` is the landing page
   * for anyone without a session — including after a reload, since the
   * route is chosen from the persisted auth store rather than from any
   * "just logged out" flag. Navigating explicitly rather than relying
   * on `ProtectedRoute` to bounce, so logout lands in the same place
   * from every page. */
  function handleLogout() {
    logout();
    navigate("/", { replace: true });
  }

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-border bg-card md:flex">
        <div className="flex h-16 items-center gap-3 border-b border-border px-6">
          <AikdapMark className="h-9 w-9 rounded-lg shadow-subtle" />
          <div className="flex flex-col">
            <span className="font-display text-sm font-semibold leading-tight tracking-tight">AIKDAP</span>
            <span className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              Intelligence
            </span>
          </div>
        </div>

        <nav className="flex flex-1 flex-col gap-1 p-3">
          <p className="px-3 pb-2 pt-3 text-label uppercase text-muted-foreground">Workspace</p>
          <NavItems />
        </nav>

        <div className="border-t border-border p-3">
          <div className="rounded-lg bg-sunken p-3">
            <p className="text-label uppercase text-muted-foreground">Signed in</p>
            <p className="mt-1 truncate text-xs font-medium text-foreground">
              {user?.email ?? "—"}
            </p>
          </div>
        </div>
      </aside>

      {/* `min-w-0` is load-bearing, not cosmetic. A flex item defaults to
       * `min-width: auto`, which means this column refuses to shrink below
       * its content's intrinsic minimum — so on a phone it stayed 450px
       * wide inside a 390px viewport and every authenticated page scrolled
       * sideways by 60px (measured at 390×844 on dashboard, projects,
       * research and health alike; Sprint 9K.6). Zeroing it lets the column
       * take the viewport's width and hands overflow back to the children
       * that are actually built for it — the mobile nav scrolls, the page
       * content wraps. */}
      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-border bg-card/85 px-4 backdrop-blur-sm md:px-8">
          <span className="font-display text-sm font-semibold tracking-tight md:hidden">AIKDAP</span>
          <div className="hidden md:block" />
          <div className="flex items-center gap-2">
            <SystemStatusPill />
            <ThemeToggle />
            <button
              type="button"
              onClick={handleLogout}
              className="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              aria-label="Log out"
            >
              <LogOut className="h-4 w-4" />
              <span className="hidden sm:inline">Logout</span>
            </button>
          </div>
        </header>

        <nav className="flex items-center gap-1 overflow-x-auto border-b border-border bg-card px-4 py-2 md:hidden">
          <NavItems compact />
        </nav>

        <main className="relative flex-1 p-4 md:p-8">
          <div
            aria-hidden="true"
            className="app-grid-surface pointer-events-none absolute inset-0 opacity-60"
          />
          <div className="relative mx-auto w-full max-w-[1400px]">
            <RoutedPage />
          </div>
        </main>
      </div>
    </div>
  );
}
