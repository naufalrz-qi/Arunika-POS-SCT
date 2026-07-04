<script setup>
import Select from "@/components/ui/Select.vue";
defineProps({
  modelValue: { type: [String, Number, null], default: "" },
  label: { type: String, default: "Status" },
});
defineEmits(["update:modelValue"]);
const options = [
  { value: "1", label: "Aktif" },
  { value: "0", label: "Non-aktif" },
  { value: "2", label: "Tidak dijual" },
];
</script>

<template>
  <Select
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', $event)"
    :label="label"
    :options="options"
    placeholder="Semua status"
  />
</template>
