(() => {
  const modal = document.getElementById("pattern-help-modal");
  if (!modal) return;

  const openButtons = document.querySelectorAll("[data-pattern-help-open]");
  const closeButtons = modal.querySelectorAll("[data-pattern-help-close]");
  let previousFocus = null;

  const open = () => {
    previousFocus = document.activeElement;
    modal.hidden = false;
    modal.querySelector("[data-pattern-help-close]")?.focus();
  };
  const close = () => {
    modal.hidden = true;
    if (previousFocus instanceof HTMLElement) previousFocus.focus();
  };

  openButtons.forEach((button) => button.addEventListener("click", open));
  closeButtons.forEach((button) => button.addEventListener("click", close));
  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) close();
  });
})();
