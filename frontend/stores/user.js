import { defineStore } from "pinia";
import { usePage } from "@inertiajs/vue3";
import { computed } from "vue";

// Hydrated from Inertia shared props (apps/core/middleware.py).
export const useUserStore = defineStore("user", () => {
  const page = usePage();

  const user = computed(() => page.props.auth_user ?? null);
  const role = computed(() => user.value?.role ?? null);
  const allowedMenus = computed(() => page.props.allowed_menus ?? []);
  const isAuthenticated = computed(() => !!user.value);

  return { user, role, allowedMenus, isAuthenticated };
});
