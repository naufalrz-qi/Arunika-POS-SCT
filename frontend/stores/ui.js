import { defineStore } from "pinia";
import { ref, computed } from "vue";

let toastSeq = 0;

const SECTION_STORAGE_KEY = "sct.sidebarSections";
const THEME_STORAGE_KEY = "sct.theme";

function loadCollapsedSections() {
  try {
    const raw = localStorage.getItem(SECTION_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function loadTheme() {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "dark" || stored === "light") return stored;
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  } catch {
    return "light";
  }
}

export const useUiStore = defineStore("ui", () => {
  const sidebarCollapsed = ref(false);
  const toasts = ref([]);
  const theme = ref(loadTheme());

  // Map of section key -> true when the section is COLLAPSED. Persisted so the
  // user's open/closed layout survives reloads. Sections default to expanded.
  const collapsedSections = ref(loadCollapsedSections());

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value;
  }

  function isSectionOpen(key) {
    return !collapsedSections.value[key];
  }

  function toggleSection(key) {
    collapsedSections.value = {
      ...collapsedSections.value,
      [key]: !collapsedSections.value[key],
    };
    try {
      localStorage.setItem(SECTION_STORAGE_KEY, JSON.stringify(collapsedSections.value));
    } catch {
      /* ignore storage failures (private mode, etc.) */
    }
  }

  function pushToast(message, type = "success", timeout = 3500) {
    const id = ++toastSeq;
    toasts.value.push({ id, message, type });
    if (timeout) {
      setTimeout(() => dismissToast(id), timeout);
    }
  }

  function dismissToast(id) {
    toasts.value = toasts.value.filter((t) => t.id !== id);
  }

  function toggleTheme() {
    const newTheme = theme.value === "dark" ? "light" : "dark";
    theme.value = newTheme;
    if (newTheme === "dark") {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
    try {
      localStorage.setItem(THEME_STORAGE_KEY, newTheme);
    } catch {
      /* ignore storage failures */
    }
  }

  return {
    sidebarCollapsed,
    toasts,
    collapsedSections,
    theme,
    toggleSidebar,
    isSectionOpen,
    toggleSection,
    pushToast,
    dismissToast,
    toggleTheme,
  };
});
