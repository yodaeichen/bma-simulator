"""Durchlauftest ohne Netzwerk: Anmeldung, Objekt, Melderliste, Übung, Anzeigen, Protokoll.

Aufruf:  python tests/smoke_test.py
"""
import datetime as dt
import logging
import os
import re
import sys
import tempfile

os.environ.update(SECRET_KEY="x" * 40, ADMIN_PASSWORD="test-passwort-123", COOKIE_SECURE="false",
                  DATA_DIR=tempfile.mkdtemp())
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from app import db as m  # noqa: E402
from app import access, backup, katalog, laufkarte, live, sim  # noqa: E402
from app.main import app  # noqa: E402
from app.version import VERSION  # noqa: E402

logging.getLogger("httpx").setLevel(logging.WARNING)


def csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


# ---------- Anlagenverhalten ohne Web ----------
now = dt.datetime(2026, 1, 1, 12, 0, 0)
ziel = {"gruppe": 12, "melder": 3, "typ": "rm", "ort": "Flur", "gname": "Flure", "etage": "EG"}
st, log = sim.neu(), []
assert sim.nr(12, 3) == "0012/03" and sim.nr(7) == "0007"
assert sim.sicht(st)["normal"]
assert sim.alarm(st, ziel, log, now) and st["ue"] and st["summer_fat"] and st["summer_bmz"]
assert not sim.alarm(st, ziel, log, now), "derselbe Melder löst nicht doppelt aus"
assert sim.sicht(st) == {"alarme": 1, "stoerungen": 0, "abschaltungen": 0, "akustik_aktiv": True, "bfs_aktiv": True,
                         "fsd_offen": True, "normal": False}
sim.schalter(st, "akustik_ab", log, "FBF")
assert not sim.sicht(st)["akustik_aktiv"] and sim.sicht(st)["bfs_aktiv"]
sim.summer_ab(st, "fat", log)
assert not st["summer_fat"] and st["summer_bmz"]
sim.ruecksetzen(st, log, now, "FBF")
assert not sim.alarme(st) and not st["ue"] and st["akustik_ab"], "Rückstellen lässt die Schalter am FBF, wie sie sind"
assert not sim.sicht(st)["normal"], "mit abgeschalteter Akustik ist die Anlage nicht in Grundstellung"

# ÜE ab: kein Alarm an die Leitstelle; wieder einschalten bei anstehendem Alarm löst aus
st, log = sim.neu(), []
sim.schalter(st, "ue_ab", log, "FBF")
sim.alarm(st, ziel, log, now)
assert not st["ue"] and any("NICHT" in t for _, t in log)
sim.ue_pruefen(st, log, "FBF")
assert not st["ue"]
sim.schalter(st, "ue_ab", log, "FBF")
assert st["ue"]

# Ursache steht an: nach dem Rückstellen kommt der Alarm wieder
st, log = sim.neu(), []
sim.alarm(st, ziel, log, now, ansteht=True)
sim.ruecksetzen(st, log, now, "FBF")
assert not sim.alarme(st) and len(st["geplant"]) == 1
assert not sim.tick(st, log, now + dt.timedelta(seconds=2))
assert sim.tick(st, log, now + dt.timedelta(seconds=6)) and len(sim.alarme(st)) == 1 and st["ue"]
sim.ursache(st, sim.alarme(st)[0]["id"], False, log)
sim.ruecksetzen(st, log, now, "FBF")
assert not st["geplant"] and not st["meldungen"]

# Abschaltung, Störung, Sprinkler, Grundstellung
st, log = sim.neu(), []
sim.abschaltung(st, 12, log, now, gname="Flure")
assert not sim.alarm(st, ziel, log, now) and any("abgeschaltet" in t for _, t in log)
sim.abschaltung(st, 12, log, now)
assert not st["meldungen"]
sim.abschaltung(st, 12, log, now, melder=4)
assert sim.alarm(st, ziel, log, now), "nur Melder 4 ist abgeschaltet"
sim.stoerung(st, "Netzausfall", log, now)
sim.alarm(st, {**ziel, "gruppe": 20, "melder": 1, "typ": "spr"}, log, now)
assert st["loesch"] and sim.sicht(st)["stoerungen"] == 1 and sim.sicht(st)["abschaltungen"] == 1
sim.ruecksetzen(st, log, now, "BMZ")
assert [x["art"] for x in st["meldungen"]] == ["abschaltung", "stoerung"] and not st["loesch"]
v = st["v"]
sim.grundstellung(st, log)
assert sim.sicht(st)["normal"] and st["v"] > v

# Melderliste lesen
zeilen, fehler = katalog.lesen("Gruppe;Melder;Typ;Etage;Gruppenname;Ort\r\n1;1;hfm;EG;Eingang;Windfang\r\n1;2;Rauchmelder;EG;Eingang;Flur\r\n")
assert not fehler and [z["typ"] for z in zeilen] == ["hfm", "rm"]
assert katalog.lesen("1\t1\tDruckknopf\tEG\tEingang\tTür")[0][0]["typ"] == "hfm", "Tabulator und Umgangssprache"
assert katalog.lesen("1,1,rm,EG,Flur,Mitte")[0][0]["ort"] == "Mitte"
for schlecht in ("", "1;1;xx", "0;1;rm", "1;100;rm", "1;1;rm\n1;1;wm", "1;1"):
    assert katalog.lesen(schlecht)[1], schlecht

