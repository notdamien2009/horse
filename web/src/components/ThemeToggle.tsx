"use client";
import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

export function ThemeToggle() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  useEffect(() => setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark"), []);
  const flip = () => {
    const t = theme === "light" ? "dark" : "light";
    setTheme(t);
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("speeds-theme", t); } catch {}
  };
  return (
    <button type="button" className="icon-btn" onClick={flip} title={theme === "light" ? "Dark mode" : "Light mode"}
      aria-label={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}>
      {theme === "light" ? <Moon size={16} /> : <Sun size={16} />}
    </button>
  );
}
