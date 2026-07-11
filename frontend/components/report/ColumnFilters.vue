<script setup>
import { computed } from "vue";
import Input from "@/components/ui/Input.vue";
import NumberRangeField from "@/components/ui/NumberRangeField.vue";
import DateModeField from "@/components/ui/DateModeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";

// filterDefs: [{key, label, type: 'text'|'number_range'|'date'|'category', options?}]
// form: the reactive object from useServerReport() — field names follow
// frontend/utils/reportFilters.js::paramNamesFor() for each type.
// types: subset of def types to render (e.g. ['number_range']); null renders all,
// so pages can split one filterDefs array across several FilterSection blocks.
const props = defineProps({
  filterDefs: { type: Array, default: () => [] },
  form: { type: Object, required: true },
  types: { type: Array, default: null },
});
const defs = computed(() =>
  props.types ? props.filterDefs.filter((d) => props.types.includes(d.type)) : props.filterDefs,
);
</script>

<template>
  <template v-for="def in defs" :key="def.key">
    <Input
      v-if="def.type === 'text'"
      :label="def.label"
      :model-value="form['f_' + def.key]"
      @update:model-value="form['f_' + def.key] = $event"
    />
    <NumberRangeField
      v-else-if="def.type === 'number_range'"
      :label="def.label"
      :min="form['f_' + def.key + '_min']"
      :max="form['f_' + def.key + '_max']"
      @update:min="form['f_' + def.key + '_min'] = $event"
      @update:max="form['f_' + def.key + '_max'] = $event"
    />
    <DateModeField
      v-else-if="def.type === 'date'"
      :label="def.label"
      :mode="form['f_' + def.key + '_mode'] || 'range'"
      :from="form['f_' + def.key + '_from']"
      :to="form['f_' + def.key + '_to']"
      :date="form['f_' + def.key + '_date']"
      @update:mode="form['f_' + def.key + '_mode'] = $event"
      @update:from="form['f_' + def.key + '_from'] = $event"
      @update:to="form['f_' + def.key + '_to'] = $event"
      @update:date="form['f_' + def.key + '_date'] = $event"
    />
    <SelectSearch
      v-else-if="def.type === 'category'"
      :label="def.label"
      :options="def.options || []"
      :model-value="form['f_' + def.key]"
      @update:model-value="form['f_' + def.key] = $event"
    />
  </template>
</template>
