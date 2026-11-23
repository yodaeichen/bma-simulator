"""Übungsszenarien: vorbereitete Abläufe aus Alarmen, Störungen, Abschaltungen und Löschanlage mit festen Zeitpunkten.

Ein Schritt nennt den Melder über Gruppen- und Meldernummer (g, m). m = 0 heißt „ganze Gruppe“ (nur bei Abschaltungen),
g = 0 heißt „Anlage ohne Melder“ (nur bei Störungen). Gestartet wird über sim.planen; die Anlage arbeitet die
Schritte dann ab wie verzögerte Auslösungen.
"""
import json

from . import db as m
from . import sim

MAX_SCHRITTE = 50
MAX_SEK = 3600


def schritte(szenario: m.Szenario) -> list[dict]:
    try:
        roh = json.loads(szenario.schritte or "[]")
    except ValueError:
        return []
    return roh if isinstance(roh, list) else []


def _zahl(wert, hoechstens: int) -> int | None:
    try:
        zahl = int(str(wert).strip())
    except ValueError:
        return None
    return zahl if 0 <= zahl <= hoechstens else None


def melder_von(objekt: m.Objekt, g: int, nummer: int):
    gruppe = next((x for x in objekt.gruppen if x.nummer == g), None)
    if gruppe is None:
        return None, None
    return gruppe, next((x for x in gruppe.melder if x.nummer == nummer), None) if nummer else None


def aus_formular(objekt: m.Objekt, form) -> tuple[list[dict], list[str]]:
    """Liest die Schritte aus dem Formular (je Feld eine Liste). Liefert (Schritte, Fehler)."""
    felder = [form.getlist(k) for k in ("sek", "aktion", "ziel", "text", "ansteht")]
    if len({len(f) for f in felder}) > 1:
        return [], ["Das Formular ist unvollständig. Bitte die Seite neu laden."]
    ergebnis, fehler = [], []
    for n, (sek, aktion, ziel, text, ansteht) in enumerate(zip(*felder), start=1):
        sek, aktion, text = _zahl(sek, MAX_SEK), str(aktion), str(text).strip()[:60]
        g, _, nummer = str(ziel).partition("/")
        g, nummer = _zahl(g, 9999), _zahl(nummer, 99)
        if sek is None:
            fehler.append(f"Schritt {n}: Zeit muss zwischen 0 und {MAX_SEK} Sekunden liegen.")
            continue
        if aktion not in sim.AKTIONEN or g is None or nummer is None:
            fehler.append(f"Schritt {n}: ungültige Angabe.")
            continue
        if aktion == "loeschanlage":
            g = nummer = 0
        gruppe, melder = melder_von(objekt, g, nummer) if g else (None, None)
        if aktion == "alarm" and melder is None:
            fehler.append(f"Schritt {n}: Für einen Alarm bitte einen Melder wählen.")
            continue
        if aktion == "abschaltung" and gruppe is None:
            fehler.append(f"Schritt {n}: Für eine Abschaltung bitte eine Gruppe oder einen Melder wählen.")
            continue
        if aktion == "stoerung" and g and gruppe is None:
            fehler.append(f"Schritt {n}: Die gewählte Gruppe gibt es nicht mehr.")
            continue
        ergebnis.append({"sek": sek, "aktion": aktion, "g": g, "m": nummer if g else 0,
                         "text": text if aktion == "stoerung" else "", "ansteht": aktion == "alarm" and ansteht == "1"})
    if len(ergebnis) > MAX_SCHRITTE:
        fehler.append(f"Höchstens {MAX_SCHRITTE} Schritte je Szenario.")
    ergebnis.sort(key=lambda s: s["sek"])
    return ergebnis, fehler


def beschreiben(objekt: m.Objekt, schritt: dict) -> str:
    """Ein Schritt in Worten, für Übersicht und Protokoll."""
    art = sim.AKTIONEN.get(schritt.get("aktion"), "?")
    g, nummer = schritt.get("g", 0), schritt.get("m", 0)
    if schritt.get("aktion") == "loeschanlage":
        return art + " ausgelöst"
    if not g:
        return f"{art} der Anlage: {schritt.get('text') or 'Störung'}"
    gruppe, melder = melder_von(objekt, g, nummer)
    ort = (melder.ort if melder else gruppe.name if gruppe else "") or ""
    ziel = sim.nr(g, nummer or None) + (f" {ort}" if ort else "")
    zusatz = f": {schritt['text']}" if schritt.get("text") else ""
    return f"{art} {ziel}{zusatz}" + (", Ursache steht an" if schritt.get("ansteht") else "") + ("" if gruppe else " (fehlt in der Melderliste)")


def starten(st: dict, objekt: m.Objekt, szenario: m.Szenario, log: list, now, wer: str) -> int:
    """Merkt alle Schritte vor. Schritte, deren Melder es nicht mehr gibt, werden übersprungen. Liefert die Zahl der Schritte."""
    quelle = f"Szenario {szenario.name}"[:40]
    geplant = 0
    for schritt in schritte(szenario):
        aktion = schritt.get("aktion")
        g, nummer = int(schritt.get("g") or 0), int(schritt.get("m") or 0)
        ziel = {"gruppe": None, "melder": None, "typ": "", "ort": "", "gname": "", "etage": ""}
        if g:
            gruppe, melder = melder_von(objekt, g, nummer)
            if gruppe is None or (nummer and melder is None):
                log.append((wer, f"Szenario „{szenario.name}“: Schritt übersprungen, {sim.nr(g, nummer or None)} fehlt in der Melderliste"))
                continue
            ziel = {"gruppe": g, "melder": nummer or None, "typ": melder.typ if melder else "", "ort": melder.ort if melder else gruppe.name,
                    "gname": gruppe.name, "etage": gruppe.etage}
        sim.planen(st, ziel, now, int(schritt.get("sek") or 0), bool(schritt.get("ansteht")), aktion=aktion,
                   text=str(schritt.get("text") or ""), quelle=quelle)
        geplant += 1
    ende = max((int(s.get("sek") or 0) for s in schritte(szenario)), default=0)
    log.append((wer, f"Szenario „{szenario.name}“ gestartet: {geplant} Schritte über {ende} s"))
    sim.tick(st, log, now)  # Schritte ohne Wartezeit gleich ausführen
    return geplant
