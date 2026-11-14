"""Feuerwehr-Laufkarten: je Meldergruppe eine Karte mit Übersicht (Laufweg ab der FIZ) und Detail (Lage der Melder).

Pläne sind hochgeladene Bilder oder Schemapläne, die der Simulator aus der Melderliste zeichnet. Alle Lagen im
Plan sind Anteile von Breite und Höhe (0 bis 1), damit sie zu jedem Bild passen.
"""
import json
import math
from html import escape

from . import db as m
from .sim import TYPEN

MAX_PLAN = 4 * 1024 * 1024
MAX_PUNKTE = 60
W, H = 1200, 700          # Zeichenfläche der Schemapläne
FLUR_Y = 350              # Mittellinie des Flurs
TREPPE = (85, FLUR_Y)     # Treppenraum am linken Ende des Flurs
ZUGANG = (1150, FLUR_Y)   # Zugang der Feuerwehr mit FIZ am rechten Ende
# Melder mit solchen Ortsangaben liegen im Flur und bekommen keinen eigenen Raum
FLUR_WORTE = ("flur", "treppenraum", "windfang", "eingang", "ausgang", "tor", "rampe", "kassenzone")


def bildart(daten: bytes) -> str | None:
    """Erkennt die Bildart am Inhalt, nicht am Dateinamen. None, wenn es kein erlaubtes Bild ist."""
    if daten.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if daten.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if daten[:4] == b"RIFF" and daten[8:12] == b"WEBP":
        return "image/webp"
    kopf = daten[:2000].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if kopf.startswith((b"<?xml", b"<svg", b"<!--", b"<!doctype svg")) and b"<svg" in kopf:
        return "image/svg+xml"
    return None


def punkte(text: str) -> list[list[float]]:
    """Liest einen gespeicherten oder vom Formular gesendeten Weg; alles Ungültige fällt weg."""
    try:
        roh = json.loads(text or "[]")
    except ValueError:
        return []
    if not isinstance(roh, list):
        return []
    weg = []
    for p in roh[:MAX_PUNKTE]:
        if isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p) \
                and all(math.isfinite(v) and 0 <= v <= 1 for v in p):
            weg.append([round(float(p[0]), 4), round(float(p[1]), 4)])
    return weg


def lage(wert) -> float | None:
    try:
        zahl = float(wert)
    except (TypeError, ValueError):
        return None
    return round(zahl, 4) if math.isfinite(zahl) and 0 <= zahl <= 1 else None


def fiz_etage(objekt: m.Objekt) -> str:
    """Etage der FIZ: die eingestellte, sonst „EG“, sonst die erste der Melderliste."""
    etagen = []
    for g in objekt.gruppen:
        if g.etage not in etagen:
            etagen.append(g.etage)
    if objekt.fiz_etage in etagen:
        return objekt.fiz_etage
    return "EG" if "EG" in etagen else (etagen[0] if etagen else "")


def plan_von(objekt: m.Objekt, etage: str) -> m.Plan | None:
    return next((p for p in objekt.plaene if p.etage == etage), None)


def karte(objekt: m.Objekt, gruppe: m.Gruppe) -> dict:
    """Alles, was die Vorlage für eine Laufkarte braucht."""
    start = fiz_etage(objekt)
    gleich = gruppe.etage == start
    arten = []
    for x in gruppe.melder:
        if TYPEN.get(x.typ, x.typ) not in arten:
            arten.append(TYPEN.get(x.typ, x.typ))
    return {
        "g": gruppe, "gleich": gleich, "fiz_etage": start, "arten": arten,
        "plan1": plan_von(objekt, start), "plan2": plan_von(objekt, gruppe.etage),
        "weg1": punkte(gruppe.weg1), "weg2": punkte(gruppe.weg1 if gleich else gruppe.weg2),
        "fiz": (objekt.fiz_x, objekt.fiz_y) if objekt.fiz_x is not None and objekt.fiz_y is not None else None,
        "schritte": [z.strip() for z in gruppe.laufweg.splitlines() if z.strip()],
        "gesetzt": sum(1 for x in gruppe.melder if x.px is not None),
    }


