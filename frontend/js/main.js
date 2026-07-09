import "../css/main.css";

import { createApp, h } from "vue";
import { createInertiaApp } from "@inertiajs/vue3";
import { createPinia } from "pinia";
import axios from "axios";

// Django CSRF integration (Inertia uses axios under the hood).
axios.defaults.xsrfCookieName = "csrftoken";
axios.defaults.xsrfHeaderName = "X-CSRFTOKEN";

// Lazy glob: each page becomes its own chunk, fetched on first visit,
// instead of one eager bundle that ships all pages on first paint.
const pages = import.meta.glob("../pages/**/*.vue");

createInertiaApp({
  resolve: (name) => {
    const page = pages[`../pages/${name}.vue`];
    if (!page) {
      throw new Error(`Inertia page not found: ${name}`);
    }
    return page();
  },
  setup({ el, App, props, plugin }) {
    createApp({ render: () => h(App, props) })
      .use(plugin)
      .use(createPinia())
      .mount(el);
  },
  progress: {
    color: "#ff2d2d",
  },
});
