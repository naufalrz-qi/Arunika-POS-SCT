import { defineStore } from "pinia";
import { router, usePage } from "@inertiajs/vue3";
import { computed, ref } from "vue";

// Active MS SQL connection. The "active" one is shared globally (topbar);
// the full list is provided by the Connections page props.
export const useConnectionStore = defineStore("connection", () => {
  const page = usePage();
  const active = computed(() => page.props.active_connection ?? null);
  const list = computed(() => page.props.connections ?? []);

  const switching = ref(false);

  // PRD §7.2 — switching the active connection refreshes master data.
  function switchConnection(connId) {
    switching.value = true;
    const currentUrl = page.url;
    router.post(
      `/admin-panel/connections/${connId}/set-default`,
      { redirect_to: currentUrl },
      {
        preserveScroll: true,
        onFinish: () => {
          switching.value = false;
        },
      },
    );
  }

  return { active, list, switching, switchConnection };
});
