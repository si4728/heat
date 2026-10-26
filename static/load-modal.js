(() => {
  const modal = document.getElementById("load-result-modal");
  if (!modal) return;
  const close = () => {
    modal.hidden = true;
    document.body.style.overflow = "";
  };
  document.body.style.overflow = "hidden";
  modal.querySelectorAll("[data-modal-close]").forEach((button) => button.addEventListener("click", close));
  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) close();
  });
  modal.querySelector("[data-modal-close]")?.focus();
})();
