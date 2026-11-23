// Anzeigen für die Übenden: FAT mit FBF und die BMZ. Fragt jede Sekunde nach, ob sich die Anlage geändert hat.
(function () {
  "use strict";
  var root = document.getElementById("anzeige");
  if (!root) return;
  var token = root.dataset.token, v = 0, st = null, sicht = null;
  var istFat = !!document.getElementById("fat-lcd"), geraet = istFat ? "fat" : "bmz";
  var ebene = "alarm", pos = 0, folgen = true, alarmeVorher = 0;
  var letzteBedienung = Date.now(), test = false, erklaeren = false;
  var gesehen = { stoerung: 0, abschaltung: 0 };  // höchste angesehene Nummer je Ebene: Neues blinkt, bis es angesehen wurde
  var RUECKKEHR_MS = 20000, HALTEN_MS = 5000;
  // Für das Live-Bild des Ausbilders: Kennung dieses Geräts, Text der Anzeige, zuletzt gedrückte Taste
  var cid = "", lcdText = "", lcdGesendet = null, runde = 0, tasteNr = 0, tasteName = "", aufgeschlossen = false;
  try { cid = window.sessionStorage.getItem("bma-geraet") || ""; } catch (e) { /* ohne Speicher: neue Kennung je Seite */ }
  if (!/^[a-z0-9]{8}$/.test(cid)) {
    cid = Math.random().toString(36).slice(2, 10).padEnd(8, "0");
    try { window.sessionStorage.setItem("bma-geraet", cid); } catch (e) { /* egal */ }
  }
  function taste(name) { tasteNr += 1; tasteName = String(name).replace(/\s+/g, " ").trim().slice(0, 60); letzteBedienung = Date.now(); }
  var TYPEN = { rm: "Rauchmelder", wm: "Wärmemelder", mm: "Mehrkriterienmelder", fm: "Flammenmelder", gm: "Gasmelder",
    lm: "Linearer Rauchmelder", ras: "Rauchansaugsystem", hfm: "Handfeuermelder", spr: "Sprinklergruppe" };
  var WORT = { alarm: "FEUER", stoerung: "STOERUNG", abschaltung: "ABSCH." };
  var KURZ = { alarm: "FEUER", stoerung: "STOER.", abschaltung: "ABSCH.", rueck: "RUECK." };
  var NAME = { alarm: "Alarm", stoerung: "Störung", abschaltung: "Abschaltung", historie: "Historie" };
  var UEBER = { alarm: "Meldergruppe / Melder", stoerung: "Störungen", abschaltung: "Abschaltungen", historie: "Historie" };

  function $(sel) { return document.querySelector(sel); }
  function all(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
  function pad(s, n) { s = String(s == null ? "" : s); return s.length >= n ? s.slice(0, n) : s + new Array(n - s.length + 1).join(" "); }
  function null3(n) { return String(n).padStart(3, "0"); }
  function nr(g, m) { return String(g).padStart(4, "0") + (m ? "/" + String(m).padStart(2, "0") : ""); }
  function uhr(iso) { return new Date(iso).toLocaleTimeString("de-DE"); }
  function hhmm(iso) { return new Date(iso).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }); }
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
  function hoechste(art) {
    return st.meldungen.reduce(function (n, m) { return m.art === art && m.id > n ? m.id : n; }, 0);
  }

  // ---------- Ton: Summer des Geräts und Hausalarm (Töne aus dem Projekt safetydaysBMA, MIT-Lizenz) ----------
  function ton(datei) {
    var a = null;
    try { a = new Audio(datei); a.loop = true; a.preload = "auto"; } catch (e) { a = null; }
    return a;
  }
  var summerTon = ton("/static/ton/summer.wav"), hausTon = ton("/static/ton/hausalarm.wav");
  var summerAn = false, hausAn = false;
  function spielen(a, soll) {
    if (!a) return;
    if (soll && a.paused) { var p = a.play(); if (p && p.catch) p.catch(function () {}); }
    else if (!soll && !a.paused) { a.pause(); a.currentTime = 0; }
  }
  function schalterKnopf(id, ein, aus, wert, setzen) {
    var k = document.getElementById(id);
    if (!k) return;
    k.addEventListener("click", function () {
      var neu = !wert();
      setzen(neu);
      k.setAttribute("aria-pressed", neu ? "true" : "false");
      k.textContent = neu ? aus : ein;
      taste(neu ? ein.replace(" ein", " eingeschaltet") : aus.replace(" aus", " ausgeschaltet"));
      zeichnen();
    });
  }
  schalterKnopf("ton", "Summer-Ton ein", "Summer-Ton aus", function () { return summerAn; }, function (x) { summerAn = x; });
  schalterKnopf("hausalarm", "Hausalarm ein", "Hausalarm aus", function () { return hausAn; }, function (x) { hausAn = x; });

  // ---------- FAT: vier Zeilen zu je 20 Zeichen ----------
  function fatKopf(m, i) { return pad(m.gruppe ? nr(m.gruppe, m.melder) : "Anlage", 8) + pad(WORT[m.art], 9) + null3(i + 1); }
  function fatText(m) { return pad(m.ort || m.gname || "", 20); }
  function zeichneFat() {
    var z = ["", "", "", ""], weitere = false, l;
    if (test) {
      z = ["", "", "", ""];
    } else if (ebene === "historie") {
      l = (st.historie || []).slice().reverse();
      if (!l.length) z[0] = "Historie leer";
      else {
        pos = Math.max(0, Math.min(pos, l.length - 1));
        [l[pos], l[pos + 1]].forEach(function (h, k) {
          if (!h) return;
          z[k * 2] = pad(h.gruppe ? nr(h.gruppe, h.melder) : (h.art === "rueck" ? "BMZ" : "Anlage"), 8) + pad(KURZ[h.art] || "", 7) + hhmm(h.zeit);
          z[k * 2 + 1] = pad(h.ort, 20);
        });
        weitere = l.length > 2;
      }
    } else {
      l = liste(ebene);
      weitere = l.length > 2;
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
      } else {
        gesehen[ebene] = Math.max(gesehen[ebene], hoechste(ebene));
        if (!l.length) z[0] = ebene === "stoerung" ? "** Keine Stoerung **" : "** Keine Abschaltung";
        else {
          pos = Math.max(0, Math.min(pos, l.length - 1));
          z[0] = fatKopf(l[pos], pos); z[1] = fatText(l[pos]);
          if (l[pos + 1]) { z[2] = fatKopf(l[pos + 1], pos + 1); z[3] = fatText(l[pos + 1]); }
        }
      }
    }
    lcdText = z.map(function (s) { return pad(s, 20); }).join("\n");
    $("#fat-lcd").textContent = lcdText;
    $("#fat-lcd").classList.toggle("voll", test);
    if (test) lcdText = "[Anzeigetest]";
    $("#fat-ueber").textContent = test ? "Anzeigetest" : UEBER[ebene];
    return weitere;
  }

  // ---------- BMZ: elf Zeilen zu je 48 Zeichen ----------
  function zeichneBmz() {
    var B = 48, l = liste(ebene), z = [];
    function zwei(n) { return String(n).padStart(2, "0"); }
    if (ebene !== "alarm") gesehen[ebene] = Math.max(gesehen[ebene], hoechste(ebene));
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
    z = z.slice(0, 11).map(function (s) { return pad(s, B); });
    $("#bmz-lcd").textContent = z.join("\n");
    lcdText = [z[0]].concat(z.slice(3)).join("\n");  // ohne die Zeile mit der Uhrzeit, sonst ändert sich der Text jede Sekunde
    all("[data-ebene]").forEach(function (b) { b.classList.toggle("on", b.dataset.ebene === ebene); b.setAttribute("aria-pressed", b.dataset.ebene === ebene); });
    return false;
  }

  function zeichnen() {
    if (!st) return;
    // Ohne Bedienung kehrt die Anzeige nach einer Weile zur ersten und letzten Meldung zurück
    if (!test && (ebene !== "alarm" || !folgen) && Date.now() - letzteBedienung > RUECKKEHR_MS) { ebene = "alarm"; folgen = true; pos = 0; }
    var weitere = istFat ? zeichneFat() : zeichneBmz();
    var summt = istFat ? st.summer_fat : st.summer_bmz;
    var abschaltungen = liste("abschaltung").length;
    var leds = { betrieb: true, alarm: sicht.alarme > 0, stoerung: sicht.stoerungen > 0, abschaltung: abschaltungen > 0, ue: st.ue,
      loesch: st.loesch, bfs_ab: st.bfs_ab, akustik_ab: st.akustik_ab, ue_ab: st.ue_ab, weitere: weitere, brand: sicht.alarme > 0 };
    var blinkt = { alarm: summt, weitere: weitere, stoerung: hoechste("stoerung") > gesehen.stoerung,
      abschaltung: hoechste("abschaltung") > gesehen.abschaltung };
    all("[data-led]").forEach(function (led) {
      var name = led.dataset.led, imTest = test && led.closest(".fat");
      led.classList.toggle("an", !!(imTest || leds[name]));
      led.classList.toggle("blinkt", !imTest && !!blinkt[name]);
    });
    spielen(summerTon, summerAn && (summt || test));
    spielen(hausTon, hausAn && !!sicht.akustik_aktiv);
  }

  function uebernehmen(d) {
    st = d.st; sicht = d.sicht; v = st.v;
    if (sicht.alarme > alarmeVorher) { ebene = "alarm"; folgen = true; pos = 0; }  // neuer Alarm holt die Alarm-Ebene nach vorn
    alarmeVorher = sicht.alarme;
    zeichnen();
  }
  function offline(an) { $("#offline").hidden = !an; }
  function holen() {
    var mitText = lcdText !== lcdGesendet || (runde += 1) % 5 === 0, text = lcdText;
    var q = "/a/" + token + "/state?v=" + v + "&c=" + cid + "&g=" + geraet + "&e=" + ebene + "&o=" + (aufgeschlossen ? 1 : 0) +
      "&t=" + (summerAn ? 1 : 0) + "&h=" + (hausAn ? 1 : 0) + "&x=" + (erklaeren ? 1 : 0) +
      "&kn=" + tasteNr + "&k=" + encodeURIComponent(tasteName) + (mitText ? "&l=" + encodeURIComponent(text) : "");
    fetch(q, { cache: "no-store" })
      .then(function (r) { if (r.status === 204) return null; if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) { offline(false); if (mitText) lcdGesendet = text; if (d) uebernehmen(d); })
      .catch(function () { offline(true); })
      .then(function () { window.setTimeout(holen, 1000); });
  }
  function senden(g, aktion) {
    fetch("/a/" + token + "/aktion", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ geraet: g, aktion: aktion }) })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) { offline(false); uebernehmen(d); })
      .catch(function () { offline(true); });
  }

  // ---------- Tasten mit langem Druck (FAT): Anzeigeebene > 5 s = Historie, Summer ab > 5 s = Anzeigetest ----------
  function halten(knopf, beginn, lang, ende) {
    if (!knopf) return;
    var timer = null, gedrueckt = false, langErreicht = false;
    function los(ev) {
      if (erklaeren || gedrueckt) return;
      if (ev.type === "pointerdown") { if (ev.button !== 0) return; try { knopf.setPointerCapture(ev.pointerId); } catch (e) { /* egal */ } }
      gedrueckt = true; langErreicht = false;
      knopf.classList.add("gedrueckt");
      if (beginn) beginn();
      timer = window.setTimeout(function () { langErreicht = true; lang(); }, HALTEN_MS);
    }
    function aus() {
      if (!gedrueckt) return;
      gedrueckt = false;
      knopf.classList.remove("gedrueckt");
      window.clearTimeout(timer);
      ende(langErreicht);
    }
    knopf.addEventListener("pointerdown", los);
    knopf.addEventListener("pointerup", aus);
    knopf.addEventListener("pointercancel", aus);
    knopf.addEventListener("lostpointercapture", aus);
    knopf.addEventListener("keydown", function (ev) { if ((ev.key === " " || ev.key === "Enter") && !ev.repeat) { ev.preventDefault(); los(ev); } });
    knopf.addEventListener("keyup", function (ev) { if (ev.key === " " || ev.key === "Enter") { ev.preventDefault(); aus(); } });
    knopf.addEventListener("click", function (ev) { if (!erklaeren) ev.preventDefault(); });
    knopf.addEventListener("contextmenu", function (ev) { ev.preventDefault(); });  // langer Druck auf dem Tablet öffnet sonst ein Menü
  }
  halten($("#fat-ebene"), null, function () {
    ebene = "historie"; pos = 0; taste("Anzeigeebene > 5 s: Historie"); zeichnen();
  }, function (lang) {
    if (lang) return;
    ebene = ebene === "alarm" ? "stoerung" : ebene === "stoerung" ? "abschaltung" : "alarm";
    pos = 0; folgen = true; taste("Anzeigeebene"); zeichnen();
  });
  halten($("#fat-summer"), function () {
    taste("Summer ab");
    if (st && st.summer_fat) senden("fat", "summer_ab");
  }, function () {
    test = true; taste("Summer ab > 5 s: Anzeigetest"); zeichnen();
  }, function () {
    if (test) { test = false; letzteBedienung = Date.now(); zeichnen(); }
  });

  // ---------- Erklärmodus: Tippen erklärt das Bedienelement, statt es auszulösen ----------
  var ERKL = {
    "erste": ["Erste Meldung", "In den oberen beiden Zeilen steht immer die zuerst eingegangene Meldung: Meldergruppe und Melder, die Art der Meldung und ihre laufende Nummer, darunter der Ort. Zu dieser Meldergruppe die Laufkarte nehmen und erkunden."],
    "letzte": ["Letzte Meldung", "Die unteren beiden Zeilen zeigen die zuletzt eingegangene Meldung. Mit den Pfeiltasten lassen sich hier die Meldungen dazwischen anzeigen."],
    "weitere": ["Weitere Meldungen", "Leuchten die Pfeiltasten, sind mehr als zwei Meldungen eingegangen. ▼ blättert vor, ▲ zurück. Ohne Bedienung springt die Anzeige nach 20 Sekunden zurück auf erste und letzte Meldung."],
    "ebene": ["Anzeigeebene / Historie", "Wechselt zwischen den Ebenen Alarme, Störungen und Abschaltungen. Länger als 5 Sekunden gedrückt halten zeigt die Historie: alle Meldungen seit Übungsbeginn mit Uhrzeit, auch die schon rückgestellten."],
    "summer": ["Summer ab / Test", "Stellt den Summer des FAT ab. Er meldet sich bei jeder weiteren Meldung wieder. Länger als 5 Sekunden gedrückt halten startet den Anzeigetest: Alle Leuchten, die Anzeige und der Summer sind an, solange die Taste gedrückt bleibt."],
    "fat-leds": ["Betrieb, Alarm, Störung, Abschaltung", "Betrieb: Das FAT ist betriebsbereit. Alarm: Die BMZ ist im Brandmeldezustand. Störung: Mindestens eine Störung steht an. Abschaltung: Meldergruppen, Melder oder Funktionen der BMA sind abgeschaltet. Blinkt Störung oder Abschaltung, ist etwas Neues dazugekommen, das noch nicht angesehen wurde."],
    "fbf-betrieb": ["Bedienfeld in Betrieb", "Das Feuerwehr-Bedienfeld ist betriebsbereit."],
    "ue": ["ÜE ausgelöst", "Die Übertragungseinrichtung hat ausgelöst: Die Meldung ist bei der Leitstelle angekommen und das Feuerwehr-Schlüsseldepot ist entriegelt."],
    "loesch": ["Löschanlage ausgelöst", "Eine Löschanlage, zum Beispiel eine Sprinkleranlage, hat ausgelöst. Die Leuchte bleibt an, bis die Anlage zurückgestellt ist."],
    "bfs_ab": ["Brandfall-Steuerung ab", "Schaltet die Brandfallsteuerungen ab, also das, was die BMA im Brandfall im Gebäude auslöst: Aufzüge, Lüftung, Feststellanlagen von Türen. Das geht nur, solange die BMA nicht im Brandmeldezustand ist. Leuchtet die Taste, ist abgeschaltet; erneut drücken schaltet wieder ein."],
    "akustik_ab": ["Akustische Signale ab", "Schaltet die Alarmierung im Gebäude ab (Hausalarm, Räumungsalarm). Leuchtet die Taste, ist sie abgeschaltet; erneut drücken schaltet wieder ein. Bei einer weiteren Meldung schaltet sie sich nicht von selbst wieder ein."],
    "rueck": ["BMZ rückstellen", "Stellt die BMZ aus dem Brandmeldezustand zurück. Die Taste leuchtet rot, solange die BMZ im Brandmeldezustand ist. Erst zurückstellen, wenn die Ursache erkundet ist: Steht sie noch an, löst der Melder erneut aus."],
    "ue_ab": ["ÜE ab", "Schaltet die Ansteuerung der Übertragungseinrichtung ab. Neue Alarme gehen dann nicht mehr zur Leitstelle. Leuchtet die Taste, ist die ÜE abgeschaltet; erneut drücken schaltet sie wieder ein."],
    "ue_pruefen": ["ÜE Nr. … prüfen", "Steuert die Übertragungseinrichtung an, ohne dass die BMA in den Brandmeldezustand geht. Brandfallsteuerungen und Räumungsalarm bleiben aus. Im Feld steht die Nummer der Übertragungseinrichtung."],
    "schloss": ["Feuerwehrschließung", "Das Feuerwehr-Bedienfeld ist verschlossen. Erst mit dem Feuerwehrschlüssel aufschließen, dann lassen sich die Tasten bedienen."]
  };
  var erklKnopf = $("#erklaeren"), erklBox = $("#erklaerung");
  if (erklKnopf && erklBox) {
    erklKnopf.addEventListener("click", function () {
      erklaeren = !erklaeren;
      erklKnopf.setAttribute("aria-pressed", erklaeren ? "true" : "false");
      erklKnopf.textContent = erklaeren ? "Erklären beenden" : "Erklären";
      root.classList.toggle("erklaermodus", erklaeren);
      if (!erklaeren) erklBox.hidden = true;
      taste(erklaeren ? "Erklärmodus ein" : "Erklärmodus aus");
    });
    $("#erkl-zu").addEventListener("click", function () { erklBox.hidden = true; });
    document.addEventListener("click", function (ev) {
      if (!erklaeren) return;
      var ziel = ev.target.closest("#anzeige [data-erkl]");
      if (!ziel) return;
      ev.preventDefault(); ev.stopPropagation();
      var t = ERKL[ziel.dataset.erkl];
      if (!t) return;
      $("#erkl-titel").textContent = t[0];
      $("#erkl-text").textContent = t[1];
      erklBox.hidden = false;
      taste("Erklärung: " + t[0]);
    }, true);
  }

  // ---------- Bedienung ----------
  function schloss(knopfSel, geraetSel, zuText, aufText) {
    var knopf = $(knopfSel), kasten = $(geraetSel);
    if (!knopf) return;
    knopf.addEventListener("click", function () {
      var auf = kasten.classList.toggle("zu") === false;
      aufgeschlossen = auf;
      taste(auf ? "Aufgeschlossen" : "Verschlossen");
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
      var name = t.getAttribute("aria-label") || t.textContent;
      if (gesperrt) {  // erst aufschließen: das Schloss kurz hervorheben
        var s = (fbf || bmz).querySelector(".schloss");
        s.focus();
        taste(name + " (verschlossen)");
        return;
      }
      taste(name);
      senden(t.dataset.geraet, t.dataset.aktion);
      return;
    }
    var e = ev.target.closest("[data-ebene]");
    if (e) { ebene = e.dataset.ebene; pos = 0; taste("Anzeige: " + e.textContent); zeichnen(); return; }
    if (ev.target.closest("#fat-auf, #bmz-auf")) { folgen = false; pos -= 1; taste("Pfeil nach oben"); zeichnen(); return; }
    if (ev.target.closest("#fat-ab, #bmz-ab")) { folgen = false; pos += 1; taste("Pfeil nach unten"); zeichnen(); }
  });

  window.setInterval(zeichnen, 1000);  // Uhrzeit in der Anzeige, Rückkehr zur Alarmebene
  holen();
})();
