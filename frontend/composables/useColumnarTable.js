import { computed, onScopeDispose, ref, shallowRef, watch } from "vue";

/**
 * Tabel besar sepenuhnya di peramban, tanpa membuat satu objek per baris.
 *
 * Dipakai halaman yang harus mencari lintas SELURUH dataset tanpa bolak-balik
 * ke server (Stok Akhir: 54.955 baris). Bentuk "list of dict" tak sanggup —
 * terukur 123 MB heap dan tab Firefox Android yang tak pernah selesai memuat.
 * Payload-nya kolom-mayor + kamus; lihat apps/inventory/services.py::_kolumnar.
 *
 * Tiga aturan yang menahan biayanya, semuanya perlu:
 *
 *  1. Data mentah TIDAK pernah masuk reaktivitas Vue. Mem-proxy 55rb entri
 *     adalah separuh dari 123 MB itu. Yang reaktif cuma state kecil (halaman,
 *     urutan, kata kunci) plus `version` yang menandai data baru datang.
 *  2. Hasil saring+urut disimpan sebagai Int32Array berisi INDEKS baris
 *     (55rb × 4 byte = 220 KB), bukan salinan barisnya.
 *  3. Hanya baris halaman berjalan yang dijadikan objek — paling banyak
 *     `perPage` buah, bukan 55rb.
 *
 * Pencarian mencocokkan salinan huruf-kecil yang dibangun SEKALI saat data
 * masuk. Merangkai/menurunkan-huruf string per baris tiap ketikan adalah yang
 * membuat kolom cari tersendat di dataset sebesar ini.
 */
const SEARCH_DEBOUNCE_MS = 200;

