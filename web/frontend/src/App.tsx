import { useEffect, useMemo, useState } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import HistoryPage from "./pages/HistoryPage";
import JobDetailPage from "./pages/JobDetailPage";
import PreviewPage from "./pages/PreviewPage";
import SubmitJobPage from "./pages/SubmitJobPage";

type ThemeMode = "light" | "dark";

const THEME_KEY = "transfold-theme";

function useTheme(): [ThemeMode, () => void] {
  const [theme, setTheme] = useState<ThemeMode>(() => {
    if (typeof window === "undefined") {
      return "light";
    }
    const stored = window.localStorage.getItem(THEME_KEY);
    return stored === "dark" ? "dark" : "light";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    window.localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  const toggle = () => {
    setTheme((prev) => (prev === "light" ? "dark" : "light"));
  };

  return [theme, toggle];
}

function AppShell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const [theme, toggleTheme] = useTheme();

  const navItems = useMemo(
    () => [
      { label: "提交任务", to: "/" },
      { label: "任务历史", to: "/history" },
    ],
    [],
  );

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__inner">
          <h1 className="app-header__title">Transfold 翻译平台</h1>
          <nav className="app-nav">
            {navItems.map((item) => {
              const isActive = location.pathname === item.to || (item.to !== "/" && location.pathname.startsWith(item.to));
              return (
                <Link key={item.to} to={item.to} className={isActive ? "app-nav__link is-active" : "app-nav__link"}>
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <button type="button" className="theme-toggle" aria-label="切换主题" onClick={toggleTheme}>
            {theme === "light" ? "🌙" : "☀️"}
          </button>
        </div>
      </header>
      <main className="app-main">{children}</main>
    </div>
  );
}

function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={
          <AppShell>
            <SubmitJobPage />
          </AppShell>
        }
      />
      <Route
        path="/history"
        element={
          <AppShell>
            <HistoryPage />
          </AppShell>
        }
      />
      <Route
        path="/jobs/:id"
        element={
          <AppShell>
            <JobDetailPage />
          </AppShell>
        }
      />
      <Route
        path="/jobs/:id/preview"
        element={
          <AppShell>
            <PreviewPage />
          </AppShell>
        }
      />
      <Route
        path="*"
        element={
          <AppShell>
            <SubmitJobPage />
          </AppShell>
        }
      />
    </Routes>
  );
}

export default App;
