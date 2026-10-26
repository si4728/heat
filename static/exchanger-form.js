(() => {
  const processSelect = document.getElementById("organization-process");
  const showUnconnected = document.getElementById("show-unconnected-processes");
  if (processSelect && showUnconnected) {
    showUnconnected.checked = processSelect.selectedOptions[0]?.dataset.unconnected === "true";
    const updateChoices = () => {
      for (const option of processSelect.options) {
        const hidden = option.dataset.unconnected === "true" && !showUnconnected.checked && !option.selected;
        option.hidden = hidden;
        option.disabled = hidden;
      }
    };
    showUnconnected.addEventListener("change", updateChoices);
    processSelect.addEventListener("change", updateChoices);
    updateChoices();
  }
  const installDate = document.getElementById("install-date");
  const manufacturingDate = document.getElementById("manufacturing-date-derived");
  const commissioningDate = document.getElementById("commissioning-date-derived");
  if (!installDate || !manufacturingDate || !commissioningDate) return;

  function updateDerivedDates() {
    const value = installDate.value;
    commissioningDate.value = value;
    if (!value) {
      manufacturingDate.value = "";
      return;
    }
    const date = new Date(`${value}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() - 3);
    manufacturingDate.value = date.toISOString().slice(0, 10);
  }

  installDate.addEventListener("input", updateDerivedDates);
  updateDerivedDates();
})();
