import { reactive, computed } from "vue";
import { router } from "@inertiajs/vue3";

// url: the page URL, e.g. "/admin-panel/laporan/penjualan"
// initial: values from props.filters (echoed by backend)
// filterKeys: dynamic advanced-filter param names for this page, e.g.
//   ["f_qty_min", "f_qty_max", "f_status", "f_jth_tempo_mode", ...] — see
//   frontend/utils/reportFilters.js::paramNamesFor().
export function useServerReport(url, initial = {}, filterKeys = []) {
  // `recent` is informational only (drives the "100 terbaru" banner in the
  // page template via props.filters.recent directly) — it must not become an
  // editable form field, or it round-trips back as a bogus `recent=true` query
  // param on the next request.
  const { recent: _recent, ...formInitial } = initial;
  const form = reactive({
    date_mode: "range",
    date_from: "",
    date_to: "",
    date: "",
    search: "",
    sort: "tanggal",
    sort_dir: "desc",
    page: 1,
    per_page: 50,
    ...Object.fromEntries(filterKeys.map((k) => [k, ""])),
    ...formInitial,
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
      else if (k === "per_page") form[k] = 50;
      else if (k === "sort") form[k] = "tanggal";
      else if (k === "sort_dir") form[k] = "desc";
      else if (k === "date_mode") form[k] = "range";
      else form[k] = "";
    }
    // Navigate with an explicitly empty query string (not cleanParams(), which
    // always injects sort/page/per_page) so the backend sees a virgin request
    // and re-enters "100 data terbaru" recent mode, same as the first page load.
    router.get(url, {}, { preserveState: true, preserveScroll: true });
  }

  const exportHref = computed(() => `${url}/export?` + new URLSearchParams(cleanParams()).toString());

  return { form, apply, onPage, onSort, reset, exportHref };
}
