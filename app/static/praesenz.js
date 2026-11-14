// Lebenszeichen der Seiten ohne eigene Anzeige (Auswahl, Verzeichnis), damit sie im Live-Bild des Ausbilders erscheinen.
(function () {
  var el = document.getElementById("da");
  if (!el) return;
  var cid = "";
  try { cid = window.sessionStorage.getItem("bma-geraet") || ""; } catch (e) { /* ohne Speicher: neue Kennung je Seite */ }
  if (!/^[a-z0-9]{8}$/.test(cid)) {
    cid = Math.random().toString(36).slice(2, 10).padEnd(8, "0");
    try { window.sessionStorage.setItem("bma-geraet", cid); } catch (e) { /* egal */ }
  }
  function ping() {
    fetch("/a/" + el.dataset.token + "/da?c=" + cid + "&g=" + el.dataset.geraet, { cache: "no-store" }).catch(function () {});
  }
  ping();
  window.setInterval(ping, 2000);
})();
