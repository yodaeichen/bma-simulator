// Laufkarte bearbeiten: Standort der FIZ, Laufwege und Melder durch Klicken in den Plan setzen.
(function () {
  "use strict";
  var form = document.getElementById("lk-edit");
  if (!form) return;
  var d = JSON.parse(form.dataset.daten);
  var wahl = document.getElementById("melder-wahl");
  var NS = "http://www.w3.org/2000/svg";
  // Welches Werkzeug auf welchem Plan arbeitet: Liegt die Gruppe in der Etage der FIZ, gibt es nur einen Plan.
  var SEITE = { fiz: "1", weg1: "1", weg2: "2", melder: d.gleich ? "1" : "2" };

  function werkzeug() { return form.querySelector('input[name="werkzeug"]:checked').value; }
  function melder(id) { return d.melder.filter(function (m) { return String(m.id) === String(id); })[0]; }
  function marke(ebene, klasse, x, y, text) {
    var i = document.createElement("i");
    i.className = "m " + klasse;
    i.style.left = (x * 100) + "%"; i.style.top = (y * 100) + "%";
    if (text != null) i.textContent = text;
    ebene.appendChild(i);
  }
  function weg(ebene, punkte, aktiv) {
    if (punkte.length > 1) {
      var svg = document.createElementNS(NS, "svg"), linie = document.createElementNS(NS, "polyline");
      svg.setAttribute("viewBox", "0 0 1000 1000"); svg.setAttribute("preserveAspectRatio", "none");
      linie.setAttribute("points", punkte.map(function (p) { return (p[0] * 1000) + "," + (p[1] * 1000); }).join(" "));
      svg.appendChild(linie); ebene.appendChild(svg);
    }
    punkte.forEach(function (p, n) { marke(ebene, n === punkte.length - 1 ? "ziel" : "punkt" + (aktiv ? " aktiv" : ""), p[0], p[1]); });
  }
  function zeichnen() {
    var w = werkzeug();
    Array.prototype.forEach.call(form.querySelectorAll(".plan.edit"), function (plan) {
      var ebene = plan.querySelector(".ebene"), seite = plan.dataset.seite;
      ebene.textContent = "";
      weg(ebene, seite === "1" ? d.weg1 : d.weg2, w === (seite === "1" ? "weg1" : "weg2"));
      if (seite === "1" && d.fiz) marke(ebene, "fiz", d.fiz[0], d.fiz[1], "FIZ");
      if (seite === SEITE.melder) d.melder.forEach(function (m) {
        if (m.x != null) marke(ebene, "melder" + (m.hfm ? " hfm" : "") + (w === "melder" && String(m.id) === wahl.value ? " gewaehlt" : ""), m.x, m.y, m.nr);
      });
      plan.classList.toggle("aktiv", SEITE[w] === seite);
    });
    Array.prototype.forEach.call(wahl.options, function (o) {
      var m = melder(o.value);
      o.textContent = o.textContent.replace(/ ✓$/, "") + (m.x != null ? " ✓" : "");
    });
  }

  form.addEventListener("click", function (ev) {
    var plan = ev.target.closest(".plan.edit");
    if (!plan) return;
    var w = werkzeug();
    if (SEITE[w] !== plan.dataset.seite) return;
    var r = plan.querySelector("img").getBoundingClientRect();
    if (!r.width || !r.height) return;
    var p = [Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height))];
    p = [Math.round(p[0] * 10000) / 10000, Math.round(p[1] * 10000) / 10000];
    if (w === "fiz") d.fiz = p;
    else if (w === "weg1" || w === "weg2") { if (d[w].length < 60) d[w].push(p); }
    else {
      var m = melder(wahl.value);
      if (m) { m.x = p[0]; m.y = p[1]; }
      var frei = d.melder.filter(function (x) { return x.x == null; })[0];  // gleich zum nächsten Melder ohne Lage
      if (frei) wahl.value = String(frei.id);
    }
    zeichnen();
  });
  document.getElementById("zurueck").addEventListener("click", function () {
    var w = werkzeug();
    if (w === "weg1" || w === "weg2") d[w].pop();
    zeichnen();
  });
  document.getElementById("leeren").addEventListener("click", function () {
    var w = werkzeug();
    if (w === "weg1" || w === "weg2") d[w] = [];
    zeichnen();
  });
  document.getElementById("melder-weg").addEventListener("click", function () {
    var m = melder(wahl.value);
    if (m) { m.x = null; m.y = null; }
    zeichnen();
  });
  form.addEventListener("change", function (ev) {
    if (ev.target === wahl) form.querySelector('input[value="melder"]').checked = true;
    zeichnen();
  });
  form.addEventListener("submit", function () {
    var lagen = {};
    d.melder.forEach(function (m) { lagen[m.id] = m.x != null ? [m.x, m.y] : null; });
    form.elements.fiz.value = JSON.stringify(d.fiz || null);
    form.elements.weg1.value = JSON.stringify(d.weg1);
    form.elements.weg2.value = JSON.stringify(d.weg2);
    form.elements.melder.value = JSON.stringify(lagen);
  });
  zeichnen();
})();
