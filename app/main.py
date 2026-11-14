"""Web-Oberfläche: Ausbilderansicht, Verwaltung der Objekte und die Anzeigen für die Übenden."""
import csv
import datetime as dt
import hmac
import io
import json
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

import segno
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import db as m
from . import katalog, sim
from . import security as sec
from .version import VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bma")

BASE = os.path.dirname(__file__)
TZ = ZoneInfo(os.environ.get("TZ", "Europe/Berlin"))
LOG_KEEP = int(os.environ.get("LOG_KEEP", "2000"))  # Protokollzeilen je Objekt
MAX_UPLOAD = 512 * 1024
_state_lock = threading.Lock()  # genau ein Prozess: Zustandsänderungen laufen nacheinander


@asynccontextmanager
async def lifespan(_app):
    m.init_db()
    with m.SessionLocal() as db:
        if not db.scalar(select(func.count(m.User.id))):
            password = os.environ.get("ADMIN_PASSWORD", "")
            if len(password) < 12:
                raise RuntimeError("ADMIN_PASSWORD fehlt oder ist kürzer als 12 Zeichen (siehe .env.example).")
            db.add(m.User(username=os.environ.get("ADMIN_USER", "admin"), password_hash=sec.hash_password(password),
                          is_admin=True))
            db.commit()
            log.info("Erster Benutzer wurde angelegt.")
            if os.environ.get("BEISPIELE", "true").lower() == "true":
                log.info("%s Beispielobjekte angelegt.", katalog.beispiele_anlegen(db))
    log.info("BMA Simulator %s gestartet.", VERSION)
    yield


app = FastAPI(title="BMA Simulator", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=sec.SESSION_SECRET, session_cookie="bma_session", same_site="lax",
                   https_only=os.environ.get("COOKIE_SECURE", "true").lower() == "true", max_age=12 * 3600)
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))
templates.env.globals.update(version=VERSION, typen=sim.TYPEN, nr=sim.nr)
templates.env.filters["localtime"] = lambda value: (
    value.replace(tzinfo=dt.timezone.utc).astimezone(TZ).strftime("%d.%m.%Y %H:%M:%S") if value else "nie")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
    return response


class LoginRequired(Exception):
    pass


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, _exc):
    if request.url.path.endswith(("/state", "/aktion")):
        return JSONResponse({"detail": "Nicht angemeldet."}, status_code=401)
    return RedirectResponse("/login", status_code=303)


def get_db():
    with m.SessionLocal() as db:
        yield db


def current_user(request: Request, db: Session = Depends(get_db)) -> m.User:
    uid = request.session.get("uid")
    user = db.get(m.User, uid) if uid else None
    if not user:
        raise LoginRequired()
    return user


def admin_user(user: m.User = Depends(current_user)) -> m.User:
    if not user.is_admin:
        raise HTTPException(403, "Nur für Administratoren.")
    return user


def csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


def check_csrf(request: Request, value: str):
    if not hmac.compare_digest(str(value), request.session.get("csrf", "-")):
        raise HTTPException(403, "Ungültiges Formular-Token. Bitte Seite neu laden.")


async def read_form(request: Request):
    form = await request.form()
    check_csrf(request, form.get("csrf", ""))
    return form


async def read_json(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > 4096:
        raise HTTPException(413, "Anfrage zu groß.")
    try:
        data = json.loads(raw or b"{}")
    except ValueError as exc:
        raise HTTPException(400, "Kein gültiges JSON.") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, "Kein gültiges JSON.")
    return data


def flash(request: Request, text: str, kind: str = "ok"):
    request.session["flash"] = [kind, text]


def page(request: Request, name: str, user: m.User | None = None, **ctx):
    ctx.update(user=user, csrf=csrf_token(request), flash=request.session.pop("flash", None))
    return templates.TemplateResponse(request, name, ctx)


def go(url: str):
    return RedirectResponse(url, status_code=303)


def need(obj):
    if obj is None:
        raise HTTPException(404, "Nicht gefunden")
    return obj


