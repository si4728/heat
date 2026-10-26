(function () {
  "use strict";

  const form = document.querySelector(".maintenance-record-form");
  if (!form) return;
  const checkbox = form.querySelector("[name='exclude_plugged']");
  const select = form.querySelector("[name='tube_id']");
  const count = form.querySelector("#plugged-excluded-count");
  if (!checkbox || !select) return;

  function applyPluggedFilter() {
    let excluded = 0;
    for (const option of select.options) {
      const isPlugged = option.dataset.status === "PLUGGED";
      const shouldExclude = checkbox.checked && isPlugged;
      option.hidden = shouldExclude;
      option.disabled = shouldExclude;
      if (shouldExclude) {
        excluded += 1;
        if (option.selected) select.value = "";
      }
    }
    if (count) count.textContent = String(excluded);
  }

  const actionType = form.querySelector("[name='action_type']");
  const newStatus = form.querySelector("[name='new_status']");
  function applyActionScope() {
    const replacement = actionType?.value === "REPLACEMENT";
    if (replacement) {
      select.value = "";
      if (newStatus) newStatus.value = "";
    }
    select.disabled = replacement;
    checkbox.disabled = replacement;
    if (newStatus) newStatus.disabled = replacement;
  }
  actionType?.addEventListener("change", applyActionScope);
  applyActionScope();
  checkbox.addEventListener("change", applyPluggedFilter);
  applyPluggedFilter();
})();
