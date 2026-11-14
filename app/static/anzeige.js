// Anzeigen für die Übenden: FAT mit FBF und die BMZ. Fragt jede Sekunde nach, ob sich die Anlage geändert hat.
(function () {
  "use strict";
  var root = document.getElementById("anzeige");
  if (!root) return;
  var token = root.dataset.token, v = 0, st = null, sicht = null;
  var istFat = !!document.getElementById("fat-lcd"), geraet = istFat ? "fat" : "bmz";
  var ebene = "alarm", pos = 0, folgen = true, alarmeVorher = 0;
  var TYPEN = { rm: "Rauchmelder", wm: "Wärmemelder", mm: "Mehrkriterienmelder", fm: "Flammenmelder", gm: "Gasmelder",
    lm: "Linearer Rauchmelder", ras: "Rauchansaugsystem", hfm: "Handfeuermelder", spr: "Sprinklergruppe" };
  var WORT = { alarm: "FEUER", stoerung: "STOERUNG", abschaltung: "ABSCH." };
  var NAME = { alarm: "Alarm", stoerung: "Störung", abschaltung: "Abschaltung" };

  function $(sel) { return document.querySelector(sel); }
  function all(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
  function pad(s, n) { s = String(s == null ? "" : s); return s.length >= n ? s.slice(0, n) : s + new Array(n - s.length + 1).join(" "); }
  function null3(n) { return String(n).padStart(3, "0"); }
  function nr(g, m) { return String(g).padStart(4, "0") + (m ? "/" + String(m).padStart(2, "0") : ""); }
  function uhr(iso) { return new Date(iso).toLocaleTimeString("de-DE"); }
  function jetzt(sek) {
    var d = new Date();
    return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" }) + "  " +
      d.toLocaleTimeString("de-DE", sek ? {} : { hour: "2-digit", minute: "2-digit" });
  }

  // Welche Meldungen eine Ebene zeigt. Die „ab"-Schalter des FBF zählen als Abschaltungen.
  function liste(art) {
    var l = st.meldungen.filter(function (m) { return m.art === art; });
    if (art === "abschaltung") {
      if (st.ue_ab) l.push({ art: art, gruppe: null, ort: "ÜE abgeschaltet", zeit: null });
      if (st.akustik_ab) l.push({ art: art, gruppe: null, ort: "Akustik abgeschaltet", zeit: null });
      if (st.bfs_ab) l.push({ art: art, gruppe: null, ort: "Steuerungen ab", zeit: null });
    }
    return l;
  }

  // ---------- Ton ----------
  var audio = null, tonAn = false, takt = null;
  function piep() {
    if (!audio || !tonAn) return;
    var o = audio.createOscillator(), g = audio.createGain();
    o.type = "square"; o.frequency.value = 2300; g.gain.value = 0.04;
    o.connect(g); g.connect(audio.destination);
    o.start(); o.stop(audio.currentTime + 0.2);
  }
  function summer(an) {
    if (an && !takt) { piep(); takt = window.setInterval(piep, 700); }
    else if (!an && takt) { window.clearInterval(takt); takt = null; }
  }
  var tonKnopf = $("#ton");
  if (tonKnopf) tonKnopf.addEventListener("click", function () {
    tonAn = !tonAn;
    if (tonAn && !audio) { var K = window.AudioContext || window.webkitAudioContext; if (K) audio = new K(); }
    if (audio && audio.state === "suspended") audio.resume();
    tonKnopf.setAttribute("aria-pressed", tonAn ? "true" : "false");
    tonKnopf.textContent = tonAn ? "Ton aus" : "Ton ein";
    if (tonAn) piep();
  });

  // ---------- FAT: vier Zeilen zu je 20 Zeichen ----------
  function fatKopf(m, i) { return pad(m.gruppe ? nr(m.gruppe, m.melder) : "Anlage", 8) + pad(WORT[m.art], 9) + null3(i + 1); }
  function fatText(m) { return pad(m.ort || m.gname || "", 20); }
  function zeichneFat() {
    var l = liste(ebene), z = ["", "", "", ""];
    if (ebene === "alarm") {
      if (!l.length) z = [pad(root.dataset.name, 20), pad(root.dataset.nr, 20), "", pad(jetzt(false), 20)];
      else {
        z[0] = fatKopf(l[0], 0); z[1] = fatText(l[0]);
        if (l.length > 1) {
          if (folgen) pos = l.length - 1;
          pos = Math.max(1, Math.min(pos, l.length - 1));
          z[2] = fatKopf(l[pos], pos); z[3] = fatText(l[pos]);
        }
      }
    } else if (!l.length) {
      z[0] = ebene === "stoerung" ? "Keine Stoerung" : "Keine Abschaltung";
    } else {
      pos = Math.max(0, Math.min(pos, l.length - 1));
      z[0] = fatKopf(l[pos], pos); z[1] = fatText(l[pos]);
      if (l[pos + 1]) { z[2] = fatKopf(l[pos + 1], pos + 1); z[3] = fatText(l[pos + 1]); }
    }
    $("#fat-lcd").textContent = z.map(function (s) { return pad(s, 20); }).join("\n");
    $("#fat-ebene-name").textContent = "Ebene: " + NAME[ebene];
    return l.length > 2;
  }

  // ---------- BMZ: elf Zeilen zu je 48 Zeichen ----------
  function zeichneBmz() {
    var B = 48, l = liste(ebene), z = [];
    function zwei(n) { return String(n).padStart(2, "0"); }
    z.push(pad("FEUER: " + zwei(sicht.alarme) + "   STOERUNG: " + zwei(sicht.stoerungen) + "   ABSCHALTUNG: " + zwei(liste("abschaltung").length), B));
    z.push(pad(jetzt(true), B));
    z.push(new Array(B + 1).join("-"));
    if (!l.length) {
      z.push(ebene === "alarm" ? (sicht.stoerungen || liste("abschaltung").length ? "Kein Alarm" : "Anlage in Betrieb, keine Meldungen")
        : ebene === "stoerung" ? "Keine Störung" : "Keine Abschaltung");
    } else {
      pos = Math.max(0, Math.min(pos, l.length - 1));
      l.slice(pos, pos + 4).forEach(function (m, k) {
        var links = null3(pos + k + 1) + " " + pad(m.gruppe ? nr(m.gruppe, m.melder) : "Anlage", 8) +
          (m.art === "alarm" ? (TYPEN[m.typ] || "Melder") : NAME[m.art]);
        var rechts = m.zeit ? uhr(m.zeit) : "";
        z.push(pad(links, B - rechts.length - 1) + " " + rechts);
        z.push("    " + pad([m.etage, m.gname, m.ort].filter(function (s, i, a) { return s && a.indexOf(s) === i; }).join(" · "), B - 4));
      });
    }
    while (z.length < 11) z.push("");
    $("#bmz-lcd").textContent = z.slice(0, 11).map(function (s) { return pad(s, B); }).join("\n");
    all("[data-ebene]").forEach(function (b) { b.classList.toggle("on", b.dataset.ebene === ebene); b.setAttribute("aria-pressed", b.dataset.ebene === ebene); });
    return false;
  }

  function zeichnen() {
    if (!st) return;
    var weitere = istFat ? zeichneFat() : zeichneBmz();
    var summt = istFat ? st.summer_fat : st.summer_bmz;
    var leds = { alarm: sicht.alarme > 0, stoerung: sicht.stoerungen > 0, abschaltung: liste("abschaltung").length > 0, ue: st.ue,
      loesch: st.loesch, bfs_ab: st.bfs_ab, akustik_ab: st.akustik_ab, ue_ab: st.ue_ab, weitere: weitere };
    all("[data-led]").forEach(function (led) {
      led.classList.toggle("an", !!leds[led.dataset.led]);
      led.classList.toggle("blinkt", led.dataset.led === "alarm" && summt);
    });
    summer(summt);
  }

  function uebernehmen(d) {
    st = d.st; sicht = d.sicht; v = st.v;
    if (sicht.alarme > alarmeVorher) { ebene = "alarm"; folgen = true; pos = 0; }  // neuer Alarm holt die Alarm-Ebene nach vorn
    alarmeVorher = sicht.alarme;
    zeichnen();
  }
  function offline(an) { $("#offline").hidden = !an; }
  function holen() {
    fetch("/a/" + token + "/state?v=" + v, { cache: "no-store" })
      .then(function (r) { if (r.status === 204) return null; if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) { offline(false); if (d) uebernehmen(d); })
      .catch(function () { offline(true); })
      .then(function () { window.setTimeout(holen, 1000); });
  }
  function senden(g, aktion) {
    fetch("/a/" + token + "/aktion", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ geraet: g, aktion: aktion }) })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) { offline(false); uebernehmen(d); })
      .catch(function () { offline(true); });
  }

  // ---------- Bedienung ----------
  function schloss(knopfSel, geraetSel, zuText, aufText) {
    var knopf = $(knopfSel), kasten = $(geraetSel);
    if (!knopf) return;
    knopf.addEventListener("click", function () {
      var auf = kasten.classList.toggle("zu") === false;
      knopf.setAttribute("aria-pressed", auf ? "true" : "false");
      knopf.querySelector("span").textContent = auf ? aufText : zuText;
    });
  }
  schloss("#fbf-schloss", "#fbf", "Mit Feuerwehrschlüssel aufschließen", "Aufgeschlossen. Hier wieder verschließen");
  schloss("#bmz-schloss", "#bmz", "Bedienung freigeben", "Bedienung frei. Hier wieder sperren");

  document.addEventListener("click", function (ev) {
    var t = ev.target.closest("[data-aktion]");
    if (t) {
      var fbf = t.closest(".fbf"), bmz = t.closest(".bmz");
      var gesperrt = (fbf && fbf.classList.contains("zu")) || (bmz && bmz.classList.contains("zu") && t.classList.contains("gesperrt"));
      if (gesperrt) {  // erst aufschließen: das Schloss kurz hervorheben
        var s = (fbf || bmz).querySelector(".schloss");
        s.focus();
        return;
      }
      senden(t.dataset.geraet, t.dataset.aktion);
      return;
    }
    var e = ev.target.closest("[data-ebene]");
    if (e) { ebene = e.dataset.ebene; pos = 0; zeichnen(); return; }
    if (ev.target.closest("#fat-ebene")) {
      ebene = ebene === "alarm" ? "stoerung" : ebene === "stoerung" ? "abschaltung" : "alarm";
      pos = 0; folgen = true; zeichnen(); return;
    }
    if (ev.target.closest("#fat-auf, #bmz-auf")) { folgen = false; pos -= 1; zeichnen(); return; }
    if (ev.target.closest("#fat-ab, #bmz-ab")) { folgen = false; pos += 1; zeichnen(); }
  });

  window.setInterval(zeichnen, 1000);  // Uhrzeit in der Anzeige
  holen();
})();
