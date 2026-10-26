(() => {
  const plantSelect = document.getElementById("import-plant-code");
  const unitSelect = document.getElementById("import-unit-code");
  if (!plantSelect || !unitSelect) return;

  const syncProductionLines = () => {
    const selectedPlant = plantSelect.value;
    let selectedUnitIsAvailable = false;
    Array.from(unitSelect.options).forEach((option, index) => {
      if (index === 0) return;
      const available = Boolean(selectedPlant) && option.dataset.plant === selectedPlant;
      option.hidden = !available;
      option.disabled = !available;
      if (available && option.selected) selectedUnitIsAvailable = true;
    });
    if (!selectedUnitIsAvailable) unitSelect.value = "";
    unitSelect.disabled = !selectedPlant;
  };

  plantSelect.addEventListener("change", syncProductionLines);
  syncProductionLines();
})();
