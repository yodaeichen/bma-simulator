"""Melderliste eines Objekts: Einlesen und Ausgeben als CSV, Beispielobjekte."""
import csv
import io
import json

from . import db as m
from .sim import TYPEN

KOPF = ["Gruppe", "Melder", "Typ", "Etage", "Gruppenname", "Ort"]
MAX_ZEILEN = 2000
# Was Menschen in die Spalte „Typ" schreiben, auf die Kürzel abgebildet
_TYP_WORTE = {name.lower(): kurz for kurz, name in TYPEN.items()}
_TYP_WORTE.update({"rauch": "rm", "optisch": "rm", "wärme": "wm", "waerme": "wm", "thermo": "wm", "thermomelder": "wm",
                   "mehrkriterien": "mm", "flamme": "fm", "gas": "gm", "co": "gm", "linear": "lm", "linearmelder": "lm",
                   "ansaug": "ras", "druckknopf": "hfm", "druckknopfmelder": "hfm", "handmelder": "hfm",
                   "sprinkler": "spr"})


def typ_kurz(wert: str) -> str | None:
    wert = wert.strip().lower()
    return wert if wert in TYPEN else _TYP_WORTE.get(wert)


def lesen(text: str) -> tuple[list[dict], list[str]]:
    """Liest eine Melderliste. Trennzeichen Semikolon, Komma oder Tabulator; die Kopfzeile ist freiwillig.

    Liefert (Zeilen, Fehler). Bei Fehlern wird nichts übernommen."""
    text = text.lstrip("﻿").strip()
    if not text:
        return [], ["Die Liste ist leer."]
    erste = text.splitlines()[0]
    trenner = max(";\t,", key=erste.count)
    zeilen, fehler, gesehen = [], [], set()
    for n, spalten in enumerate(csv.reader(io.StringIO(text), delimiter=trenner), start=1):
        spalten = [s.strip() for s in spalten]
        if not any(spalten) or spalten[0].startswith("#"):
            continue
        if n == 1 and not spalten[0].isdigit():
            continue  # Kopfzeile
        if len(spalten) < 3:
            fehler.append(f"Zeile {n}: mindestens Gruppe, Melder und Typ angeben.")
            continue
        spalten += [""] * (6 - len(spalten))
        gruppe, melder, typ, etage, gname, ort = spalten[:6]
        if not (gruppe.isdigit() and 1 <= int(gruppe) <= 9999):
            fehler.append(f"Zeile {n}: Gruppe muss eine Zahl von 1 bis 9999 sein.")
            continue
        if not (melder.isdigit() and 1 <= int(melder) <= 99):
            fehler.append(f"Zeile {n}: Melder muss eine Zahl von 1 bis 99 sein.")
            continue
        kurz = typ_kurz(typ)
        if not kurz:
            fehler.append(f"Zeile {n}: Typ „{typ}“ unbekannt. Erlaubt: {', '.join(TYPEN)}.")
            continue
        if (int(gruppe), int(melder)) in gesehen:
            fehler.append(f"Zeile {n}: Melder {gruppe}/{melder} kommt doppelt vor.")
            continue
        gesehen.add((int(gruppe), int(melder)))
        zeilen.append({"gruppe": int(gruppe), "melder": int(melder), "typ": kurz, "etage": etage[:40],
                       "gname": gname[:80], "ort": ort[:80]})
        if len(zeilen) > MAX_ZEILEN:
            return [], [f"Höchstens {MAX_ZEILEN} Melder je Objekt."]
    if not zeilen and not fehler:
        fehler.append("Keine Melder gefunden.")
    return ([], fehler[:20]) if fehler else (zeilen, [])


def uebernehmen(db, objekt: m.Objekt, zeilen: list[dict], ersetzen: bool) -> int:
    """Trägt die Zeilen in das Objekt ein. Vorhandene Melder mit gleicher Nummer werden überschrieben."""
    if ersetzen:
        objekt.gruppen.clear()
        db.flush()
    gruppen = {g.nummer: g for g in objekt.gruppen}
    for z in zeilen:
        g = gruppen.get(z["gruppe"])
        if g is None:
            g = m.Gruppe(nummer=z["gruppe"], name=z["gname"], etage=z["etage"])
            objekt.gruppen.append(g)
            gruppen[g.nummer] = g
        else:
            g.name = z["gname"] or g.name
            g.etage = z["etage"] or g.etage
        vorhanden = next((x for x in g.melder if x.nummer == z["melder"]), None)
        if vorhanden:
            vorhanden.typ, vorhanden.ort = z["typ"], z["ort"]
        else:
            g.melder.append(m.Melder(nummer=z["melder"], typ=z["typ"], ort=z["ort"]))
    return len(zeilen)


def schreiben(objekt: m.Objekt) -> str:
    aus = io.StringIO()
    w = csv.writer(aus, delimiter=";", lineterminator="\r\n")
    w.writerow(KOPF)
    for g in objekt.gruppen:
        for x in g.melder:
            w.writerow([g.nummer, x.nummer, x.typ, g.etage, g.name, x.ort])
    return "﻿" + aus.getvalue()


