// Ausbilderansicht: Melder auslösen, Zustand der Anlage und Protokoll anzeigen.
(function () {
  "use strict";
  var root = document.getElementById("leitstand");
  if (!root) return;
  var id = root.dataset.id, csrf = root.dataset.csrf, v = 0, st = null;
  var ARTEN = { alarm: "Feuer", stoerung: "Störung", abschaltung: "Abschaltung" };
  var TYPEN = { rm: "Rauchmelder", wm: "Wärmemelder", mm: "Mehrkriterienmelder", fm: "Flammenmelder", gm: "Gasmelder",
    lm: "Linearer Rauchmelder", ras: "Rauchansaugsystem", hfm: "Handfeuermelder", spr: "Sprinklergruppe" };

  function $(sel) { return document.querySelector(sel); }
  function all(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function nr(g, m) { return String(g).padStart(4, "0") + (m ? "/" + String(m).padStart(2, "0") : ""); }
  function uhr(iso) { return new Date(iso).toLocaleTimeString("de-DE"); }
  function offline(an) { $("#offline").hidden = !an; }

  function antwort(r) {
    if (r.status === 401) { window.location.href = "/login"; throw new Error("abgemeldet"); }
    if (r.status === 204) return null;
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }
  function senden(body) {
    return fetch("/objekte/" + id + "/aktion", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF": csrf }, body: JSON.stringify(body) })
      .then(antwort).then(function (d) { offline(false); if (d) zeigen(d); })
      .catch(function () { offline(true); });
  }
  function holen() {
    fetch("/objekte/" + id + "/state?v=" + v, { credentials: "same-origin" })
      .then(antwort).then(function (d) { offline(false); if (d) zeigen(d); })
      .catch(function () { offline(true); })
      .then(function () { window.setTimeout(holen, 1000); });
  }

  function zeigen(d) {
    st = d.st; v = st.v;
    var sicht = d.sicht, proEtage = {};

    // Melder und Gruppen einfärben
    all(".chip").forEach(function (chip) {
      var g = Number(chip.dataset.g), m = Number(chip.dataset.m), klassen = { alarm: false, stoerung: false, ab: false, geplant: false };
      st.meldungen.forEach(function (x) {
        if (x.gruppe !== g) return;
        if (x.art === "alarm" && x.melder === m) klassen.alarm = true;
        if (x.art === "stoerung" && x.melder === m) klassen.stoerung = true;
        if (x.art === "abschaltung" && (x.melder === null || x.melder === m)) klassen.ab = true;
      });
      st.geplant.forEach(function (p) { if (p.ziel.gruppe === g && p.ziel.melder === m) klassen.geplant = true; });
      Object.keys(klassen).forEach(function (k) { chip.classList.toggle(k, klassen[k]); });
      chip.setAttribute("aria-pressed", klassen.alarm ? "true" : "false");
    });
    all(".gruppe").forEach(function (box) {
      var g = Number(box.dataset.g);
      var ab = st.meldungen.some(function (x) { return x.art === "abschaltung" && x.gruppe === g && x.melder === null; });
      box.classList.toggle("ab", ab);
      box.querySelector("[data-gruppe-ab]").textContent = ab ? "Gruppe einschalten" : "Gruppe abschalten";
    });

    // Lampen
    var lampen = { ue: st.ue, akustik: sicht.akustik_aktiv, bfs: sicht.bfs_aktiv, loesch: st.loesch, ue_ab: st.ue_ab,
      akustik_ab: st.akustik_ab, bfs_ab: st.bfs_ab, summer: st.summer_fat || st.summer_bmz };
    all("#lampen li").forEach(function (li) { li.classList.toggle("an", !!lampen[li.dataset.l]); });
    var lage = $("#lage");
    if (sicht.alarme) { lage.textContent = sicht.alarme + (sicht.alarme === 1 ? " Alarm" : " Alarme"); lage.className = "tag fehler"; }
    else if (sicht.normal) { lage.textContent = "Ruhe"; lage.className = "tag gesendet"; }
    else { lage.textContent = "nicht in Grundstellung"; lage.className = "tag test"; }
    var loesch = document.querySelector('[data-aktion="loeschanlage"]');
    if (loesch) loesch.textContent = st.loesch ? "Löschanlage: Auslösung beenden" : "Löschanlage auslösen";

    // Aktive Meldungen
    var liste = $("#meldungen");
    liste.textContent = "";
    st.meldungen.forEach(function (x) {
      var li = el("li", x.art), kopf = el("div", "kopf");
      kopf.appendChild(el("b", null, x.gruppe ? nr(x.gruppe, x.melder) : "Anlage"));
      kopf.appendChild(el("span", null, ARTEN[x.art] + (x.typ ? " · " + (TYPEN[x.typ] || x.typ) : "")));
      var t = el("time", null, uhr(x.zeit)); t.dateTime = x.zeit; kopf.appendChild(t);
      li.appendChild(kopf);
      li.appendChild(el("div", "ort", [x.etage, x.gname, x.ort].filter(function (s, i, a) { return s && a.indexOf(s) === i; }).join(" · ")));
      var tun = el("div", "tun");
      if (x.art === "alarm") {
        var u = el("button", "link", x.ansteht ? "Ursache steht an: jetzt beseitigen" : "Ursache als anstehend markieren");
        u.type = "button";
        u.addEventListener("click", function () { senden({ aktion: "ursache", id: x.id, ansteht: !x.ansteht }); });
        tun.appendChild(u);
        if (x.etage != null) proEtage[x.etage] = (proEtage[x.etage] || 0) + 1;
      }
      var weg = el("button", "link weg", x.art === "abschaltung" ? "Wieder einschalten" : "Entfernen");
      weg.type = "button";
      weg.addEventListener("click", function () { senden({ aktion: "entfernen", id: x.id }); });
      tun.appendChild(weg);
      li.appendChild(tun);
      liste.appendChild(li);
    });
    $("#anzahl").textContent = st.meldungen.length;
    $("#keine").hidden = st.meldungen.length > 0;
    all("#etagen button[data-etage]").forEach(function (b) {
      var zahl = b.querySelector("b");
      if (!zahl) return;
      var n = proEtage[b.dataset.etage] || 0;
      zahl.hidden = !n; zahl.textContent = n;
    });

    // Vorgemerkte Auslösungen
    var box = $("#vorgemerkt");
    box.hidden = !st.geplant.length;
    if (st.geplant.length) {
      var naechste = st.geplant.map(function (p) { return p.faellig; }).sort()[0];
      $("#vorgemerkt-text").textContent = st.geplant.length + (st.geplant.length === 1 ? " Auslösung" : " Auslösungen") +
        " vorgemerkt, die nächste um " + uhr(naechste) + ".";
    }

    // Protokoll
    if (d.protokoll) {
      var p = $("#protokoll");
      p.textContent = "";
      d.protokoll.forEach(function (z) {
        var li = el("li"), t = el("time", null, uhr(z.zeit)), rechts = el("span");
        t.dateTime = z.zeit;
        rechts.appendChild(el("b", null, z.quelle + ": "));
        rechts.appendChild(document.createTextNode(z.text));
        li.appendChild(t); li.appendChild(rechts); p.appendChild(li);
      });
    }
  }

  function modus() { return document.querySelector('input[name="modus"]:checked').value; }
  function zahl(sel) { return Math.max(0, parseInt($(sel).value, 10) || 0); }

  all('input[name="modus"]').forEach(function (r) {
    r.addEventListener("change", function () { $("#optionen").classList.toggle("aus", modus() !== "alarm"); });
  });

  document.addEventListener("click", function (ev) {
    if (ev.defaultPrevented) return;
    var chip = ev.target.closest(".chip");
    if (chip) {
      var mid = Number(chip.dataset.melder);
      if (modus() === "alarm") senden({ aktion: "alarm", melder_id: mid, sekunden: zahl("#sekunden"), ausbreitung: zahl("#ausbreitung"), ansteht: $("#ansteht").checked });
      else if (modus() === "stoerung") senden({ aktion: "stoerung", melder_id: mid, text: "Melder gestört" });
      else senden({ aktion: "abschaltung", melder_id: mid });
      return;
    }
    var gab = ev.target.closest("[data-gruppe-ab]");
    if (gab) { senden({ aktion: "abschaltung", gruppe_id: Number(gab.dataset.gruppeAb) }); return; }
    var stoer = ev.target.closest("[data-stoerung]");
    if (stoer) { senden({ aktion: "stoerung", text: stoer.dataset.stoerung }); return; }
    var akt = ev.target.closest("[data-aktion]");
    if (akt) {
      var body = { aktion: akt.dataset.aktion };
      if (body.aktion === "loeschanlage") body.an = !(st && st.loesch);
      senden(body);
      return;
    }
    var et = ev.target.closest("#etagen button");
    if (et) {
      all("#etagen button").forEach(function (b) { b.classList.toggle("on", b === et); });
      all(".etage").forEach(function (e) { e.hidden = et.dataset.etage !== "*" && e.dataset.etage !== et.dataset.etage; });
    }
  });

  holen();
})();