def text(form, key: str, limit: int = 300) -> str:
    return str(form.get(key, "")).strip()[:limit]


def zahl(value, low: int, high: int, default: int = 0) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


# ---------- Zustand der Anlage ----------

def laden(objekt: m.Objekt) -> dict:
    return json.loads(objekt.state) if objekt.state else sim.neu()


def aendern(db: Session, objekt: m.Objekt, fn=None) -> dict:
    """Lädt den Zustand, führt fällige Auslösungen und ``fn(st, log, now)`` aus und speichert, falls sich etwas tat."""
    with _state_lock:
        db.refresh(objekt)
        st = laden(objekt)
        vorher, eintraege, now = st["v"], [], m.utcnow()
        sim.tick(st, eintraege, now)
        if fn:
            fn(st, eintraege, now)
        if eintraege and st["v"] == vorher:
            st["v"] += 1  # auch ein reiner Protokolleintrag soll bei den Anzeigen ankommen
        if st["v"] != vorher or not objekt.state:
            objekt.state = json.dumps(st, ensure_ascii=False)
            for quelle, zeile in eintraege:
                db.add(m.Protokoll(objekt_id=objekt.id, ts=now, quelle=quelle[:40], text=zeile))
            db.commit()
    return st


def zustand(db: Session, objekt: m.Objekt) -> dict:
    st = laden(objekt)
    if not objekt.state or (st["geplant"] and min(p["faellig"] for p in st["geplant"]) <= sim.iso(m.utcnow())):
        st = aendern(db, objekt)
    return st


def oeffentlich(st: dict) -> dict:
    """Was die Anzeigen der Übenden erfahren: nichts Vorgemerktes und nicht, ob eine Ursache noch ansteht."""
    sichtbar = {k: v for k, v in st.items() if k != "geplant"}
    sichtbar["meldungen"] = [{k: v for k, v in mm.items() if k != "ansteht"} for mm in st["meldungen"]]
    return {"st": sichtbar, "sicht": {k: v for k, v in sim.sicht(st).items() if k != "normal"}}


def protokoll_zeilen(db: Session, objekt_id: int, limit: int = 60) -> list[dict]:
    rows = db.scalars(select(m.Protokoll).where(m.Protokoll.objekt_id == objekt_id)
                      .order_by(m.Protokoll.id.desc()).limit(limit)).all()
    return [{"zeit": sim.iso(r.ts), "quelle": r.quelle, "text": r.text} for r in rows]


def protokoll_kuerzen(db: Session, objekt_id: int):
    grenze = db.scalar(select(m.Protokoll.id).where(m.Protokoll.objekt_id == objekt_id)
                       .order_by(m.Protokoll.id.desc()).offset(LOG_KEEP).limit(1))
    if grenze:
        db.execute(delete(m.Protokoll).where(m.Protokoll.objekt_id == objekt_id, m.Protokoll.id <= grenze))
        db.commit()


def ziel_von(melder: m.Melder) -> dict:
    g = melder.gruppe
    return {"gruppe": g.nummer, "melder": melder.nummer, "typ": melder.typ, "ort": melder.ort, "gname": g.name, "etage": g.etage}


def ausbreitung_folge(melder: m.Melder, anzahl: int = 4) -> list[m.Melder]:
    """Welche Melder bei einer Brandausbreitung als Nächste ansprechen: erst die eigene Gruppe, dann dieselbe Etage."""
    g = melder.gruppe
    automatisch = lambda x: x.typ not in ("hfm", "spr")  # noqa: E731
    eigene = sorted((x for x in g.melder if x.id != melder.id and automatisch(x)), key=lambda x: abs(x.nummer - melder.nummer))
    nachbarn = [x for og in sorted(g.objekt.gruppen, key=lambda og: abs(og.nummer - g.nummer))
                if og.id != g.id and og.etage == g.etage for x in og.melder if automatisch(x)]
    return (eigene + nachbarn)[:anzahl]


# ---------- Anmeldung ----------

_failed: dict[str, list[float]] = {}


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": VERSION}


@app.get("/login")
def login_form(request: Request):
    return page(request, "login.html")


