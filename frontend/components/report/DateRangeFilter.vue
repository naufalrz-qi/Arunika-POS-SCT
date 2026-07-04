<script setup>
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";

// Shared date(+divisi) filter bar for report pages. `filters` is the reactive
// object from useReportFilters() — passed by reference so inputs here mutate
// it directly, no v-model plumbing needed in the parent page.
const props = defineProps({
  mode: { type: String, default: "range" }, // "single" | "range"
  filters: { type: Object, required: true },
  dateField: { type: String, default: "tanggal" },
  dateFromField: { type: String, default: "date_from" },
  dateToField: { type: String, default: "date_to" },
  divisiField: { type: String, default: "kd_divisi" },
  divisiOptions: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  submitLabel: { type: String, default: "Tarik Data" },
  inlineSubmit: { type: Boolean, default: true },
});
const emit = defineEmits(["submit"]);
</script>

<template>
  <div>
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <slot name="before" />
      <Select
        v-if="divisiOptions.length"
        v-model="filters[divisiField]"
        label="Divisi"
        :options="divisiOptions"
        placeholder="Semua Divisi"
      />
      <Input v-if="mode === 'single'" v-model="filters[dateField]" label="Per Tanggal" type="date" />
      <template v-else>
        <Input v-model="filters[dateFromField]" label="Dari Tanggal" type="date" />
        <Input v-model="filters[dateToField]" label="Sampai Tanggal" type="date" />
      </template>
      <div v-if="inlineSubmit" class="flex items-end">
        <Button class="w-full" :loading="loading" @click="emit('submit')">{{ submitLabel }}</Button>
      </div>
    </div>
    <div v-if="!inlineSubmit" class="mt-3 flex justify-end">
      <Button :loading="loading" @click="emit('submit')">{{ submitLabel }}</Button>
    </div>
  </div>
</template>
