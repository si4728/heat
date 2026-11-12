(() => {
  const criticality = document.querySelector('[name="process_criticality"]');
  const automaticLimit = document.getElementById('management-plugging-limit-range');
  if (criticality && automaticLimit) {
    const synchronize = () => {
      automaticLimit.value = criticality.value === 'CRITICAL' ? '10' : '20';
      automaticLimit.dispatchEvent(new Event('input', {bubbles: true}));
    };
    criticality.addEventListener('change', synchronize);
    synchronize();
  }
  document.querySelectorAll("[data-plugging-limit-range]").forEach((range) => {
    const output = range.closest("label")?.querySelector("output");
    if (!output) return;
    const refresh = () => {
      output.value = `${range.value}%`;
      output.textContent = output.value;
    };
    range.addEventListener("input", refresh);
    refresh();
  });
})();