def etagen(objekt: m.Objekt) -> list[str]:
    """Etagen in der Reihenfolge, in der die Gruppen sie zuerst nennen."""
    gesehen = []
    for g in objekt.gruppen:
        if g.etage not in gesehen:
            gesehen.append(g.etage)
    return gesehen


BEISPIELE = [
    {"name": "Seniorenheim Am Musterpark", "adresse": "Parkstraße 12, 12345 Musterstadt", "bma_nr": "BMA 017",
     "hinweis": "FIZ im Windfang Haupteingang. Nachts eine Pflegekraft je Wohnbereich.", "loeschanlage": False,
     "szenarien": [
         ("Brand Zimmer 101 mit Ausbreitung", "Echter Brand im 1. OG: Der Rauch zieht in den Flur, nach zwei Minuten löst der Handfeuermelder aus.",
          [(0, "alarm", 10, 3, "", True), (45, "alarm", 10, 2, "", True), (120, "alarm", 10, 1, "", True)]),
         ("Täuschungsalarm Küche", "Wasserdampf in der Großküche. Ursache beseitigt, die Anlage lässt sich zurückstellen.",
          [(0, "alarm", 3, 1, "", False)]),
         ("Nacht mit Störung", "Erst fällt ein Melder im Keller aus, dann löst im 2. OG ein Rauchmelder aus.",
          [(0, "stoerung", 30, 1, "Melder verschmutzt", False), (60, "alarm", 20, 4, "", True)]),
     ],
     "liste": """
1;1;hfm;EG;Haupteingang;Windfang
1;2;hfm;EG;Haupteingang;Flur Verwaltung
2;1;rm;EG;Foyer und Verwaltung;Foyer
2;2;rm;EG;Foyer und Verwaltung;Büro Heimleitung
2;3;rm;EG;Foyer und Verwaltung;Büro Pflegedienst
3;1;wm;EG;Küche;Großküche
3;2;wm;EG;Küche;Spülküche
3;3;rm;EG;Küche;Lager Lebensmittel
4;1;rm;EG;Speisesaal;Speisesaal Mitte
4;2;rm;EG;Speisesaal;Speisesaal Fenster
10;1;hfm;1. OG;Wohnbereich 1;Flur vor Treppenraum
10;2;rm;1. OG;Wohnbereich 1;Flur Mitte
10;3;rm;1. OG;Wohnbereich 1;Zimmer 101
10;4;rm;1. OG;Wohnbereich 1;Zimmer 102
10;5;rm;1. OG;Wohnbereich 1;Zimmer 103
10;6;rm;1. OG;Wohnbereich 1;Aufenthaltsraum
11;1;rm;1. OG;Dienstzimmer WB 1;Dienstzimmer
11;2;wm;1. OG;Dienstzimmer WB 1;Teeküche
20;1;hfm;2. OG;Wohnbereich 2;Flur vor Treppenraum
20;2;rm;2. OG;Wohnbereich 2;Flur Mitte
20;3;rm;2. OG;Wohnbereich 2;Zimmer 201
20;4;rm;2. OG;Wohnbereich 2;Zimmer 202
20;5;rm;2. OG;Wohnbereich 2;Zimmer 203
30;1;rm;KG;Technik;Heizungsraum
30;2;wm;KG;Technik;Heizungsraum Kessel
30;3;rm;KG;Technik;Elektroverteilung
31;1;rm;KG;Wäscherei;Waschraum
31;2;rm;KG;Wäscherei;Wäschelager
"""},
    {"name": "Möbelhaus Wohnwelt", "adresse": "Industriestraße 4, 12345 Musterstadt", "bma_nr": "BMA 023",
     "hinweis": "Sprinkleranlage in Verkauf und Lager. Sprinklerzentrale im EG neben der Warenannahme.",
     "loeschanlage": True,
     "szenarien": [
         ("Sprinkler im Hochregallager", "Das Ansaugsystem meldet zuerst, kurz darauf löst die Sprinklergruppe aus.",
          [(0, "alarm", 21, 2, "", True), (40, "alarm", 20, 1, "", True)]),
     ],
     "liste": """
1;1;hfm;EG;Eingang Kunden;Windfang
1;2;hfm;EG;Eingang Kunden;Kassenzone
2;1;spr;EG;Sprinkler Verkauf EG;Verkaufsfläche EG
3;1;rm;EG;Restaurant;Gastraum
3;2;wm;EG;Restaurant;Küche
4;1;lm;EG;Warenannahme;Rampe 1 bis 3
4;2;hfm;EG;Warenannahme;Tor 1
5;1;rm;EG;Sprinklerzentrale;Sprinklerzentrale
10;1;spr;1. OG;Sprinkler Verkauf OG;Verkaufsfläche OG
11;1;hfm;1. OG;Treppenräume;Treppenraum Nord
11;2;hfm;1. OG;Treppenräume;Treppenraum Süd
12;1;rm;1. OG;Verwaltung;Büro Leitung
12;2;rm;1. OG;Verwaltung;Sozialraum
20;1;spr;Lager;Sprinkler Hochregal;Hochregallager
21;1;ras;Lager;Ansaugsystem Hochregal;Gasse 1 bis 4
21;2;ras;Lager;Ansaugsystem Hochregal;Gasse 5 bis 8
22;1;hfm;Lager;Lager Ausgänge;Notausgang Ost
"""},
    {"name": "Metallbau Beispiel GmbH", "adresse": "Gewerbering 9, 12345 Musterstadt", "bma_nr": "BMA 031",
     "hinweis": "Gasflaschenlager außen an der Nordseite. Schweißarbeiten: Gruppe 3 tagsüber häufig abgeschaltet.",
     "loeschanlage": False, "liste": """
1;1;hfm;EG;Halle Ausgänge;Tor Süd
1;2;hfm;EG;Halle Ausgänge;Tür Büro
1;3;hfm;EG;Halle Ausgänge;Notausgang Nord
2;1;lm;EG;Halle Montage;Hallenschiff 1
2;2;lm;EG;Halle Montage;Hallenschiff 2
3;1;fm;EG;Halle Schweißerei;Schweißplatz 1 und 2
3;2;fm;EG;Halle Schweißerei;Schweißplatz 3 und 4
3;3;wm;EG;Halle Schweißerei;Absaugung
4;1;gm;EG;Gaslager;Gasflaschenlager
5;1;rm;EG;Lackierraum;Lackierkabine Zuluft
5;2;wm;EG;Lackierraum;Farblager
10;1;rm;OG;Büro;Flur
10;2;rm;OG;Büro;Büro Meister
10;3;rm;OG;Büro;Serverraum
10;4;wm;OG;Büro;Teeküche
"""},
    {"name": "Grundschule Musterdorf", "adresse": "Schulweg 1, 12345 Musterdorf", "bma_nr": "BMA 008",
     "hinweis": "Hausalarm mit Weiterleitung. Sammelplatz: Pausenhof West.", "loeschanlage": False, "liste": """
1;1;hfm;EG;Flure EG;Haupteingang
1;2;hfm;EG;Flure EG;Flur Ost
1;3;rm;EG;Flure EG;Flur Mitte
2;1;rm;EG;Aula;Aula Bühne
2;2;rm;EG;Aula;Aula Saal
3;1;rm;EG;Verwaltung;Sekretariat
3;2;rm;EG;Verwaltung;Lehrerzimmer
4;1;wm;EG;Werkraum;Werkraum
4;2;rm;EG;Werkraum;Materiallager
10;1;hfm;OG;Flure OG;Treppenraum
10;2;rm;OG;Flure OG;Flur Mitte
11;1;rm;OG;Klassenräume;Klasse 1a
11;2;rm;OG;Klassenräume;Klasse 2a
11;3;rm;OG;Klassenräume;Klasse 3a
11;4;rm;OG;Klassenräume;Klasse 4a
12;1;rm;OG;Computerraum;Computerraum
20;1;rm;KG;Heizung;Heizungsraum
20;2;wm;KG;Heizung;Öllager
"""},
]