export function useColumnarTable(getPayload, options = {}) {
  const { searchKeys = [], defaultSort = "", defaultSortDir = "asc", perPage: perPageInit = 100 } =
    options;

  // Di luar ref: isinya tak boleh di-proxy. `version` yang memberi tahu computed
  // bahwa isinya berganti.
  let store = null;
  let sorted = { key: null, dir: null, arr: null };
  const version = ref(0);

  // `searchInput` yang diikat ke kolom isian; `search` yang menggerakkan
  // penyaringan. Keduanya dipisah karena menyaring 55rb baris tak bisa
  // dikerjakan per ketikan: satu huruf memicu ~110rb pencarian substring, dan
  // di ponsel (CPU 6x) itu terukur ~1,2 detik tersendat per huruf. Dengan jeda
  // ini kolom isian tetap responsif dan penyaringan jalan sekali setelah
  // pengetikan berhenti.
  const searchInput = ref("");
  const search = ref("");
  let searchTimer = null;
  watch(searchInput, (v) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      search.value = v;
    }, SEARCH_DEBOUNCE_MS);
  });
  // Pindah menu dalam jeda 200 ms itu meninggalkan timer yang menembak ke
  // scope yang sudah mati.
  onScopeDispose(() => clearTimeout(searchTimer));
  const sortKey = ref(defaultSort);
  const sortDir = ref(defaultSortDir);
  const page = ref(1);
  const perPage = ref(perPageInit);
  // { namaKolom: nilaiTerpilih } — saringan sama-dengan atas kolom berkamus.
  const equals = shallowRef({});

  function ingest(payload) {
    if (!payload || !payload.cols) {
      store = null;
      version.value++;
      return;
    }
    const col = {};
    for (const c of payload.cols) {
      const raw = payload.data[c];
      // Bentuk kolom DINYATAKAN server, tidak ditebak dari `typeof raw[0]`:
      // tebakan itu salah begitu kolom angka memuat satu null, dan hasilnya
      // NaN yang tercetak ke layar. Lihat _kolumnar di services.py.
      const kind = payload.types[c];
      if (kind === "dict") {
        col[c] = { kind, idx: Int32Array.from(raw), dict: payload.dict[c] };
      } else if (kind === "num") {
        col[c] = { kind, arr: Float64Array.from(raw) };
      } else {
        // Larik hasil parse dipakai APA ADANYA, tidak disalin. Inertia tetap
        // memegang payload-nya selama halaman hidup, jadi `raw.map(String)`
        // hanya menggandakan 55rb string yang sudah ada di memori — dan kolom
        // string di sini (kd_barang, barang) memang yang paling besar.
        col[c] = { kind, arr: raw };
      }
      if (searchKeys.includes(c)) {
        // Kolom berkamus cukup diturunkan hurufnya di TABEL KAMUS-nya
        // (ratusan entri), bukan di 55rb barisnya.
        const src = kind === "dict" ? payload.dict[c] : raw;
        col[c].lower = src.map((s) => (s == null ? "" : String(s).toLowerCase()));
      }
    }
    store = { cols: payload.cols, n: payload.n, col };
    sorted = { key: null, dir: null, arr: null };
    // Payload baru (mis. tanggal lain) bisa punya baris jauh lebih sedikit;
    // tanpa ini pengguna yang sedang di halaman 300 mendapat tabel kosong.
    page.value = 1;
    version.value++;
  }

  // Urutan SELURUH baris untuk (sortKey, sortDir) berjalan, dihitung sekali.
  //
  // Sebelumnya mengurut dijalankan atas hasil saringan, jadi tiap ketikan di
  // kolom cari memicu satu sort penuh. Terukur di viewport ponsel dengan CPU
  // 6x: satu huruf = 1265 ms tersendat, karena huruf pertama masih meloloskan
  // ~40rb baris dan mengurut 40rb string itu ~1 detik.
  //
  // Menyaring larik yang SUDAH terurut mempertahankan urutannya, jadi sort
  // hanya perlu diulang saat kolom/arah urut benar-benar berubah — bukan saat
  // kata kunci berubah.
  function sortedAll() {
    const key = sortKey.value;
    const dir = sortDir.value;
    if (sorted.arr && sorted.key === key && sorted.dir === dir) return sorted.arr;
    const n = store.n;
    const arr = new Int32Array(n);
    for (let i = 0; i < n; i++) arr[i] = i;
    const c = key && store.col[key];
    if (c) {
      const sign = dir === "asc" ? 1 : -1;
      if (c.kind === "num") {
        arr.sort((x, y) => (c.arr[x] - c.arr[y]) * sign);
      } else if (c.kind === "dict") {
        // Kamus dari server sudah terurut, jadi membandingkan INDEKS setara
        // membandingkan teksnya — jauh lebih murah daripada localeCompare.
        arr.sort((x, y) => (c.idx[x] - c.idx[y]) * sign);
      } else {
        // Pakai salinan huruf-kecil bila ada: membandingkan string mentah
        // menaruh seluruh nama ber-huruf-kecil SETELAH yang huruf besar
        // (urutan titik-kode), sehingga "xxxx" terlempar ke ujung daftar.
        //
        // Kolom `raw` boleh memuat null. Tanpa penanganan khusus, `null < "a"`
        // dan `null > "a"` sama-sama false sehingga comparator melaporkan
        // "sama" untuk pasangan yang tak sama — urutan jadi tak konsisten dan
        // hasil sort-nya tak terdefinisi. Null selalu ditaruh di belakang.
        const a = c.lower || c.arr;
        arr.sort((x, y) => {
          const p = a[x];
          const q = a[y];
          if (p == null) return q == null ? 0 : 1;
          if (q == null) return -1;
          return (p < q ? -1 : p > q ? 1 : 0) * sign;
        });
      }
    }
    sorted = { key, dir, arr };
    return arr;
  }

  // Mengetik kata kunci baru sementara berada di halaman 12 akan menampilkan
  // halaman kosong walau hasilnya ada — kembalikan ke halaman pertama.
  watch(search, () => {
    page.value = 1;
  });

  function valueAt(name, i) {
    const c = store.col[name];
    if (!c) return null;
    if (c.kind === "dict") return c.dict[c.idx[i]];
    if (c.kind === "num") return c.arr[i];
    return c.arr[i];
  }

  // Indeks baris yang lolos saringan, lalu diurut. Satu Int32Array, dibangun
  // ulang hanya saat saringan/urutan berubah — bukan saat halaman berpindah.
  const order = computed(() => {
    version.value; // eslint-disable-line no-unused-expressions -- dependensi
    if (!store) return new Int32Array(0);
    const n = store.n;
    const term = search.value.trim().toLowerCase();

    // Saringan sama-dengan diterjemahkan jadi indeks kamus sekali di depan;
    // di dalam loop tinggal banding angka.
    const eqCols = [];
    for (const [name, val] of Object.entries(equals.value)) {
      if (val === "" || val == null) continue;
      const c = store.col[name];
      if (!c) continue;
      if (c.kind === "dict") {
        const wanted = c.dict.indexOf(val);
        if (wanted < 0) return new Int32Array(0); // nilai tak ada → nihil, bukan semua
        eqCols.push({ idx: c.idx, wanted });
      } else {
        // Nilai dari <select> selalu string; kolom angka menyimpan number.
        // Tanpa konversi, `"12" !== 12` dan filternya tak pernah cocok.
        eqCols.push({ arr: c.arr, wanted: c.kind === "num" ? Number(val) : val });
      }
    }

    const haystacks = term
      ? searchKeys.map((k) => store.col[k]).filter((c) => c && c.lower)
      : [];

    // Ditelusuri dalam urutan terurut, jadi hasilnya ikut terurut tanpa sort.
    const src = sortedAll();
    const buf = new Int32Array(n);
    let m = 0;
    outer: for (let j = 0; j < n; j++) {
      const i = src[j];
      for (const e of eqCols) {
        if (e.idx ? e.idx[i] !== e.wanted : e.arr[i] !== e.wanted) continue outer;
      }
      if (term) {
        let hit = false;
        for (const c of haystacks) {
          const s = c.kind === "dict" ? c.lower[c.idx[i]] : c.lower[i];
          if (s.includes(term)) {
            hit = true;
            break;
          }
        }
        if (!hit) continue;
      }
      buf[m++] = i;
    }
    return buf.slice(0, m);
  });

  const total = computed(() => order.value.length);
  const n = computed(() => (version.value, store ? store.n : 0));

  const pageRows = computed(() => {
    const ord = order.value;
    if (!store) return [];
    const start = (page.value - 1) * perPage.value;
    const end = Math.min(start + perPage.value, ord.length);
    const rows = [];
    for (let i = start; i < end; i++) {
      const r = ord[i];
      const o = { _rid: i + 1 };
      for (const cname of store.cols) o[cname] = valueAt(cname, r);
      rows.push(o);
    }
    return rows;
  });

  /** Jumlah kolom angka atas baris yang lolos saringan.
   *
   *  Dibaca langsung dari Float64Array lewat daftar indeks — tak ada baris yang
   *  dijadikan objek hanya untuk menghitung ringkasan. */
  function sumOf(name) {
    version.value;
    const c = store && store.col[name];
    if (!c || c.kind !== "num") return 0;
    const ord = order.value;
    let s = 0;
    for (let i = 0; i < ord.length; i++) s += c.arr[ord[i]];
    return s;
  }

  /** Opsi dropdown untuk satu kolom.
   *
   *  Kolom berkamus gratis: tabel kamusnya memang sudah daftar nilai unik yang
   *  terurut. Kolom lain dipindai sekali dan hasilnya disimpan — tanpa cadangan
   *  ini, kolom yang kebetulan melewati ambang kamus (nilai uniknya terlalu
   *  banyak) membuat dropdown-nya kosong tanpa gejala lain, dan filternya mati
   *  diam-diam. */
  const optionsCache = new Map();

  function dictOptions(name) {
    version.value;
    const c = store && store.col[name];
    if (!c) return [];
    if (c.kind === "dict") return c.dict.filter((v) => v !== "").map((v) => ({ value: v, label: v }));
    const memo = optionsCache.get(name);
    if (memo && memo.v === version.value) return memo.opts;
    const uniq = [...new Set(c.arr)].filter((v) => v !== "" && v != null);
    uniq.sort((p, q) => (p < q ? -1 : p > q ? 1 : 0));
    const opts = uniq.map((v) => ({ value: v, label: String(v) }));
    optionsCache.set(name, { v: version.value, opts });
    return opts;
  }

  function setSort({ key, dir }) {
    sortKey.value = key;
    sortDir.value = dir;
    page.value = 1;
  }
  function setPerPage(v) {
    perPage.value = v;
    page.value = 1;
  }
  function setEquals(name, value) {
    equals.value = { ...equals.value, [name]: value };
    page.value = 1;
  }
  function resetFilters() {
    searchInput.value = "";
    search.value = "";
    equals.value = {};
    page.value = 1;
  }

  return {
    ingest, dictOptions, valueAt, sumOf,
    searchInput, search, sortKey, sortDir, page, perPage, equals,
    order, total, n, pageRows,
    setSort, setPerPage, setEquals, resetFilters,
  };
}
