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
from app import katalog, sim  # noqa: E402
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
    assert c.get(f"/objekte/{oid}/state?v={v}").status_code == 204
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

    # Adresse erneuern, kopieren, löschen
    c.post(f"/objekte/{oid}/link-erneuern", data={"csrf": tok})
    assert c.get(f"/a/{token}/fat").status_code == 404, "die alte Adresse gilt nicht mehr"
    r = c.post(f"/objekte/{oid}/kopieren", data={"csrf": tok})
    assert "(Kopie)" in r.text
    with m.SessionLocal() as db:
        kopie = db.query(m.Objekt).filter(m.Objekt.name.like("%(Kopie)")).one()
        assert sum(len(g.melder) for g in kopie.gruppen) == 5 and kopie.token != token
        kid = kopie.id
    assert c.post(f"/melder/{ids[(7, 1)]}/loeschen", data={"csrf": tok}).status_code == 200
    with m.SessionLocal() as db:
        assert 7 not in {g.nummer for g in db.get(m.Objekt, oid).gruppen}, "leere Gruppe verschwindet mit dem letzten Melder"
    assert "gelöscht" in c.post(f"/gruppen/{gid[6]}/loeschen", data={"csrf": tok}).text
    assert "gelöscht" in c.post(f"/objekte/{kid}/loeschen", data={"csrf": tok}).text
    assert c.get(f"/objekte/{kid}").status_code == 404

    # Benutzer
    assert c.get("/hilfe").status_code == 200 and c.get("/konto").status_code == 200
    assert "mindestens 12" in c.post("/benutzer/speichern", data={"csrf": tok, "username": "anna", "password": "kurz"}).text
    assert "angelegt" in c.post("/benutzer/speichern", data={"csrf": tok, "username": "anna", "password": "anna-passwort-1"}).text
    assert "gibt es schon" in c.post("/benutzer/speichern", data={"csrf": tok, "username": "Anna", "password": "anna-passwort-1"}).text
    assert "nicht löschen" in c.post("/benutzer/1/loeschen", data={"csrf": tok}).text
    with TestClient(app, base_url="http://testserver") as a:
        t2 = csrf(a.get("/login").text)
        r = a.post("/login", data={"csrf": t2, "username": "anna", "password": "anna-passwort-1"})
        assert "Übung öffnen" in r.text and 'href="/benutzer"' not in r.text
        assert a.get("/benutzer").status_code == 403, "Ausbilder verwalten keine Benutzer"
        t2 = csrf(r.text)
        assert "stimmt nicht" in a.post("/konto", data={"csrf": t2, "alt": "falsch", "neu": "neues-passwort-1", "neu2": "neues-passwort-1"}).text
        assert "geändert" in a.post("/konto", data={"csrf": t2, "alt": "anna-passwort-1", "neu": "neues-passwort-1", "neu2": "neues-passwort-1"}).text
        assert a.post("/logout", data={"csrf": t2}).status_code == 200 and a.get("/", follow_redirects=False).status_code == 303
    assert "gelöscht" in c.post("/benutzer/2/loeschen", data={"csrf": tok}).text

    # Anmeldesperre nach fünf Fehlversuchen
    with TestClient(app, base_url="http://testserver") as b:
        for _ in range(5):
            b.post("/login", data={"csrf": csrf(b.get("/login").text), "username": "admin", "password": "falsch"})
        assert "Zu viele Fehlversuche" in b.post("/login", data={"csrf": csrf(b.get("/login").text), "username": "admin", "password": "test-passwort-123"}).text

print("Alle Prüfungen bestanden.")