def stand(objekt: m.Objekt) -> list[dict]:
    """Je Gruppe, was der Laufkarte noch fehlt (für die Übersichtsseite)."""
    return [{"g": k["g"], "plan": bool(k["plan1"] and k["plan2"]), "weg": bool(k["weg1"]) and (k["gleich"] or bool(k["weg2"])),
             "gesetzt": k["gesetzt"], "text": bool(k["schritte"])}
            for k in (karte(objekt, g) for g in objekt.gruppen)]


# ---------- Schemapläne ----------

def _im_flur(ort: str) -> bool:
    klein = ort.lower()
    return any(wort in klein for wort in FLUR_WORTE)


def _zeilen(text: str, breite: float) -> list[str]:
    """Bricht eine Raumbezeichnung auf höchstens zwei Zeilen um."""
    platz = max(6, int(breite / 9.5))
    if len(text) <= platz:
        return [text]
    erste, rest = "", text
    for wort in text.split():
        if len(erste) + len(wort) + 1 > platz and erste:
            break
        erste = (erste + " " + wort).strip()
        rest = text[len(erste):].strip()
    rest = rest if len(rest) <= platz else rest[:platz - 1] + "…"
    return [erste or text[:platz], rest] if rest else [erste]


def schema(objekt: m.Objekt, etage: str, mit_zugang: bool) -> tuple[str, dict[int, tuple[float, float]]]:
    """Zeichnet einen Schemaplan der Etage: Flur in der Mitte, Räume darüber und darunter, Treppenraum links.

    Liefert das SVG und die Lage jedes Melders der Etage (in Pixeln der Zeichenfläche)."""
    melder = [x for g in objekt.gruppen if g.etage == etage for x in g.melder]
    raeume, flur = [], []
    for x in melder:
        if _im_flur(x.ort):
            flur.append(x)
        elif x.ort not in raeume:
            raeume.append(x.ort)
    oben = math.ceil(len(raeume) / 2) or 1
    unten = max(len(raeume) - oben, 1)
    x0, x1 = 150, 1180
    teile = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Arial, Helvetica, sans-serif">',
             f'<rect width="{W}" height="{H}" fill="#fff"/>',
             f'<rect x="20" y="40" width="{x1 - 20}" height="620" fill="#f7f7f5" stroke="#222" stroke-width="5"/>',
             f'<rect x="20" y="300" width="{x1 - 20}" height="100" fill="#ececea" stroke="#222" stroke-width="3"/>',
             '<rect x="20" y="300" width="130" height="100" fill="#dcdcd8" stroke="#222" stroke-width="3"/>']
    teile += [f'<line x1="{x}" y1="300" x2="{x}" y2="400" stroke="#555" stroke-width="2"/>' for x in range(40, 150, 18)]
    teile.append('<text x="85" y="290" text-anchor="middle" font-size="15" font-weight="bold" fill="#222">Treppenraum</text>')
    teile.append(f'<text x="{(x0 + x1) / 2}" y="356" text-anchor="middle" font-size="17" fill="#777" letter-spacing="6">FLUR</text>')
    mitte = {}
    for i, name in enumerate(raeume):
        reihe_oben = i < oben
        anzahl, k = (oben, i) if reihe_oben else (unten, i - oben)
        breite = (x1 - x0) / anzahl
        rx, ry = x0 + k * breite, 40 if reihe_oben else 400
        teile.append(f'<rect x="{rx:.0f}" y="{ry}" width="{breite:.0f}" height="260" fill="none" stroke="#222" stroke-width="3"/>')
        tuer = ry + 260 if reihe_oben else ry  # Türöffnung zum Flur
        teile.append(f'<line x1="{rx + breite / 2 - 22:.0f}" y1="{tuer}" x2="{rx + breite / 2 + 22:.0f}" y2="{tuer}" stroke="#ececea" stroke-width="7"/>')
        for n, zeile in enumerate(_zeilen(name, breite)):
            teile.append(f'<text x="{rx + breite / 2:.0f}" y="{ry + 34 + n * 20}" text-anchor="middle" font-size="16" fill="#222">{escape(zeile)}</text>')
        mitte[name] = (rx + breite / 2, ry + 150)
    if mit_zugang:
        teile.append(f'<line x1="{x1}" y1="312" x2="{x1}" y2="388" stroke="#fff" stroke-width="8"/>')
        teile.append(f'<text x="{x1 - 8}" y="292" text-anchor="end" font-size="15" font-weight="bold" fill="#222">Zugang Feuerwehr</text>')
    teile.append(f'<text x="30" y="688" font-size="14" fill="#777">Schemaplan {escape(etage or "ohne Etage")} · nicht maßstäblich</text>')
    teile.append("</svg>")

    orte: dict[int, tuple[float, float]] = {}
    je_raum: dict[str, list] = {}
    for x in melder:
        if not _im_flur(x.ort):
            je_raum.setdefault(x.ort, []).append(x)
    for name, liste in je_raum.items():
        cx, cy = mitte[name]
        for k, x in enumerate(liste):
            orte[x.id] = (cx + (k - (len(liste) - 1) / 2) * 46, cy)
    for k, x in enumerate(flur):
        orte[x.id] = (230 + (k + 0.5) * (860 / len(flur)), FLUR_Y - 22)
    return "\n".join(teile), orte


