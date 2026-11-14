"""Verhalten der simulierten Brandmeldeanlage.

Reine Funktionen auf einem Zustands-Wörterbuch, ohne Datenbank und ohne Netzwerk. Jede Änderung erhöht
``v``; die Anzeigen fragen nur nach, ob sich ``v`` geändert hat. Zeitpunkte sind UTC als ISO-Text.

Abgebildet ist das, was die Feuerwehr an FBF (DIN 14661) und FAT (DIN 14662) bedient:
Übertragungseinrichtung (ÜE), akustische Signale, Brandfallsteuerungen, Löschanlage, Rückstellen.
"""
import datetime as dt

TYPEN = {
    "rm": "Rauchmelder",
    "wm": "Wärmemelder",
    "mm": "Mehrkriterienmelder",
    "fm": "Flammenmelder",
    "gm": "Gasmelder",
    "lm": "Linearer Rauchmelder",
    "ras": "Rauchansaugsystem",
    "hfm": "Handfeuermelder",
    "spr": "Sprinklergruppe",
}
MAX_MELDUNGEN = 200
WIEDERAUSLOESUNG_SEK = 5


def neu() -> dict:
    return {"v": 1, "seq": 0, "meldungen": [], "geplant": [],
            "ue": False, "ue_ab": False, "akustik_ab": False, "bfs_ab": False, "loesch": False,
            "summer_fat": False, "summer_bmz": False}


def iso(now: dt.datetime) -> str:
    return now.replace(microsecond=0).isoformat() + "Z"


def nr(gruppe, melder=None) -> str:
    """Schreibweise wie am FAT: vierstellige Gruppe, zweistelliger Melder."""
    return f"{int(gruppe):04d}" + (f"/{int(melder):02d}" if melder else "")


def alarme(st: dict) -> list:
    return [m for m in st["meldungen"] if m["art"] == "alarm"]


def abgeschaltet(st: dict, gruppe: int, melder=None) -> bool:
    for m in st["meldungen"]:
        if m["art"] == "abschaltung" and m["gruppe"] == gruppe and (m["melder"] is None or m["melder"] == melder):
            return True
    return False


def _neue_meldung(st: dict, art: str, now: dt.datetime, **felder) -> dict:
    st["seq"] += 1
    meldung = {"id": st["seq"], "art": art, "zeit": iso(now), "gruppe": None, "melder": None, "typ": "",
               "ort": "", "gname": "", "etage": "", "ansteht": False}
    meldung.update(felder)
    st["meldungen"].append(meldung)
    st["summer_fat"] = st["summer_bmz"] = True
    st["v"] += 1
    return meldung


def _ue_ausloesen(st: dict, log: list, grund: str):
    if st["ue_ab"]:
        log.append(("Anlage", f"ÜE ist abgeschaltet: {grund} wird NICHT an die Leitstelle übertragen"))
    elif not st["ue"]:
        st["ue"] = True
        log.append(("Anlage", f"ÜE ausgelöst ({grund}): Leitstelle alarmiert, FSD entriegelt, Blitzleuchte an"))
    st["v"] += 1


def alarm(st: dict, ziel: dict, log: list, now: dt.datetime, quelle: str = "Ausbilder", ansteht: bool = False) -> bool:
    """Löst einen Melder aus. ``ziel``: gruppe, melder, typ, ort, gname, etage."""
    gruppe, melder = ziel["gruppe"], ziel["melder"]
    bez = f"{nr(gruppe, melder)} {TYPEN.get(ziel.get('typ', ''), 'Melder')} ({ziel.get('ort', '')})"
    if abgeschaltet(st, gruppe, melder):
        log.append((quelle, f"{bez} angesprochen, ist aber abgeschaltet: keine Alarmmeldung"))
        return False
    if any(m["gruppe"] == gruppe and m["melder"] == melder for m in alarme(st)):
        return False
    if len(st["meldungen"]) >= MAX_MELDUNGEN:
        return False
    _neue_meldung(st, "alarm", now, gruppe=gruppe, melder=melder, typ=ziel.get("typ", ""), ort=ziel.get("ort", ""),
                  gname=ziel.get("gname", ""), etage=ziel.get("etage", ""), ansteht=bool(ansteht))
    log.append((quelle, f"Alarm {bez}" + (", Ursache steht an" if ansteht else "")))
    if ziel.get("typ") == "spr" and not st["loesch"]:
        st["loesch"] = True
        log.append(("Anlage", "Löschanlage ausgelöst"))
    _ue_ausloesen(st, log, "Feueralarm")
    return True