# ---------- Web ----------
with TestClient(app, base_url="http://testserver") as c:
    assert c.get("/", follow_redirects=False).status_code == 303, "ohne Anmeldung muss umgeleitet werden"
    assert c.get("/objekte/1/state").status_code == 401
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION) and c.get("/healthz").json() == {"ok": True, "version": VERSION}
    assert f"## {VERSION}" in open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read(), "CHANGELOG nachziehen"
    first = c.get("/login")
    assert f"BMA Simulator {VERSION}" in first.text and "powered by yodaeichen" in first.text
    assert "https://github.com/sponsors/yodaeichen" in first.text
    assert "default-src 'self'" in first.headers["content-security-policy"] and first.headers["x-frame-options"] == "DENY"
    tok = csrf(first.text)
    assert "falsch" in c.post("/login", data={"csrf": tok, "username": "admin", "password": "nein"}).text
    tok = csrf(c.get("/login").text)
    assert c.post("/login", data={"username": "admin", "password": "test-passwort-123"}).status_code == 403, "CSRF"
    r = c.post("/login", data={"csrf": tok, "username": "admin", "password": "test-passwort-123"})
    assert "Seniorenheim Am Musterpark" in r.text and r.text.count("Übung öffnen") == 4, "vier Beispielobjekte"
    tok = csrf(r.text)

    # Objekt anlegen und Melderliste füllen
    r = c.post("/objekte/speichern", data={"csrf": tok, "id": "", "name": "Testhalle <b>", "adresse": "Weg 1", "bma_nr": "BMA 99",
                                          "hinweis": "FIZ am Tor", "loeschanlage": "on"})
    assert "Melderliste: Testhalle &lt;b&gt;" in r.text, "nach dem Anlegen zur Melderliste, Namen maskiert"
    with m.SessionLocal() as db:
        oid = db.query(m.Objekt).filter_by(name="Testhalle <b>").one().id
    r = c.post(f"/objekte/{oid}/melder/hinzufuegen", data={"csrf": tok, "gruppe": "5", "melder": "1", "typ": "rm", "etage": "EG",
                                                          "gname": "Halle", "ort": "Tor <script>"})
    assert "0005/01" in r.text and "<script>" not in r.text.replace('<script src="/static/frage.js?v=1"></script>', "")
    r = c.post(f"/objekte/{oid}/melder/hinzufuegen", data={"csrf": tok, "gruppe": "5", "melder": "0", "typ": "rm"})
    assert "Melder muss eine Zahl" in r.text
    r = c.post(f"/objekte/{oid}/melder/import", data={"csrf": tok, "liste": "5;2;wm;EG;Halle;Kessel\n6;1;hfm;OG;Büro;Flur\n6;2;rm;OG;Büro;Büro 1"})
    assert "3 Melder übernommen" in r.text
    r = c.post(f"/objekte/{oid}/melder/import", data={"csrf": tok}, files={"datei": ("liste.csv", "7;1;spr;Lager;Sprinkler;Hochregal\n".encode("cp1252"), "text/csv")})
    assert "1 Melder übernommen" in r.text
    r = c.post(f"/objekte/{oid}/melder/import", data={"csrf": tok, "liste": "5;2;wm\n9;1;quatsch"})
    assert "Nichts übernommen" in r.text
    export = c.get(f"/objekte/{oid}/melder.csv").text
    assert export.startswith("﻿Gruppe;Melder;Typ;Etage;Gruppenname;Ort") and "6;2;rm;OG;Büro;Büro 1" in export
    assert katalog.lesen(export)[0] and len(katalog.lesen(export)[0]) == 5, "Export lässt sich wieder einlesen"
    with m.SessionLocal() as db:
        o = db.get(m.Objekt, oid)
        token = o.token
        ids = {(g.nummer, x.nummer): x.id for g in o.gruppen for x in g.melder}
        gid = {g.nummer: g.id for g in o.gruppen}
        fremd = db.query(m.Melder).join(m.Gruppe).filter(m.Gruppe.objekt_id != oid).first().id

    # Ausbilderansicht
    r = c.get(f"/objekte/{oid}")
    assert f"/a/{token}" in r.text and 'data-melder="%d"' % ids[(5, 1)] in r.text and "FIZ am Tor" in r.text
    assert c.get(f"/objekte/{oid}/qr.svg").headers["content-type"].startswith("image/svg")
    kopf = {"X-CSRF": tok}

    def akt(**body):
        return c.post(f"/objekte/{oid}/aktion", json=body, headers=kopf)

    assert c.post(f"/objekte/{oid}/aktion", json={"aktion": "grundstellung"}).status_code == 403, "CSRF"
    assert akt(aktion="alarm", melder_id=fremd).status_code == 404, "Melder eines anderen Objekts"
    assert akt(aktion="unsinn").status_code == 400
    d = akt(aktion="alarm", melder_id=ids[(5, 1)], ansteht=True).json()
    assert d["sicht"]["alarme"] == 1 and d["st"]["ue"] and d["st"]["meldungen"][0]["ort"] == "Tor <script>"
    assert "Ausbilder admin" in d["protokoll"][-1]["quelle"] or any("Ausbilder admin" == z["quelle"] for z in d["protokoll"])
    v = d["st"]["v"]
    assert d["live"] == [] and c.get(f"/objekte/{oid}/state?v={v}&pv={d['pv']}").status_code == 204
    assert c.get(f"/objekte/{oid}/state?v={v}").status_code == 200, "ohne Fingerabdruck des Live-Bilds kommt der volle Stand"
    assert c.get(f"/objekte/{oid}/state?v=0").json()["st"]["v"] == v

    # Anzeigen der Übenden: ohne Anmeldung, aber nur mit der geheimen Adresse
    with TestClient(app, base_url="http://testserver") as gast:
        assert gast.get("/a/falsch-falsch").status_code == 404 and gast.get("/a/x/state").status_code == 404
        for seite, wort in (("", "FAT und FBF"), ("/fat", "Feuerwehr-Bedienfeld"), ("/bmz", "Brandmelderzentrale"), ("/verzeichnis", "0006/02")):
            r = gast.get(f"/a/{token}{seite}")
            assert r.status_code == 200 and wort in r.text and "csrf" not in r.text, seite
        d = gast.get(f"/a/{token}/state").json()
        assert "geplant" not in d["st"] and "ansteht" not in d["st"]["meldungen"][0], "nichts für die Übenden Verborgenes"
        assert d["sicht"]["alarme"] == 1 and gast.get(f"/a/{token}/state?v={d['st']['v']}").status_code == 204
        assert gast.post(f"/a/{token}/aktion", json={"geraet": "fat", "aktion": "ruecksetzen"}).status_code == 400, "das FAT stellt nicht zurück"
        assert gast.post(f"/a/{token}/aktion", json={"geraet": "fbf", "aktion": "grundstellung"}).status_code == 400
        assert gast.post(f"/a/{token}/aktion", content=b"x" * 5000).status_code == 413
        assert gast.post(f"/objekte/{oid}/aktion", json={"aktion": "grundstellung"}).status_code == 401
        # Live-Bild: Die Anzeige meldet, was sie zeigt und was gedrückt wurde
        lcd = "0005/01 FEUER    001\nTor <script>"
        assert gast.get(f"/a/{token}/state", params={"v": d["st"]["v"], "c": "ab12cd34", "g": "fat", "e": "stoerung", "o": "1", "t": "0",
                                                     "kn": "0", "k": "", "l": lcd}).status_code == 204
        gast.get(f"/a/{token}/state", params={"v": d["st"]["v"], "c": "ab12cd34", "g": "fat", "e": "stoerung", "o": "1", "t": "0",
                                              "kn": "1", "k": "Anzeigeebene" + "x" * 100})
        assert gast.get(f"/a/{token}/da", params={"c": "zz99zz99", "g": "verz"}).status_code == 204
        gast.get(f"/a/{token}/da", params={"c": "<script>", "g": "verz"})
        gast.get(f"/a/{token}/da", params={"c": "qq11qq11", "g": "unsinn"})
        bild = c.get(f"/objekte/{oid}/state?v=0").json()
        assert [g["name"] for g in bild["live"]] == ["FAT und FBF", "Meldergruppenverzeichnis"], "ungültige Meldungen zählen nicht"
        fat = bild["live"][0]
        assert fat["id"] == "AB12" and fat["lcd"] == lcd.split("\n") and fat["ebene"] == "stoerung" and fat["offen"] and not fat["ton"]
        assert fat["taste"].startswith("Anzeigeebene") and len(fat["taste"]) == 60 and fat["taste_zeit"], "Text der Taste gekürzt"
        assert c.get(f"/objekte/{oid}/state?v={bild['st']['v']}&pv={bild['pv']}").status_code == 204
        with live._lock:  # sechs Sekunden ohne Lebenszeichen: Gerät gilt als getrennt
            for e in live._geraete[oid].values():
                e["gesehen"] -= 10
        assert c.get(f"/objekte/{oid}/state?v={bild['st']['v']}&pv={bild['pv']}").json()["live"] == []
        d = gast.post(f"/a/{token}/aktion", json={"geraet": "fat", "aktion": "summer_ab"}).json()
        assert not d["st"]["summer_fat"] and d["st"]["summer_bmz"]
        d = gast.post(f"/a/{token}/aktion", json={"geraet": "fbf", "aktion": "akustik_ab"}).json()
        assert d["st"]["akustik_ab"] and not d["sicht"]["akustik_aktiv"]
        d = gast.post(f"/a/{token}/aktion", json={"geraet": "fbf", "aktion": "ruecksetzen"}).json()
        assert d["sicht"]["alarme"] == 0 and not d["st"]["ue"]

    # Ursache steht an: der Alarm ist vorgemerkt und kommt wieder
    d = c.get(f"/objekte/{oid}/state?v=0").json()
    assert len(d["st"]["geplant"]) == 1 and any(z["quelle"] == "FBF" and z["text"] == "BMZ rückgestellt" for z in d["protokoll"])
    with m.SessionLocal() as db:  # Uhr vorstellen statt warten
        o = db.get(m.Objekt, oid)
        o.state = o.state.replace(d["st"]["geplant"][0]["faellig"], "2000-01-01T00:00:00Z")
        db.commit()
    d = c.get(f"/objekte/{oid}/state?v=0").json()
    assert d["sicht"]["alarme"] == 1 and not d["st"]["geplant"] and d["st"]["ue"]
    assert akt(aktion="ursache", id=d["st"]["meldungen"][0]["id"], ansteht=False).json()["st"]["meldungen"][0]["ansteht"] is False

    # Verzögerung, Ausbreitung, Abschaltung, Störung, Löschanlage
    d = akt(aktion="alarm", melder_id=ids[(6, 2)], sekunden=30, ausbreitung=10).json()
    assert d["sicht"]["alarme"] == 1 and len(d["st"]["geplant"]) == 1, "nur der Melder selbst: der Nachbar ist ein Handfeuermelder"
    assert not akt(aktion="vormerkungen_loeschen").json()["st"]["geplant"]
    d = akt(aktion="alarm", melder_id=ids[(5, 2)], ausbreitung=10).json()
    assert d["sicht"]["alarme"] == 2 and not d["st"]["geplant"], "5/1 brennt schon, sonst gibt es im EG keinen automatischen Melder"
    d = akt(aktion="abschaltung", gruppe_id=gid[6]).json()
    assert d["sicht"]["abschaltungen"] == 1
    d = akt(aktion="alarm", melder_id=ids[(6, 1)]).json()
    assert d["sicht"]["alarme"] == 2 and "abgeschaltet" in d["protokoll"][0]["text"]
    assert akt(aktion="abschaltung", gruppe_id=gid[6]).json()["sicht"]["abschaltungen"] == 0
    d = akt(aktion="stoerung", text="Netzausfall").json()
    assert d["sicht"]["stoerungen"] == 1 and d["st"]["meldungen"][-1]["gruppe"] is None
    d = akt(aktion="stoerung", melder_id=ids[(6, 2)], text="Melder gestört").json()
    assert d["sicht"]["stoerungen"] == 2 and d["st"]["meldungen"][-1]["ort"] == "Büro 1", "am FAT steht der Ort des Melders"
    assert akt(aktion="stoerung", melder_id=ids[(6, 2)], text="Melder gestört").json()["sicht"]["stoerungen"] == 2, "nicht doppelt"
    assert akt(aktion="loeschanlage", an=True).json()["st"]["loesch"]
    d = akt(aktion="alarm", melder_id=ids[(7, 1)]).json()
    assert d["sicht"]["alarme"] == 3
    d = akt(aktion="grundstellung").json()
    assert d["sicht"]["normal"] and not d["st"]["meldungen"]

    # Protokoll
    protokoll = c.get(f"/objekte/{oid}/protokoll.csv").text
    assert "Zeit;Quelle;Ereignis" in protokoll and "FBF;BMZ rückgestellt" in protokoll and "Grundstellung" in protokoll
    r = c.post(f"/objekte/{oid}/protokoll/leeren", data={"csrf": tok})
    assert c.get(f"/objekte/{oid}/protokoll.csv").text.count("\r\n") == 2, "Kopfzeile und der Vermerk über das Leeren"

    # Laufkarten
    assert laufkarte.bildart(b"\x89PNG\r\n\x1a\n....") == "image/png" and laufkarte.bildart(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert laufkarte.bildart(b'<?xml version="1.0"?><svg xmlns="x"/>') == "image/svg+xml" and laufkarte.bildart(b"%PDF-1.7") is None
    assert laufkarte.bildart(b"<html><svg>") is None
    assert laufkarte.punkte('[[0.1,0.2],[2,0],["a",1],[0.5,0.5,0.5],[true,0],[1,1]]') == [[0.1, 0.2], [1.0, 1.0]] and laufkarte.punkte("{") == []
    r = c.get(f"/objekte/{oid}/laufkarten")
    assert r.text.count("Plan fehlt") == 3 and "Schemapläne erzeugen" in r.text, "selbst angelegtes Objekt hat noch keine Pläne"
    r = c.get(f"/objekte/{oid}/laufkarten/druck")
    assert r.text.count('class="lk-seite"') == 6 and "kein Plan hinterlegt" in r.text and "Feuerwehr-Laufkarte" in r.text
    r = c.post(f"/objekte/{oid}/laufkarten/schema", data={"csrf": tok})
    assert "3 Schemapläne erzeugt" in r.text and r.text.count("vollständig") == 3
    with m.SessionLocal() as db:
        o = db.get(m.Objekt, oid)
        plaene = {pl.etage: pl.id for pl in o.plaene}
        g6 = next(g for g in o.gruppen if g.nummer == 6)
        k = laufkarte.karte(o, g6)
        assert laufkarte.fiz_etage(o) == "EG" and not k["gleich"] and len(k["weg1"]) == 3 and len(k["weg2"]) >= 2 and k["fiz"]
        assert all(x.px is not None and 0 < x.px < 1 and 0 < x.py < 1 for g in o.gruppen for x in g.melder)
        assert k["schritte"][-1].endswith("Büro") and laufkarte.karte(o, o.gruppen[0])["gleich"]
        g6id, m61 = g6.id, g6.melder[0].id
    r = c.get(f"/plaene/{plaene['OG']}")
    assert r.headers["content-type"].startswith("image/svg") and "sandbox" in r.headers["content-security-policy"] and "Schemaplan OG" in r.text
    assert "Büro 1" in r.text and "Zugang Feuerwehr" not in r.text and "Zugang Feuerwehr" in c.get(f"/plaene/{plaene['EG']}").text
    r = c.get(f"/objekte/{oid}/laufkarten/druck?gruppe=6")
    assert r.text.count('class="lk-seite"') == 2 and "<polyline" in r.text and 'class="m melder hfm"' in r.text and "0006/02" in r.text
    assert f'/plaene/{plaene["EG"]}"' in r.text and f'/plaene/{plaene["OG"]}"' in r.text, "vorn die Etage der FIZ, hinten die der Gruppe"
    # von Hand bearbeiten
    r = c.get(f"/gruppen/{g6id}/laufkarte")
    assert "Vorderseite: EG" in r.text and "Rückseite: OG" in r.text and "laufkarte_edit.js" in r.text
    r = c.post(f"/gruppen/{g6id}/laufkarte", data={"csrf": tok, "laufweg": "Durch die Halle\nTreppe Nord ins OG", "hinweis": "Zwischendecke <b>",
                                                   "fiz": "[0.9, 0.5]", "weg1": "[[0.9,0.5],[0.5,0.5],[7,7]]", "weg2": "[[0.1,0.5],[0.4,0.2]]",
                                                   "melder": '{"%d": [0.25, 0.75], "999999": [0.1, 0.1]}' % m61})
    assert "Laufkarte 0006 gespeichert" in r.text
    with m.SessionLocal() as db:
        g6 = db.get(m.Gruppe, g6id)
        assert g6.weg1 == "[[0.9, 0.5], [0.5, 0.5]]" and g6.weg2 == "[[0.1, 0.5], [0.4, 0.2]]" and (g6.melder[0].px, g6.melder[0].py) == (0.25, 0.75)
        assert g6.objekt.fiz_x == 0.9 and g6.melder[1].px is not None, "nicht genannte Melder bleiben, wo sie sind"
    r = c.get(f"/objekte/{oid}/laufkarten/druck?gruppe=6")
    assert "Treppe Nord ins OG" in r.text and "Zwischendecke &lt;b&gt;" in r.text and "left:25.0%;top:75.0%" in r.text
    # eigenen Plan hochladen
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    assert "muss ein Bild sein" in c.post(f"/objekte/{oid}/plan", data={"csrf": tok, "etage": "OG"}, files={"datei": ("plan.pdf", b"%PDF-1.7 ...", "application/pdf")}).text
    assert "höchstens 4 MB" in c.post(f"/objekte/{oid}/plan", data={"csrf": tok, "etage": "OG"}, files={"datei": ("gross.png", png + b"0" * laufkarte.MAX_PLAN, "image/png")}).text
    r = c.post(f"/objekte/{oid}/plan", data={"csrf": tok, "etage": "OG"}, files={"datei": ("og.png", png, "image/png")})
    assert "Plan für „OG“ gespeichert" in r.text and "neu einzeichnen" in r.text and "eigener Plan" in r.text
    assert c.get(f"/plaene/{plaene['OG']}").content == png
    with m.SessionLocal() as db:
        g6 = db.get(m.Gruppe, g6id)
        assert g6.weg2 == "" and g6.melder[0].px is None and g6.weg1, "Lagen aus dem Schemaplan passen nicht zum neuen Bild"
    r = c.post(f"/objekte/{oid}/laufkarten/schema", data={"csrf": tok})
    assert "2 Schemapläne erzeugt" in r.text and c.get(f"/plaene/{plaene['OG']}").content == png, "eigene Pläne bleiben unberührt"
    assert "Plan gelöscht" in c.post(f"/plaene/{plaene['OG']}/loeschen", data={"csrf": tok}).text
    c.post(f"/objekte/{oid}/laufkarten/schema", data={"csrf": tok})
    r = c.post(f"/objekte/{oid}/laufkarten/fiz", data={"csrf": tok, "fiz_etage": "OG"})
    assert "Etage der FIZ geändert" in r.text
    c.post(f"/objekte/{oid}/laufkarten/schema", data={"csrf": tok})
    with m.SessionLocal() as db:
        o = db.get(m.Objekt, oid)
        assert laufkarte.fiz_etage(o) == "OG" and laufkarte.karte(o, db.get(m.Gruppe, g6id))["gleich"] and db.get(m.Gruppe, g6id).weg2 == ""
        pid_og = laufkarte.plan_von(o, "OG").id
        fremder_plan = db.query(m.Plan).filter(m.Plan.objekt_id != oid).first().id
    assert "Zugang Feuerwehr" in c.get(f"/plaene/{pid_og}").text
    # die Übenden
    with TestClient(app, base_url="http://testserver") as gast:
        r = gast.get(f"/a/{token}/laufkarten")
        assert r.status_code == 200 and f"/a/{token}/laufkarte/6" in r.text and "0005" in r.text
        r = gast.get(f"/a/{token}/laufkarte/6")
        assert r.text.count('class="lk-seite"') == 2 and f"/a/{token}/plan/{pid_og}" in r.text and "/plaene/" not in r.text and "◀ 0005" in r.text
        assert gast.get(f"/a/{token}/laufkarte/99").status_code == 404
        assert gast.get(f"/a/{token}/laufkarten/alle").text.count('class="lk-seite"') == 6
        assert gast.get(f"/a/{token}/plan/{pid_og}").status_code == 200
        assert gast.get(f"/a/{token}/plan/{fremder_plan}").status_code == 404, "Pläne anderer Objekte bleiben verborgen"
        assert gast.get(f"/plaene/{pid_og}", follow_redirects=False).status_code == 303
        gast.get(f"/a/{token}/da", params={"c": "lk12lk12", "g": "lauf", "i": "Laufkarte 0006 Büro"})
        bild = c.get(f"/objekte/{oid}/state?v=0").json()["live"]
        assert bild[-1]["name"] == "Laufkarten" and bild[-1]["info"] == "Laufkarte 0006 Büro"
    live.vergessen(oid)
    assert c.get("/plaene/%d" % fremder_plan).status_code == 200, "Beispielobjekte haben von Anfang an Schemapläne"
    assert c.get("/objekte/1/laufkarten").text.count("vollständig") == 9

    # Adresse erneuern, kopieren, löschen
    c.post(f"/objekte/{oid}/link-erneuern", data={"csrf": tok})
    assert c.get(f"/a/{token}/fat").status_code == 404, "die alte Adresse gilt nicht mehr"
    r = c.post(f"/objekte/{oid}/kopieren", data={"csrf": tok})
    assert "(Kopie)" in r.text
    with m.SessionLocal() as db:
        kopie = db.query(m.Objekt).filter(m.Objekt.name.like("%(Kopie)")).one()
        assert sum(len(g.melder) for g in kopie.gruppen) == 5 and kopie.token != token
        assert len(kopie.plaene) == 3 and kopie.fiz_etage == "OG" and all(x.px is not None for g in kopie.gruppen for x in g.melder)
        kid = kopie.id
    assert c.post(f"/melder/{ids[(7, 1)]}/loeschen", data={"csrf": tok}).status_code == 200
    with m.SessionLocal() as db:
        assert 7 not in {g.nummer for g in db.get(m.Objekt, oid).gruppen}, "leere Gruppe verschwindet mit dem letzten Melder"
    assert "gelöscht" in c.post(f"/gruppen/{gid[6]}/loeschen", data={"csrf": tok}).text
    assert "gelöscht" in c.post(f"/objekte/{kid}/loeschen", data={"csrf": tok}).text
    assert c.get(f"/objekte/{kid}").status_code == 404

    # Benutzer und Rechte
    assert c.get("/hilfe").status_code == 200 and "Rolle: Administrator" in c.get("/konto").text
    r = c.get("/benutzer")
    assert "Benutzer anlegen" in r.text and 'class="dot on"' in r.text
    def rechte(**p):
        return {f"p_{k}": str(v) for k, v in p.items()}
    assert "mindestens 12" in c.post("/benutzer/speichern", data={"csrf": tok, "username": "anna", "password": "kurz", **rechte(objekte=2, uebung=2, protokoll=2, users=0)}).text
    r = c.post("/benutzer/speichern", data={"csrf": tok, "username": "anna", "password": "anna-passwort-1", "objekt": [str(oid)],
                                           **rechte(objekte=2, uebung=2, protokoll=1, users=0)})
    assert "gespeichert" in r.text and "Angepasst" in r.text and "Testhalle" in r.text
    assert "gibt es schon" in c.post("/benutzer/speichern", data={"csrf": tok, "username": "Anna", "password": "anna-passwort-1"}).text
    assert "nicht löschen" in c.post("/benutzer/1/loeschen", data={"csrf": tok}).text
    assert "nicht selbst nehmen" in c.post("/benutzer/speichern", data={"csrf": tok, "id": "1", **rechte(objekte=2, uebung=2, protokoll=2, users=0)}).text
    with m.SessionLocal() as db:
        anna = db.query(m.User).filter_by(username="anna").one()
        assert access.role_of(anna) == "Angepasst" and not access.sees_all(anna) and access.objekt_ids(anna) == {oid}
        assert access.role_of(db.get(m.User, 1)) == "Administrator"
        alt = m.User(username="alt", password_hash="x", is_admin=False)  # Konto aus Version 1.0 ohne eigene Rechte
        assert access.role_of(alt) == "Ausbilder" and access.sees_all(alt)
        alt.is_admin = True
        assert access.role_of(alt) == "Administrator"
    with TestClient(app, base_url="http://testserver") as a:
        t2 = csrf(a.get("/login").text)
        r = a.post("/login", data={"csrf": t2, "username": "anna", "password": "anna-passwort-1"})
        assert r.text.count("Übung öffnen") == 1 and "Testhalle" in r.text and "Seniorenheim" not in r.text, "nur das freigegebene Objekt"
        assert 'href="/benutzer"' not in r.text and 'href="/sicherung"' not in r.text
        t2 = csrf(r.text)
        for pfad in ("/benutzer", "/benutzer/neu", "/sicherung"):
            r = a.get(pfad)
            assert r.status_code == 403 and "Kein Zugriff" in r.text, pfad
        assert a.post("/sicherung/herunterladen", data={"csrf": t2}).status_code == 403
        assert a.get("/objekte/1").status_code == 404 and a.get("/objekte/1/state").status_code == 404, "fremdes Objekt ist unsichtbar"
        assert a.post("/objekte/1/aktion", json={"aktion": "grundstellung"}, headers={"X-CSRF": t2}).status_code == 404
        assert a.get("/objekte/1/melder.csv").status_code == 404 and a.post("/objekte/1/loeschen", data={"csrf": t2}).status_code == 404
        assert a.post(f"/objekte/{oid}/aktion", json={"aktion": "grundstellung"}, headers={"X-CSRF": t2}).status_code == 200
        r = a.get(f"/objekte/{oid}")
        assert "Übungsprotokoll" in r.text and "protokoll/leeren" not in r.text
        assert a.post(f"/objekte/{oid}/protokoll/leeren", data={"csrf": t2}).status_code == 403, "Protokoll nur sehen"
        r = a.post("/objekte/speichern", data={"csrf": t2, "id": "", "name": "Annas Halle"})
        assert "Melderliste: Annas Halle" in r.text and a.get("/").text.count("Übung öffnen") == 2, "selbst angelegtes Objekt ist freigegeben"
        assert "stimmt nicht" in a.post("/konto", data={"csrf": t2, "alt": "falsch", "neu": "neues-passwort-1", "neu2": "neues-passwort-1"}).text
        assert "geändert" in a.post("/konto", data={"csrf": t2, "alt": "anna-passwort-1", "neu": "neues-passwort-1", "neu2": "neues-passwort-1"}).text
        assert a.post("/logout", data={"csrf": t2}).status_code == 200 and a.get("/", follow_redirects=False).status_code == 303
    with m.SessionLocal() as db:
        assert db.get(m.User, anna.id).last_seen is None, "nach dem Abmelden nicht mehr als aktiv geführt"

    # Beobachter: sieht zu, löst nichts aus; Anlage ohne Passwort ergibt einen Einmal-Link
    r = c.post("/benutzer/speichern", data={"csrf": tok, "username": "ben", "password": "", "all_objekte": "on", **rechte(objekte=1, uebung=1, protokoll=0, users=0)})
    link = re.search(r"/einladung/([\w-]+)", r.text).group(1)
    assert "Gib ihm den Link" in r.text
    with m.SessionLocal() as db:
        ben = db.query(m.User).filter_by(username="ben").one()
        assert ben.password_hash == "" and link not in ben.invite_hash and len(ben.invite_hash) == 64, "gespeichert ist nur der Hash"
    assert link not in c.get(f"/benutzer/{ben.id}/bearbeiten").text, "der Link wird nur einmal gezeigt"
    assert "Einladung offen" in c.get("/benutzer").text
    with TestClient(app, base_url="http://testserver") as b:
        t3 = csrf(b.get("/login").text)
        assert "falsch" in b.post("/login", data={"csrf": t3, "username": "ben", "password": ""}).text, "ohne Passwort keine Anmeldung"
        assert "ungültig oder abgelaufen" in b.get("/einladung/gibtsnicht").text
        r = b.get(f"/einladung/{link}")
        assert "Hallo <strong>ben</strong>" in r.text
        t3 = csrf(r.text)
        assert "beide Eingaben" in b.post(f"/einladung/{link}", data={"csrf": t3, "password": "bens-passwort-1", "repeat": "anders"}).text
        assert "Du kannst dich jetzt anmelden" in b.post(f"/einladung/{link}", data={"csrf": t3, "password": "bens-passwort-1", "repeat": "bens-passwort-1"}).text
        assert "ungültig oder abgelaufen" in b.get(f"/einladung/{link}").text, "der Link gilt nur einmal"
        r = b.post("/login", data={"csrf": csrf(b.get("/login").text), "username": "ben", "password": "bens-passwort-1"})
        assert "Übung ansehen" in r.text and "Neues Objekt" not in r.text
        t3 = csrf(r.text)
        r = b.get(f"/objekte/{oid}")
        assert 'data-steuern="0"' in r.text and "Grundstellung" not in r.text and "Übungsprotokoll" not in r.text and "Live-Bild" in r.text
        assert "protokoll" not in b.get(f"/objekte/{oid}/state").json()
        r = b.post(f"/objekte/{oid}/aktion", json={"aktion": "grundstellung"}, headers={"X-CSRF": t3})
        assert r.status_code == 403 and "Übungen" in r.json()["detail"]
        assert b.get(f"/objekte/{oid}/protokoll.csv").status_code == 403 and b.get("/objekte/neu").status_code == 403
        assert b.post(f"/objekte/{oid}/melder/import", data={"csrf": t3, "liste": "1;1;rm"}).status_code == 403
        r = b.get(f"/objekte/{oid}/melder")
        assert r.status_code == 200 and "Liste einlesen" not in r.text and "Löschen" not in r.text
    r = c.post(f"/benutzer/{ben.id}/einladung", data={"csrf": tok})
    assert "/einladung/" in r.text and "Neuer Link erzeugt" in r.text
    r = c.post("/benutzer/speichern", data={"csrf": tok, "id": str(ben.id), "all_objekte": "on", **rechte(objekte=1, uebung=1, protokoll=1, users=0)})
    assert "Beobachter" in r.text
    assert "gelöscht" in c.post(f"/benutzer/{ben.id}/loeschen", data={"csrf": tok}).text
    assert "gelöscht" in c.post(f"/benutzer/{anna.id}/loeschen", data={"csrf": tok}).text

    # Sicherung
    import io, sqlite3, zipfile
    r = c.get("/sicherung")
    assert "Noch keine Sicherung abgelegt" in r.text and backup.auto_due()
    r = c.post("/sicherung/herunterladen", data={"csrf": tok})
    assert r.headers["content-type"] == "application/zip" and re.search(r'bma-simulator-\d{8}-\d{6}\.zip', r.headers["content-disposition"])
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert sorted(z.namelist()) == ["LIESMICH.txt", "simulator.db"] and "Wiederherstellen" in z.read("LIESMICH.txt").decode()
        ziel = os.path.join(tempfile.mkdtemp(), "simulator.db")
        open(ziel, "wb").write(z.read("simulator.db"))
    con = sqlite3.connect(ziel)
    assert con.execute("select count(*) from objekte").fetchone()[0] == 6 and con.execute("pragma integrity_check").fetchone()[0] == "ok"
    con.close()
    r = c.post("/sicherung/ablegen", data={"csrf": tok})
    name = re.search(r"bma-simulator-\d{8}-\d{6}\.zip", r.text).group(0)
    assert "abgelegt" in r.text and not backup.auto_due() and c.get(f"/sicherung/datei/{name}").content[:2] == b"PK"
    assert c.get("/sicherung/datei/..%2Fsimulator.db").status_code == 404 and backup.path_of("../simulator.db") is None
    assert backup.store(auto=True).endswith("-auto.zip") and "automatisch" in c.get("/sicherung").text
    assert "gelöscht" in c.post(f"/sicherung/datei/{name}/loeschen", data={"csrf": tok}).text and backup.path_of(name) is None

    # Anmeldesperre nach fünf Fehlversuchen
    with TestClient(app, base_url="http://testserver") as b:
        for _ in range(5):
            b.post("/login", data={"csrf": csrf(b.get("/login").text), "username": "admin", "password": "falsch"})
        assert "Zu viele Fehlversuche" in b.post("/login", data={"csrf": csrf(b.get("/login").text), "username": "admin", "password": "test-passwort-123"}).text

# Datenbank aus Version 1.0: fehlende Spalten kommen beim Start dazu, alte Konten behalten ihre Rolle
import sqlite3  # noqa: E402

alt_db = os.path.join(m.DATA_DIR, "alt.db")
con = sqlite3.connect(alt_db)
con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(80), password_hash VARCHAR(200), is_admin BOOLEAN NOT NULL DEFAULT 0, last_login DATETIME)")
con.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('chef', 'x', 1), ('azubi', 'x', 0)")
con.execute("CREATE TABLE objekte (id INTEGER PRIMARY KEY, name VARCHAR(120), adresse VARCHAR(200) DEFAULT '', bma_nr VARCHAR(40) DEFAULT '', "
            "hinweis TEXT DEFAULT '', loeschanlage BOOLEAN DEFAULT 0, token VARCHAR(40), state TEXT DEFAULT '')")
