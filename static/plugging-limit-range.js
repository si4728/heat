(() => {
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