def planen(st: dict, ziel: dict, now: dt.datetime, sekunden: int, ansteht: bool = False):
    """Merkt eine Auslösung für später vor; ``tick`` führt sie aus."""
    if len(st["geplant"]) >= 50:
        return
    faellig = iso(now + dt.timedelta(seconds=max(0, min(int(sekunden), 3600))))
    st["geplant"].append({"faellig": faellig, "ziel": ziel, "ansteht": bool(ansteht)})
    st["v"] += 1


def tick(st: dict, log: list, now: dt.datetime) -> bool:
    """Führt fällige vorgemerkte Auslösungen aus. Liefert True, wenn sich etwas geändert hat."""
    jetzt = iso(now)
    faellig = [p for p in st["geplant"] if p["faellig"] <= jetzt]
    if not faellig:
        return False
    st["geplant"] = [p for p in st["geplant"] if p["faellig"] > jetzt]
    for p in sorted(faellig, key=lambda p: p["faellig"]):
        alarm(st, p["ziel"], log, now, quelle=p.get("quelle", "Ausbilder (verzögert)"), ansteht=p["ansteht"])
    st["v"] += 1
    return True


def stoerung(st: dict, text: str, log: list, now: dt.datetime, gruppe=None, melder=None, quelle: str = "Ausbilder",
             ort: str = "", gname: str = "", etage: str = ""):
    """Meldet eine Störung: an einem Melder (dann mit dessen Ort) oder an der Anlage (dann mit dem Text)."""
    anzeige = (ort or text)[:60]
    if any(m["art"] == "stoerung" and m["gruppe"] == gruppe and m["melder"] == melder and m["ort"] == anzeige
           for m in st["meldungen"]) or len(st["meldungen"]) >= MAX_MELDUNGEN:
        return
    _neue_meldung(st, "stoerung", now, gruppe=gruppe, melder=melder, ort=anzeige, gname=gname, etage=etage)
    log.append((quelle, "Störung " + (nr(gruppe, melder) + " " if gruppe else "") + text[:60]))


def abschaltung(st: dict, gruppe: int, log: list, now: dt.datetime, melder=None, gname: str = "", ort: str = "",
                quelle: str = "Ausbilder"):
    """Schaltet eine Gruppe oder einen einzelnen Melder ab; ein zweiter Aufruf schaltet wieder ein."""
    for m in st["meldungen"]:
        if m["art"] == "abschaltung" and m["gruppe"] == gruppe and m["melder"] == melder:
            st["meldungen"].remove(m)
            st["v"] += 1
            log.append((quelle, f"{nr(gruppe, melder)} wieder eingeschaltet"))
            return
    if len(st["meldungen"]) >= MAX_MELDUNGEN:
        return
    _neue_meldung(st, "abschaltung", now, gruppe=gruppe, melder=melder, gname=gname, ort=ort or gname)
    log.append((quelle, f"{nr(gruppe, melder)} abgeschaltet"))


def entfernen(st: dict, meldung_id: int, log: list, quelle: str = "Ausbilder"):
    """Nimmt eine einzelne Meldung heraus, z. B. eine behobene Störung."""
    for m in st["meldungen"]:
        if m["id"] == meldung_id:
            st["meldungen"].remove(m)
            st["v"] += 1
            log.append((quelle, f"Meldung entfernt: {m['art']} {nr(m['gruppe'], m['melder']) if m['gruppe'] else m['ort']}"))
            if m["art"] == "alarm" and not alarme(st):
                st["ue"] = False
            return


def ursache(st: dict, meldung_id: int, ansteht: bool, log: list, quelle: str = "Ausbilder"):
    """Legt fest, ob die Ursache eines Alarms noch ansteht (dann kommt er nach dem Rückstellen wieder)."""
    for m in st["meldungen"]:
        if m["id"] == meldung_id and m["art"] == "alarm":
            m["ansteht"] = bool(ansteht)
            st["v"] += 1
            log.append((quelle, f"{nr(m['gruppe'], m['melder'])}: Ursache " + ("steht an" if ansteht else "beseitigt")))
            return