@app.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await read_form(request)
    username = text(form, "username", 80)
    recent = [t for t in _failed.get(username.lower(), []) if time.time() - t < 300]
    if len(recent) >= 5:
        flash(request, "Zu viele Fehlversuche. Bitte fünf Minuten warten.", "err")
        return go("/login")
    user = db.scalar(select(m.User).where(func.lower(m.User.username) == username.lower()))
    if not user or not sec.verify_password(str(form.get("password", "")), user.password_hash):
        _failed[username.lower()] = recent + [time.time()]
        log.warning("Fehlgeschlagene Anmeldung für %r", username)
        flash(request, "Benutzername oder Passwort falsch.", "err")
        return go("/login")
    _failed.pop(username.lower(), None)
    request.session.clear()
    request.session["uid"] = user.id
    user.last_login = m.utcnow()
    db.commit()
    return go("/")


@app.post("/logout")
async def logout(request: Request):
    await read_form(request)
    request.session.clear()
    return go("/login")


# ---------- Objekte ----------

@app.get("/")
def home(request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    objekte = db.scalars(select(m.Objekt).order_by(m.Objekt.name)).all()
    karten = []
    for o in objekte:
        st = laden(o)
        karten.append({"o": o, "sicht": sim.sicht(st), "melder": sum(len(g.melder) for g in o.gruppen),
                       "etagen": len(katalog.etagen(o))})
    return page(request, "home.html", user, karten=karten)


@app.get("/objekte/neu")
def objekt_neu(request: Request, user: m.User = Depends(current_user)):
    return page(request, "objekt_form.html", user, o=None)


@app.get("/objekte/{oid}/bearbeiten")
def objekt_bearbeiten(oid: int, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return page(request, "objekt_form.html", user, o=need(db.get(m.Objekt, oid)))


@app.post("/objekte/speichern")
async def objekt_speichern(request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    form = await read_form(request)
    name = text(form, "name", 120)
    oid = text(form, "id", 12)
    if not name:
        flash(request, "Bitte einen Namen eintragen.", "err")
        return go(f"/objekte/{oid}/bearbeiten" if oid else "/objekte/neu")
    o = need(db.get(m.Objekt, int(oid))) if oid.isdigit() else m.Objekt()
    o.name, o.adresse, o.bma_nr = name, text(form, "adresse", 200), text(form, "bma_nr", 40)
    o.hinweis, o.loeschanlage = text(form, "hinweis", 2000), form.get("loeschanlage") == "on"
    db.add(o)
    db.commit()
    flash(request, "Objekt gespeichert.")
    return go(f"/objekte/{o.id}/melder" if not oid else f"/objekte/{o.id}")


@app.post("/objekte/{oid}/loeschen")
async def objekt_loeschen(oid: int, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    await read_form(request)
    o = need(db.get(m.Objekt, oid))
    db.delete(o)
    db.commit()
    flash(request, f"„{o.name}“ gelöscht.")
    return go("/")


@app.post("/objekte/{oid}/kopieren")
async def objekt_kopieren(oid: int, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    await read_form(request)
    o = need(db.get(m.Objekt, oid))
    neu = m.Objekt(name=(o.name + " (Kopie)")[:120], adresse=o.adresse, bma_nr=o.bma_nr, hinweis=o.hinweis, loeschanlage=o.loeschanlage)
    for g in o.gruppen:
        neu.gruppen.append(m.Gruppe(nummer=g.nummer, name=g.name, etage=g.etage,
                                    melder=[m.Melder(nummer=x.nummer, typ=x.typ, ort=x.ort) for x in g.melder]))
    db.add(neu)
    db.commit()
    flash(request, "Objekt kopiert.")
    return go(f"/objekte/{neu.id}/bearbeiten")


@app.post("/objekte/{oid}/link-erneuern")
async def link_erneuern(oid: int, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    await read_form(request)
    o = need(db.get(m.Objekt, oid))
    o.token = m.new_token()
    db.commit()
    flash(request, "Neue Adresse für die Anzeigen vergeben. Die alte gilt nicht mehr.")
    return go(f"/objekte/{oid}")


@app.get("/objekte/{oid}/qr.svg")
def qr(oid: int, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    o = need(db.get(m.Objekt, oid))
    out = io.BytesIO()
    segno.make(f"{str(request.base_url).rstrip('/')}/a/{o.token}", error="m").save(out, kind="svg", scale=4, border=2)
    return Response(out.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


# ---------- Melderliste ----------

@app.get("/objekte/{oid}/melder")
def melderliste(oid: int, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    o = need(db.get(m.Objekt, oid))
    return page(request, "melder.html", user, o=o, etagen=katalog.etagen(o), kopf=";".join(katalog.KOPF))


@app.post("/objekte/{oid}/melder/hinzufuegen")
async def melder_hinzufuegen(oid: int, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    form = await read_form(request)
    o = need(db.get(m.Objekt, oid))
    zeile = ";".join(text(form, k, 80).replace(";", ",") for k in ("gruppe", "melder", "typ", "etage", "gname", "ort"))
    zeilen, fehler = katalog.lesen(zeile)
    if fehler:
        flash(request, fehler[0].replace("Zeile 1: ", ""), "err")
    else:
        katalog.uebernehmen(db, o, zeilen, ersetzen=False)
        db.commit()
        flash(request, f"Melder {sim.nr(zeilen[0]['gruppe'], zeilen[0]['melder'])} gespeichert.")
    return go(f"/objekte/{oid}/melder")


@app.post("/objekte/{oid}/melder/import")
async def melder_import(oid: int, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    form = await read_form(request)
    o = need(db.get(m.Objekt, oid))
    inhalt = str(form.get("liste", ""))
    datei = form.get("datei")
    if datei is not None and getattr(datei, "filename", ""):
        raw = await datei.read(MAX_UPLOAD + 1)
        if len(raw) > MAX_UPLOAD:
            flash(request, "Die Datei ist zu groß (höchstens 512 KB).", "err")
            return go(f"/objekte/{oid}/melder")
        try:
            inhalt = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            inhalt = raw.decode("cp1252", errors="replace")  # CSV aus Excel unter Windows
    zeilen, fehler = katalog.lesen(inhalt)
    if fehler:
        flash(request, "Nichts übernommen. " + " ".join(fehler[:5]), "err")
    else:
        anzahl = katalog.uebernehmen(db, o, zeilen, ersetzen=form.get("ersetzen") == "on")
        db.commit()
        flash(request, f"{anzahl} Melder übernommen.")
    return go(f"/objekte/{oid}/melder")


@app.get("/objekte/{oid}/melder.csv")
def melder_export(oid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    o = need(db.get(m.Objekt, oid))
    return Response(katalog.schreiben(o), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="melderliste-{o.id}.csv"'})


@app.post("/melder/{mid}/loeschen")
async def melder_loeschen(mid: int, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    await read_form(request)
    x = need(db.get(m.Melder, mid))
    g = x.gruppe
    oid = g.objekt_id
    g.melder.remove(x)
    if not g.melder:
        db.delete(g)
    db.commit()
    return go(f"/objekte/{oid}/melder")


@app.post("/gruppen/{gid}/loeschen")
async def gruppe_loeschen(gid: int, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    await read_form(request)
    g = need(db.get(m.Gruppe, gid))
    oid = g.objekt_id
    db.delete(g)
    db.commit()
    flash(request, f"Gruppe {sim.nr(g.nummer)} gelöscht.")
    return go(f"/objekte/{oid}/melder")


# ---------- Ausbilderansicht ----------

@app.get("/objekte/{oid}")
def leitstand(oid: int, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    o = need(db.get(m.Objekt, oid))
    link = f"{str(request.base_url).rstrip('/')}/a/{o.token}"
    return page(request, "leitstand.html", user, o=o, etagen=katalog.etagen(o), link=link)


def ausbilder_antwort(db: Session, o: m.Objekt, st: dict) -> dict:
    return {"st": st, "sicht": sim.sicht(st), "protokoll": protokoll_zeilen(db, o.id)}


@app.get("/objekte/{oid}/state")
def leitstand_state(oid: int, v: int = 0, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    o = need(db.get(m.Objekt, oid))
    st = zustand(db, o)
    if v == st["v"]:
        return Response(status_code=204)
    return ausbilder_antwort(db, o, st)


@app.post("/objekte/{oid}/aktion")
async def leitstand_aktion(oid: int, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    check_csrf(request, request.headers.get("x-csrf", ""))
    data = await read_json(request)
    o = need(db.get(m.Objekt, oid))
    aktion = str(data.get("aktion", ""))
    wer = f"Ausbilder {user.username}"

    def melder_von(key="melder_id") -> m.Melder:
        x = db.get(m.Melder, zahl(data.get(key), 1, 2**31, 0))
        if x is None or x.gruppe.objekt_id != o.id:
            raise HTTPException(404, "Melder nicht gefunden")
        return x

    def gruppe_von() -> m.Gruppe:
        g = db.get(m.Gruppe, zahl(data.get("gruppe_id"), 1, 2**31, 0))
        if g is None or g.objekt_id != o.id:
            raise HTTPException(404, "Gruppe nicht gefunden")
        return g

    if aktion == "alarm":
        x = melder_von()
        sekunden, abstand = zahl(data.get("sekunden"), 0, 3600), zahl(data.get("ausbreitung"), 0, 600)
        ansteht = bool(data.get("ansteht"))
        folge = ausbreitung_folge(x) if abstand else []

        def fn(st, eintraege, now):
            if sekunden:
                sim.planen(st, ziel_von(x), now, sekunden, ansteht)
                eintraege.append((wer, f"Alarm {sim.nr(x.gruppe.nummer, x.nummer)} in {sekunden} s vorgemerkt"))
            else:
                sim.alarm(st, ziel_von(x), eintraege, now, wer, ansteht)
            brennt = {(a["gruppe"], a["melder"]) for a in sim.alarme(st)}
            weitere = [n for n in folge if (n.gruppe.nummer, n.nummer) not in brennt]
            for i, nachbar in enumerate(weitere, start=1):
                sim.planen(st, ziel_von(nachbar), now, sekunden + i * abstand, ansteht)
            if weitere:
                eintraege.append((wer, f"Ausbreitung vorgemerkt: {len(weitere)} weitere Melder im Abstand von {abstand} s"))
    elif aktion == "stoerung":
        meldung = str(data.get("text", "")).strip()[:60] or "Störung"
        x = melder_von() if data.get("melder_id") else None

        def fn(st, eintraege, now):
            if x:
                sim.stoerung(st, meldung, eintraege, now, gruppe=x.gruppe.nummer, melder=x.nummer, quelle=wer,
                             ort=x.ort, gname=x.gruppe.name, etage=x.gruppe.etage)
            else:
                sim.stoerung(st, meldung, eintraege, now, quelle=wer)
    elif aktion == "abschaltung":
        x = melder_von() if data.get("melder_id") else None
        g = x.gruppe if x else gruppe_von()

        def fn(st, eintraege, now):
            sim.abschaltung(st, g.nummer, eintraege, now, melder=x.nummer if x else None, gname=g.name,
                            ort=x.ort if x else g.name, quelle=wer)
    elif aktion == "entfernen":
        fn = lambda st, eintraege, now: sim.entfernen(st, zahl(data.get("id"), 0, 2**31), eintraege, wer)  # noqa: E731
    elif aktion == "ursache":
        fn = lambda st, eintraege, now: sim.ursache(st, zahl(data.get("id"), 0, 2**31), bool(data.get("ansteht")), eintraege, wer)  # noqa: E731
    elif aktion == "loeschanlage":
        fn = lambda st, eintraege, now: sim.loeschanlage(st, bool(data.get("an")), eintraege, wer)  # noqa: E731
    elif aktion == "schalter":
        fn = lambda st, eintraege, now: sim.schalter(st, str(data.get("name", "")), eintraege, wer)  # noqa: E731
    elif aktion == "ue_pruefen":
        fn = lambda st, eintraege, now: sim.ue_pruefen(st, eintraege, wer)  # noqa: E731
    elif aktion == "ruecksetzen":
        fn = lambda st, eintraege, now: sim.ruecksetzen(st, eintraege, now, wer)  # noqa: E731
    elif aktion == "vormerkungen_loeschen":
        def fn(st, eintraege, now):
            if st["geplant"]:
                st["geplant"] = []
                st["v"] += 1
                eintraege.append((wer, "Vorgemerkte Auslösungen verworfen"))
    elif aktion == "grundstellung":
        fn = lambda st, eintraege, now: sim.grundstellung(st, eintraege, wer)  # noqa: E731
    else:
        raise HTTPException(400, "Unbekannte Aktion")
    st = aendern(db, o, fn)
    protokoll_kuerzen(db, o.id)
    return ausbilder_antwort(db, o, st)


@app.get("/objekte/{oid}/protokoll.csv")
def protokoll_export(oid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    o = need(db.get(m.Objekt, oid))
    rows = db.scalars(select(m.Protokoll).where(m.Protokoll.objekt_id == o.id).order_by(m.Protokoll.id)).all()
    aus = io.StringIO()
    w = csv.writer(aus, delimiter=";", lineterminator="\r\n")
    w.writerow(["Zeit", "Quelle", "Ereignis"])
    for r in rows:
        w.writerow([r.ts.replace(tzinfo=dt.timezone.utc).astimezone(TZ).strftime("%d.%m.%Y %H:%M:%S"), r.quelle, r.text])
    return Response("﻿" + aus.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="uebungsprotokoll-{o.id}.csv"'})


@app.post("/objekte/{oid}/protokoll/leeren")
async def protokoll_leeren(oid: int, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    await read_form(request)
    o = need(db.get(m.Objekt, oid))
    db.execute(delete(m.Protokoll).where(m.Protokoll.objekt_id == o.id))
    db.commit()
    aendern(db, o, lambda st, eintraege, now: eintraege.append((f"Ausbilder {user.username}", "Protokoll geleert")))
    return go(f"/objekte/{oid}")


# ---------- Anzeigen für die Übenden (ohne Anmeldung, über die geheime Adresse) ----------

def objekt_zu(db: Session, token: str) -> m.Objekt:
    return need(db.scalar(select(m.Objekt).where(m.Objekt.token == token)) if 8 <= len(token) <= 40 else None)


def anzeige(request: Request, name: str, o: m.Objekt, **ctx):
    response = templates.TemplateResponse(request, name, {"o": o, "user": None, "flash": None, "csrf": "", **ctx})
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex"
    return response


@app.get("/a/{token}")
def anzeige_wahl(token: str, request: Request, db: Session = Depends(get_db)):
    return anzeige(request, "anzeige_wahl.html", objekt_zu(db, token))


@app.get("/a/{token}/fat")
def anzeige_fat(token: str, request: Request, db: Session = Depends(get_db)):
    return anzeige(request, "fat.html", objekt_zu(db, token))


@app.get("/a/{token}/bmz")
def anzeige_bmz(token: str, request: Request, db: Session = Depends(get_db)):
    return anzeige(request, "bmz.html", objekt_zu(db, token))


@app.get("/a/{token}/verzeichnis")
def anzeige_verzeichnis(token: str, request: Request, db: Session = Depends(get_db)):
    o = objekt_zu(db, token)
    return anzeige(request, "verzeichnis.html", o, etagen=katalog.etagen(o))


@app.get("/a/{token}/state")
def anzeige_state(token: str, v: int = 0, db: Session = Depends(get_db)):
    st = zustand(db, objekt_zu(db, token))
    if v == st["v"]:
        return Response(status_code=204)
    return JSONResponse(oeffentlich(st), headers={"Cache-Control": "no-store"})


GERAETE = {"fbf": ("akustik_ab", "bfs_ab", "ue_ab", "ue_pruefen", "ruecksetzen"), "fat": ("summer_ab",),
           "bmz": ("summer_ab", "ruecksetzen")}


@app.post("/a/{token}/aktion")
async def anzeige_aktion(token: str, request: Request, db: Session = Depends(get_db)):
    o = objekt_zu(db, token)
    data = await read_json(request)
    geraet, aktion = str(data.get("geraet", "")), str(data.get("aktion", ""))
    if aktion not in GERAETE.get(geraet, ()):
        raise HTTPException(400, "Unbekannte Aktion")
    wer = geraet.upper()

    def fn(st, eintraege, now):
        if aktion == "summer_ab":
            sim.summer_ab(st, geraet, eintraege)
        elif aktion == "ruecksetzen":
            sim.ruecksetzen(st, eintraege, now, wer)
        elif aktion == "ue_pruefen":
            sim.ue_pruefen(st, eintraege, wer)
        else:
            sim.schalter(st, aktion, eintraege, wer)
    return JSONResponse(oeffentlich(aendern(db, o, fn)), headers={"Cache-Control": "no-store"})


# ---------- Benutzer ----------

@app.get("/benutzer")
def benutzer(request: Request, user: m.User = Depends(admin_user), db: Session = Depends(get_db)):
    return page(request, "benutzer.html", user, liste=db.scalars(select(m.User).order_by(m.User.username)).all())


@app.post("/benutzer/speichern")
async def benutzer_speichern(request: Request, user: m.User = Depends(admin_user), db: Session = Depends(get_db)):
    form = await read_form(request)
    name, password = text(form, "username", 80), str(form.get("password", ""))
    if not name or len(password) < 12:
        flash(request, "Bitte Benutzername und ein Passwort mit mindestens 12 Zeichen angeben.", "err")
    elif db.scalar(select(m.User).where(func.lower(m.User.username) == name.lower())):
        flash(request, "Diesen Benutzernamen gibt es schon.", "err")
    else:
        db.add(m.User(username=name, password_hash=sec.hash_password(password), is_admin=form.get("is_admin") == "on"))
        db.commit()
        flash(request, f"Benutzer „{name}“ angelegt.")
    return go("/benutzer")


@app.post("/benutzer/{uid}/passwort")
async def benutzer_passwort(uid: int, request: Request, user: m.User = Depends(admin_user), db: Session = Depends(get_db)):
    form = await read_form(request)
    ziel = need(db.get(m.User, uid))
    password = str(form.get("password", ""))
    if len(password) < 12:
        flash(request, "Das Passwort braucht mindestens 12 Zeichen.", "err")
    else:
        ziel.password_hash = sec.hash_password(password)
        db.commit()
        flash(request, f"Passwort für „{ziel.username}“ gesetzt.")
    return go("/benutzer")


@app.post("/benutzer/{uid}/loeschen")
async def benutzer_loeschen(uid: int, request: Request, user: m.User = Depends(admin_user), db: Session = Depends(get_db)):
    await read_form(request)
    ziel = need(db.get(m.User, uid))
    if ziel.id == user.id:
        flash(request, "Das eigene Konto lässt sich nicht löschen.", "err")
    else:
        db.delete(ziel)
        db.commit()
        flash(request, f"Benutzer „{ziel.username}“ gelöscht.")
    return go("/benutzer")


@app.get("/konto")
def konto(request: Request, user: m.User = Depends(current_user)):
    return page(request, "konto.html", user)


@app.post("/konto")
async def konto_speichern(request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    form = await read_form(request)
    neu = str(form.get("neu", ""))
    if not sec.verify_password(str(form.get("alt", "")), user.password_hash):
        flash(request, "Das bisherige Passwort stimmt nicht.", "err")
    elif len(neu) < 12 or neu != str(form.get("neu2", "")):
        flash(request, "Das neue Passwort braucht mindestens 12 Zeichen und muss zweimal gleich eingegeben werden.", "err")
    else:
        user.password_hash = sec.hash_password(neu)
        db.commit()
        flash(request, "Passwort geändert.")
    return go("/konto")


@app.get("/hilfe")
def hilfe(request: Request, user: m.User = Depends(current_user)):
    return page(request, "hilfe.html", user)
