(function () {
  "use strict";

  const shell = document.querySelector(".app-shell");
  const toggle = document.querySelector(".sidebar-toggle");
  if (!shell || !toggle) return;

  const storageKey = "hx-manager-sidebar-collapsed";

  function readPreference() {
    try {
      return window.localStorage.getItem(storageKey) === "true";
    } catch (_error) {
      return false;
    }
  }

  function savePreference(collapsed) {
    try {
      window.localStorage.setItem(storageKey, String(collapsed));
    } catch (_error) {
      // Storage may be disabled; the current page state still works.
    }
  }

  function applyState(collapsed, persist) {
    shell.classList.toggle("sidebar-collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.title = collapsed ? "왼쪽 메뉴 펼치기" : "왼쪽 메뉴 접기";
    toggle.querySelector("[aria-hidden='true']").textContent = collapsed ? "›" : "‹";
    toggle.querySelector(".sr-only").textContent = toggle.title;
    if (persist) savePreference(collapsed);
  }

  const narrow = window.matchMedia('(max-width:1100px)');
  const pageMode = shell.dataset.sidebarMode || 'auto';
  let manualState = null;
  function preferredState() {
    if (manualState !== null) return manualState;
    if (pageMode === 'collapsed') return true;
    if (pageMode === 'expanded') return false;
    return narrow.matches || readPreference();
  }
  const equipmentPicker = document.querySelector('details.analysis-equipment-panel');
  if (equipmentPicker && narrow.matches) equipmentPicker.open = false;
  applyState(preferredState(), false);
  narrow.addEventListener('change', () => {
    applyState(preferredState(), false);
    if (equipmentPicker) equipmentPicker.open = !narrow.matches;
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && narrow.matches) {
      manualState = true;
      applyState(true, false);
    }
  });
  toggle.addEventListener("click", function () {
    manualState = !shell.classList.contains("sidebar-collapsed");
    applyState(manualState, true);
  });
})();