def _anteil(p: tuple[float, float]) -> list[float]:
    return [round(p[0] / W, 4), round(p[1] / H, 4)]


def _weg(von: tuple[float, float], ziel: tuple[float, float]) -> str:
    """Weg im Schemaplan: den Flur entlang bis vor das Ziel, dann hinein."""
    weg = [von, (ziel[0], FLUR_Y)] + ([ziel] if abs(ziel[1] - FLUR_Y) > 30 else [])
    return json.dumps([_anteil(p) for p in weg])


def schema_erzeugen(db, objekt: m.Objekt) -> int:
    """Zeichnet für jede Etage ohne hochgeladenen Plan einen Schemaplan und setzt dort Melder, FIZ und Laufwege.

    Hochgeladene Pläne und alles, was auf ihnen eingezeichnet ist, bleiben unberührt. Liefert die Zahl der Schemapläne."""
    start = fiz_etage(objekt)
    etagen = []
    for g in objekt.gruppen:
        if g.etage not in etagen:
            etagen.append(g.etage)
    schematisch, orte = set(), {}
    for etage in etagen:
        plan = plan_von(objekt, etage)
        if plan is not None and not plan.schema:
            continue
        svg, lagen = schema(objekt, etage, mit_zugang=etage == start)
        if plan is None:
            plan = m.Plan(etage=etage, mime="image/svg+xml", schema=True, daten=b"")
            objekt.plaene.append(plan)
        plan.mime, plan.daten = "image/svg+xml", svg.encode()
        schematisch.add(etage)
        orte.update(lagen)
    if start in schematisch:
        objekt.fiz_etage = start
        objekt.fiz_x, objekt.fiz_y = _anteil(ZUGANG)
    for g in objekt.gruppen:
        if g.etage in schematisch:
            for x in g.melder:
                x.px, x.py = _anteil(orte[x.id])
        ziel = orte.get(g.melder[0].id) if g.melder else None
        if g.etage == start:
            if start in schematisch and ziel:
                g.weg1, g.weg2 = _weg(ZUGANG, ziel), ""
        else:
            if start in schematisch:
                g.weg1 = json.dumps([_anteil(ZUGANG), _anteil((150, FLUR_Y)), _anteil(TREPPE)])
            if g.etage in schematisch and ziel:
                g.weg2 = _weg(TREPPE, ziel)
        if not g.laufweg.strip() and g.melder:
            ziel_name = g.name or g.melder[0].ort
            g.laufweg = (f"Von der FIZ dem Flur folgen\nZiel: {ziel_name}" if g.etage == start
                         else f"Von der FIZ durch den Flur zum Treppenraum\nIm Treppenraum ins {g.etage or 'Geschoss'}\nDem Flur folgen, Ziel: {ziel_name}")
    db.flush()
    return len(schematisch)
