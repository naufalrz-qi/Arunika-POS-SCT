import { onBeforeUnmount, onMounted, ref } from "vue";

/**
 * Satu pola untuk semua panel yang mengambang (menu kolom, menu pengguna, menu
 * koneksi, daftar SelectSearch).
 *
 * Sebelum ini ada dua pola yang hidup berdampingan. Yang satu benar
 * (click-outside di SelectSearch); yang lain hack `@blur="open = false"` di
 * pemicu plus `@mousedown.prevent` di panelnya, dipakai di DataTable,
 * ServerTable, UserMenu, dan ConnectionMenu. Hack itu punya dua masalah nyata:
 *
 *   1. Tab keluar dari pemicu langsung menutup panel, jadi isinya tak pernah
 *      bisa dijangkau keyboard sama sekali.
 *   2. `@mousedown.prevent` menahan fokus supaya blur tak terpicu, yang berarti
 *      elemen di dalam panel tak pernah benar-benar menerima fokus.
 *
 * Di sini penutupan dipicu klik di luar akar dan tombol Escape, tanpa
 * mengganggu fokus — jadi isinya bisa dipakai tetikus maupun keyboard.
 *
 * @param {{ onClose?: () => void }} [options] onClose dipanggil setelah panel
 *   ditutup (mis. untuk mengembalikan fokus ke pemicu).
 */
export function useDismissable(options = {}) {
  const open = ref(false);
  const root = ref(null);

  function close() {
    if (!open.value) return;
    open.value = false;
    options.onClose?.();
  }

  function toggle() {
    open.value ? close() : (open.value = true);
  }

  function onPointerDown(e) {
    if (open.value && root.value && !root.value.contains(e.target)) close();
  }

  function onKeydown(e) {
    if (e.key === "Escape") close();
  }

  onMounted(() => {
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeydown);
  });
  onBeforeUnmount(() => {
    document.removeEventListener("mousedown", onPointerDown);
    document.removeEventListener("keydown", onKeydown);
  });

  return { open, root, close, toggle };
}
