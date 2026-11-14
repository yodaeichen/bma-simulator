"""Live-Bild: welche Anzeigen der Übenden gerade offen sind und was sie zeigen.

Die Anzeigen melden sich mit jeder Abfrage (einmal je Sekunde). Gehalten wird das nur im Arbeitsspeicher;
wer sich sechs Sekunden nicht meldet, gilt als getrennt. Alle Angaben kommen ungeprüft vom Gerät der Übenden
und werden deshalb auf feste Werte und Längen begrenzt.
"""
import hashlib
import json
import re
import threading
import time

from . import sim
from .db import utcnow

TIMEOUT = 6
MAX_GERAETE = 20
GERAETE = {"fat": "FAT und FBF", "bmz": "BMZ", "verz": "Meldergruppenverzeichnis", "wahl": "Auswahlseite", "lauf": "Laufkarten"}
EBENEN = ("alarm", "stoerung", "abschaltung")
_ID = re.compile(r"^[A-Za-z0-9]{4,16}$")
_lock = threading.Lock()
_geraete: dict[int, dict[str, dict]] = {}


def melden(objekt_id: int, q) -> None:
    """Nimmt die Meldung einer Anzeige an. ``q``: die Angaben aus der Adresse der Abfrage."""
    cid = str(q.get("c", ""))
    geraet = str(q.get("g", ""))
    if not _ID.match(cid) or geraet not in GERAETE:
        return
    now = time.time()
    with _lock:
        offen = _geraete.setdefault(objekt_id, {})
        eintrag = offen.get(cid)
        if eintrag is None:
            if len(offen) >= MAX_GERAETE:
                return
            eintrag = offen[cid] = {"id": cid[:4].upper(), "seit": sim.iso(utcnow()), "lcd": [], "taste": "", "taste_zeit": "", "kn": "", "info": ""}
        eintrag["gesehen"] = now
        eintrag["geraet"] = geraet
        eintrag["ebene"] = q.get("e") if q.get("e") in EBENEN else "alarm"
        eintrag["offen"] = q.get("o") == "1"
        eintrag["ton"] = q.get("t") == "1"
        eintrag["info"] = str(q.get("i", ""))[:60]  # z. B. welche Laufkarte gerade offen ist
        if "l" in q:  # die Anzeige schickt ihren Text nur mit, wenn er sich geändert hat
            eintrag["lcd"] = [zeile[:48] for zeile in str(q.get("l", ""))[:700].split("\n")[:12]]
        kn = str(q.get("kn", ""))[:8]
        if kn and kn != eintrag["kn"]:
            if eintrag["kn"] or kn != "0":
                eintrag["taste"], eintrag["taste_zeit"] = str(q.get("k", ""))[:60], sim.iso(utcnow())
            eintrag["kn"] = kn


def liste(objekt_id: int) -> list[dict]:
    grenze = time.time() - TIMEOUT
    with _lock:
        offen = _geraete.get(objekt_id, {})
        for cid in [c for c, e in offen.items() if e["gesehen"] < grenze]:
            del offen[cid]
        return [{k: v for k, v in e.items() if k not in ("gesehen", "kn")} | {"name": GERAETE[e["geraet"]]}
                for e in sorted(offen.values(), key=lambda e: e["seit"])]


def signatur(eintraege: list[dict]) -> str:
    """Kurzer Fingerabdruck: Die Ausbilderansicht lädt nur neu, wenn er sich ändert."""
    return hashlib.sha256(json.dumps(eintraege, sort_keys=True).encode()).hexdigest()[:12]


def vergessen(objekt_id: int) -> None:
    with _lock:
        _geraete.pop(objekt_id, None)
