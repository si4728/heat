(() => {
  const modal = document.getElementById("dashboard-metric-modal");
  if (!modal) return;

  const dialog = modal.querySelector(".dashboard-metric-modal");
  const title = document.getElementById("dashboard-metric-title");
  const value = document.getElementById("dashboard-metric-value");
  const definition = document.getElementById("dashboard-metric-definition");
  const basis = document.getElementById("dashboard-metric-basis");
  const formula = document.getElementById("dashboard-metric-formula");
  const note = document.getElementById("dashboard-metric-note");
  const link = document.getElementById("dashboard-metric-link");
  let opener = null;

  const close = () => {
    modal.hidden = true;
    document.body.style.overflow = "";
    opener?.focus();
  };

  document.querySelectorAll(".metric-number").forEach((button) => {
    button.addEventListener("click", () => {
      opener = button;
      title.textContent = button.dataset.metricTitle || "지표 설명";
      value.textContent = button.dataset.metricValue || "0";
      definition.textContent = button.dataset.metricDefinition || "";
      basis.textContent = button.dataset.metricBasis || "";
      formula.textContent = button.dataset.metricFormula || "";
      note.textContent = button.dataset.metricNote || "";
      if (button.dataset.metricLink) {
        link.hidden = false;
        link.href = button.dataset.metricLink;
        link.textContent = button.dataset.metricLinkLabel || "관련 화면 보기";
      } else {
        link.hidden = true;
        link.removeAttribute("href");
      }
      modal.hidden = false;
      document.body.style.overflow = "hidden";
      dialog?.focus();
    });
  });

  modal.querySelectorAll("[data-dashboard-metric-close]").forEach((button) => {
    button.addEventListener("click", close);
  });
  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) close();
  });
})();
