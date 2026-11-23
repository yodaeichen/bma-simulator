// Szenario bearbeiten: Schritte hinzufügen und entfernen; Felder, die für die Art des Schritts nicht gelten, ausgrauen.
(function () {
  "use strict";
  var tabelle = document.querySelector("#schritte tbody");
  if (!tabelle) return;
  function anpassen(zeile) {
    var art = zeile.querySelector('[name="aktion"]').value;
    zeile.querySelector('[name="text"]').disabled = art !== "stoerung";
    zeile.querySelector('[name="ansteht"]').disabled = art !== "alarm";
    zeile.querySelector('[name="ziel"]').disabled = art === "loeschanlage";
  }
  function alle() { Array.prototype.forEach.call(tabelle.rows, anpassen); }
  document.getElementById("sz-plus").addEventListener("click", function () {
    var letzte = tabelle.rows[tabelle.rows.length - 1], neu = letzte.cloneNode(true);
    var zeit = neu.querySelector('[name="sek"]');
    zeit.value = String((parseInt(letzte.querySelector('[name="sek"]').value, 10) || 0) + 30);
    neu.querySelector('[name="text"]').value = "";
    tabelle.appendChild(neu);
    anpassen(neu);
    zeit.focus();
  });
  tabelle.addEventListener("click", function (ev) {
    if (!ev.target.closest("[data-weg]")) return;
    if (tabelle.rows.length > 1) ev.target.closest("tr").remove();
  });
  tabelle.addEventListener("change", function (ev) { var z = ev.target.closest("tr"); if (z) anpassen(z); });
  // Ausgegraute Felder würden nicht mitgeschickt; die Listen müssen aber gleich lang bleiben
  document.getElementById("sz-form").addEventListener("submit", function () {
    Array.prototype.forEach.call(tabelle.querySelectorAll("[disabled]"), function (f) { f.disabled = false; });
  });
  alle();
})();
