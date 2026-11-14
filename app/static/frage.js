// Rückfrage vor dem Löschen: Knöpfe mit data-frage fragen erst nach.
document.addEventListener("click", function (ev) {
  var knopf = ev.target.closest("[data-frage]");
  if (knopf && !window.confirm(knopf.dataset.frage)) ev.preventDefault();
});