con.execute("CREATE TABLE gruppen (id INTEGER PRIMARY KEY, objekt_id INTEGER, nummer INTEGER, name VARCHAR(80), etage VARCHAR(40))")
con.execute("CREATE TABLE melder (id INTEGER PRIMARY KEY, gruppe_id INTEGER, nummer INTEGER, typ VARCHAR(10), ort VARCHAR(80))")
con.execute("INSERT INTO objekte (name, token) VALUES ('Altbau', 'tokentokentoken')")
con.execute("INSERT INTO gruppen (objekt_id, nummer, name, etage) VALUES (1, 1, 'Flur', 'EG'), (1, 2, 'Büro', 'OG')")
con.execute("INSERT INTO melder (gruppe_id, nummer, typ, ort) VALUES (1, 1, 'hfm', 'Flur'), (2, 1, 'rm', 'Büro 1')")
con.commit()
con.close()
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

haupt, m.engine = m.engine, create_engine(f"sqlite:///{alt_db}")
try:
    m.add_missing_columns()
    m.add_missing_columns()  # zweiter Lauf ändert nichts
    with Session(m.engine) as db:
        rollen = {u.username: (access.role_of(u), access.sees_all(u)) for u in db.query(m.User)}
    assert rollen == {"chef": ("Administrator", True), "azubi": ("Ausbilder", True)}, rollen
    m.Base.metadata.create_all(m.engine)  # legt die neue Tabelle der Pläne an
    with Session(m.engine) as db:  # ein Objekt aus Version 1.0 bekommt Laufkarten per Knopfdruck
        altbau = db.get(m.Objekt, 1)
        assert altbau.fiz_x is None and altbau.gruppen[0].weg1 == "" and altbau.gruppen[1].melder[0].px is None
        assert laufkarte.schema_erzeugen(db, altbau) == 2 and all(s["plan"] and s["weg"] for s in laufkarte.stand(altbau))
finally:
    m.engine = haupt

print("Alle Prüfungen bestanden.")