def _szenarien_von(b: dict) -> list:
    return [m.Szenario(name=name, beschreibung=text, schritte=json.dumps([
        {"sek": sek, "aktion": aktion, "g": g, "m": nummer, "text": t, "ansteht": ansteht} for sek, aktion, g, nummer, t, ansteht in ablauf]))
        for name, text, ablauf in b.get("szenarien", [])]


def beispielszenarien_nachtragen(db) -> int:
    """Für Installationen von vor Version 1.5: Die Beispielobjekte bekommen ihre Szenarien, sofern sie noch keine haben
    und alle Melder darin noch vorhanden sind. Läuft nur einmal (Merker im Datenverzeichnis)."""
    import os
    merker = os.path.join(m.DATA_DIR, ".beispielszenarien")
    if os.path.exists(merker):
        return 0
    anzahl = 0
    for b in BEISPIELE:
        for objekt in db.query(m.Objekt).filter(m.Objekt.name == b["name"]).all():
            if objekt.szenarien:
                continue
            vorhanden = {(g.nummer, x.nummer) for g in objekt.gruppen for x in g.melder}
            neu = [sz for sz in _szenarien_von(b)
                   if all((s["g"], s["m"]) in vorhanden or not s["g"] for s in json.loads(sz.schritte))]
            objekt.szenarien.extend(neu)
            anzahl += len(neu)
    db.commit()
    with open(merker, "w", encoding="utf-8") as datei:
        datei.write("Beispielszenarien wurden eingetragen.\n")
    return anzahl


def beispiele_anlegen(db) -> int:
    for b in BEISPIELE:
        objekt = m.Objekt(name=b["name"], adresse=b["adresse"], bma_nr=b["bma_nr"], hinweis=b["hinweis"],
                          loeschanlage=b["loeschanlage"])
        db.add(objekt)
        zeilen, fehler = lesen(b["liste"])
        assert not fehler, fehler
        uebernehmen(db, objekt, zeilen, ersetzen=False)
        objekt.szenarien.extend(_szenarien_von(b))
    db.commit()
    return len(BEISPIELE)
