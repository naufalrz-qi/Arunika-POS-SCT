import { defineStore } from "pinia";
import { ref } from "vue";

let toastSeq = 0;

const SIDEBAR_STORAGE_KEY = "sct.sidebarCollapsed";
const THEME_STORAGE_KEY = "sct.theme";

function loadSidebarCollapsed() {
  try {
    return localStorage.getItem(SIDEBAR_STORAGE_KEY) === "1";
  } catch {
    return false;
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
  const sidebarCollapsed = ref(loadSidebarCollapsed());
  const toasts = ref([]);
  const theme = ref(loadTheme());

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value;
    try {
      localStorage.setItem(SIDEBAR_STORAGE_KEY, sidebarCollapsed.value ? "1" : "0");
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
    theme,
    toggleSidebar,
    pushToast,
    dismissToast,
    toggleTheme,
  };
});
