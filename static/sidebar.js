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

  applyState(readPreference(), false);
  toggle.addEventListener("click", function () {
    applyState(!shell.classList.contains("sidebar-collapsed"), true);
  });
})();
