// Dynamic query-param names for a report's advanced column filters, mirroring
// apps/core/reporting.py::parse_column_filters()'s per-type param naming.
// filterDefs: [{key, type: 'text'|'number_range'|'date'|'category', ...}]
export function paramNamesFor(filterDefs) {
  const names = [];
  for (const def of filterDefs) {
    if (def.type === "number_range") {
      names.push(`f_${def.key}_min`, `f_${def.key}_max`);
    } else if (def.type === "date") {
      names.push(`f_${def.key}_mode`, `f_${def.key}_from`, `f_${def.key}_to`, `f_${def.key}_date`);
    } else {
      names.push(`f_${def.key}`);
    }
  }
  return names;
}
