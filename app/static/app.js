// App-Funktionen: Service Worker anmelden, Installation anbieten; auf den Anzeigen zusätzlich Vollbild und Bildschirm wach halten.
(function () {
  var standalone = (window.matchMedia && (window.matchMedia("(display-mode: standalone)").matches || window.matchMedia("(display-mode: fullscreen)").matches))
    || window.navigator.standalone === true;
  var ios = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});

  function show(id, on) { var el = document.getElementById(id); if (el) el.hidden = !on; }

  // ---------- Installation (Karte unter „Mein Konto“ und auf der Auswahlseite der Anzeigen) ----------
  if (document.getElementById("app-install")) {
    var prompt = null;
    show("app-installed", standalone);
    show("app-insecure", !standalone && !window.isSecureContext);
    show("app-ios", !standalone && window.isSecureContext && ios);
    show("app-other", !standalone && window.isSecureContext && !ios);
    window.addEventListener("beforeinstallprompt", function (event) {
      event.preventDefault();
      prompt = event;
      show("app-other", false);
      show("app-prompt", true);
    });
    var button = document.getElementById("app-install-button");
    if (button) button.addEventListener("click", function () {
      if (!prompt) return;
      prompt.prompt();
      prompt.userChoice.then(function () { prompt = null; show("app-prompt", false); });
    });
    window.addEventListener("appinstalled", function () { show("app-prompt", false); show("app-other", false); show("app-installed", true); });
  }

  // ---------- Vollbild (Knopf in der Leiste der Anzeigen) ----------
  var voll = document.getElementById("vollbild");
  var root = document.documentElement;
  var request = root.requestFullscreen || root.webkitRequestFullscreen;
  var exit = document.exitFullscreen || document.webkitExitFullscreen;
  function isFull() { return !!(document.fullscreenElement || document.webkitFullscreenElement); }
  if (voll && request && exit && !standalone) {
    voll.hidden = false;
    voll.addEventListener("click", function () {
      var done = isFull() ? exit.call(document) : request.call(root);
      if (done && done.catch) done.catch(function () {});
    });
    var mark = function () { voll.setAttribute("aria-pressed", isFull() ? "true" : "false"); voll.textContent = isFull() ? "Vollbild aus" : "Vollbild"; };
    document.addEventListener("fullscreenchange", mark);
    document.addEventListener("webkitfullscreenchange", mark);
  }

  // ---------- Bildschirm wach halten, solange eine Anzeige offen ist ----------
  if (document.body.hasAttribute("data-wach") && "wakeLock" in navigator) {
    var lock = null;
    var hold = function () {
      if (lock || document.visibilityState !== "visible") return;
      navigator.wakeLock.request("screen").then(function (got) {
        lock = got;
        got.addEventListener("release", function () { lock = null; });
      }).catch(function () {});
    };
    hold();
    document.addEventListener("visibilitychange", hold);
    document.addEventListener("click", hold);   // manche Browser geben die Sperre erst nach einer Bedienung frei
  }
})();
