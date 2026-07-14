import { onMounted, onUnmounted, ref } from "vue";

// Tidak ada sinyal progress asli dari backend (satu query blocking per
// deferred prop) — jadi ini cuma kasih tanda "masih hidup" (elapsed timer)
// + pesan berjenjang biar user tahu ini bukan macet, tanpa janji persen palsu.
const STAGES = [
  { after: 0, hint: "" },
  { after: 3, hint: "Sedikit lebih lama dari biasanya…" },
  { after: 8, hint: "Query lumayan besar — mohon tunggu…" },
  { after: 20, hint: "Masih diproses. Cek koneksi server di navbar kalau ini kelamaan." },
];

export function useLoadingProgress() {
  const elapsed = ref(0);
  const hint = ref("");
  let timer = null;

  onMounted(() => {
    timer = setInterval(() => {
      elapsed.value += 1;
      for (const stage of STAGES) {
        if (elapsed.value >= stage.after) hint.value = stage.hint;
      }
    }, 1000);
  });
  onUnmounted(() => clearInterval(timer));

  return { elapsed, hint };
}
