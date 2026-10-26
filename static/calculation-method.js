(function () {
  const selector = document.querySelector('[name="calculation_method"]');
  if (!selector) return;
  const groups = document.querySelectorAll('[data-calculation-fields]');
  function refresh() {
    groups.forEach((group) => {
      const active = group.dataset.calculationFields === selector.value;
      group.hidden = !active;
      group.querySelectorAll('input, select').forEach((control) => {
        control.disabled = !active;
      });
    });
  }
  selector.addEventListener('change', refresh);
  refresh();
})();
