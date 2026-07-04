import { reactive, computed } from "vue";
import { router } from "@inertiajs/vue3";

// url: the page URL, e.g. "/admin-panel/laporan/penjualan"
// initial: values from props.filters (echoed by backend)
export function useServerReport(url, initial = {}) {
  const form = reactive({
    date_from: "",
    date_to: "",
    search: "",
    sort: "tanggal",
    sort_dir: "desc",
    page: 1,
    per_page: 50,
    ...initial,
  });

  function cleanParams() {
    const out = {};
    for (const [k, v] of Object.entries(form)) {
      if (v !== "" && v !== null && v !== undefined) out[k] = v;
    }
    return out;
  }

  function apply(extra = {}) {
    Object.assign(form, extra);
    router.get(url, cleanParams(), { preserveState: true, preserveScroll: true });
  }
  function onPage(p) {
    apply({ page: p });
  }
  function onSort(s) {
    apply({ sort: s.key, sort_dir: s.dir, page: 1 });
  }
  function reset() {
    for (const k of Object.keys(form)) {
      if (k === "page") form[k] = 1;
      else if (k === "sort" || k === "sort_dir" || k === "per_page") continue;
      else form[k] = "";
    }
    apply({ page: 1 });
  }

  const exportHref = computed(() => `${url}/export?` + new URLSearchParams(cleanParams()).toString());

  return { form, apply, onPage, onSort, reset, exportHref };
}
