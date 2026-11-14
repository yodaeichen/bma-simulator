// Knöpfe mit data-drucken öffnen den Druckdialog des Browsers.
document.addEventListener("click", function (ev) {
  if (ev.target.closest("[data-drucken]")) window.print();
});