def loeschanlage(st: dict, an: bool, log: list, quelle: str = "Ausbilder"):
    if st["loesch"] != bool(an):
        st["loesch"] = bool(an)
        st["v"] += 1
        log.append((quelle, "Löschanlage ausgelöst" if an else "Löschanlage: Auslösung beendet"))


def ruecksetzen(st: dict, log: list, now: dt.datetime, quelle: str):
    """BMZ rückstellen: Alarme und ÜE-Auslösung gehen weg. Steht die Ursache noch an, löst der Melder erneut aus.
    Störungen, Abschaltungen und die „ab"-Schalter am FBF bleiben, wie sie sind."""
    bleibend = [m for m in alarme(st) if m["ansteht"]]
    st["meldungen"] = [m for m in st["meldungen"] if m["art"] != "alarm"]
    st["ue"] = False
    st["loesch"] = False
    st["summer_fat"] = st["summer_bmz"] = False
    st["v"] += 1
    log.append((quelle, "BMZ rückgestellt"))
    for m in bleibend:
        ziel = {k: m[k] for k in ("gruppe", "melder", "typ", "ort", "gname", "etage")}
        faellig = iso(now + dt.timedelta(seconds=WIEDERAUSLOESUNG_SEK))
        st["geplant"].append({"faellig": faellig, "ziel": ziel, "ansteht": True, "quelle": "Anlage (Ursache steht an)"})


def schalter(st: dict, name: str, log: list, quelle: str):
    """Die drei Schalter am FBF: akustik_ab, bfs_ab, ue_ab. Jeder Druck schaltet um."""
    texte = {"akustik_ab": "Akustische Signale", "bfs_ab": "Brandfallsteuerungen", "ue_ab": "ÜE"}
    if name not in texte:
        return
    st[name] = not st[name]
    st["v"] += 1
    log.append((quelle, f"{texte[name]} {'ab' if st[name] else 'wieder ein'}geschaltet"))
    if name == "ue_ab" and not st["ue_ab"] and alarme(st) and not st["ue"]:
        _ue_ausloesen(st, log, "anstehender Feueralarm")


def ue_pruefen(st: dict, log: list, quelle: str):
    if st["ue_ab"]:
        log.append((quelle, "ÜE prüfen gedrückt, ÜE ist aber abgeschaltet: keine Übertragung"))
        st["v"] += 1
    else:
        log.append((quelle, "ÜE prüfen gedrückt"))
        _ue_ausloesen(st, log, "Prüfung")


def summer_ab(st: dict, geraet: str, log: list):
    key = "summer_fat" if geraet == "fat" else "summer_bmz"
    if st[key]:
        st[key] = False
        st["v"] += 1
        log.append((geraet.upper(), "Summer abgestellt"))


def grundstellung(st: dict, log: list, quelle: str = "Ausbilder"):
    """Setzt alles zurück, auch Störungen, Abschaltungen und die Schalter am FBF."""
    v, seq = st["v"], st["seq"]
    st.clear()
    st.update(neu())
    st["v"], st["seq"] = v + 1, seq
    log.append((quelle, "Anlage in Grundstellung gebracht"))


def sicht(st: dict) -> dict:
    """Abgeleitete Angaben für die Anzeigen."""
    arten = {"alarm": 0, "stoerung": 0, "abschaltung": 0}
    for m in st["meldungen"]:
        arten[m["art"]] += 1
    feuer = arten["alarm"] > 0
    return {
        "alarme": arten["alarm"], "stoerungen": arten["stoerung"], "abschaltungen": arten["abschaltung"],
        "akustik_aktiv": feuer and not st["akustik_ab"],
        "bfs_aktiv": feuer and not st["bfs_ab"],
        "fsd_offen": st["ue"],
        "normal": not st["meldungen"] and not st["geplant"] and not (st["ue"] or st["ue_ab"] or st["akustik_ab"] or st["bfs_ab"] or st["loesch"]),
    }
