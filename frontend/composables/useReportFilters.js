import { reactive, ref } from "vue";
import { router } from "@inertiajs/vue3";

/**
 * Shared server-round-trip filter state for report/listing pages.
 * Mirrors the router.get(path, params, {preserveState, preserveScroll})
 * pattern already used by Stock.vue/BarangHistori.vue — extracted so future
 * pages don't hand-roll it again. Empty-string/null/undefined values are
 * omitted from the request, matching BarangHistori's existing tampilkan().
 */
export function useReportFilters(path, initial = {}) {
  const filters = reactive({ ...initial });
  const loading = ref(false);

  function apply(options = {}) {
    const { onFinish, ...rest } = options;
    const params = {};
    for (const [key, value] of Object.entries(filters)) {
      const v = typeof value === "string" ? value.trim() : value;
      if (v !== "" && v !== null && v !== undefined) params[key] = v;
    }
    loading.value = true;
    router.get(path, params, {
      preserveState: true,
      preserveScroll: true,
      ...rest,
      onFinish: () => {
        loading.value = false;
        onFinish?.();
      },
    });
  }

  function reset() {
    Object.assign(filters, initial);
    apply();
  }

  return { filters, loading, apply, reset };
}
