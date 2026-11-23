"""Web-Oberfläche: Ausbilderansicht, Verwaltung der Objekte und die Anzeigen für die Übenden."""
import asyncio
import csv
import datetime as dt
import hashlib
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
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import db as m
from . import access, backup, katalog, laufkarte, live, sim, szenario
from . import security as sec
from .version import VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bma")

BASE = os.path.dirname(__file__)
TZ = ZoneInfo(os.environ.get("TZ", "Europe/Berlin"))
LOG_KEEP = int(os.environ.get("LOG_KEEP", "2000"))  # Protokollzeilen je Objekt
MAX_UPLOAD = 512 * 1024
INVITE_HOURS = 48
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
                          is_admin=True, perms=json.dumps(access.PRESETS["admin"])))
            db.commit()
            log.info("Erster Benutzer wurde angelegt.")
            if os.environ.get("BEISPIELE", "true").lower() == "true":
                log.info("%s Beispielobjekte angelegt.", katalog.beispiele_anlegen(db))
                for objekt in db.scalars(select(m.Objekt)).all():
                    laufkarte.schema_erzeugen(db, objekt)
                db.commit()
        anzahl = katalog.beispielszenarien_nachtragen(db)
        if anzahl:
            log.info("%s Beispielszenarien für die Beispielobjekte nachgetragen.", anzahl)
    log.info("BMA Simulator %s gestartet.", VERSION)
    task = asyncio.create_task(sicherung_schleife())
    yield
    task.cancel()


async def sicherung_schleife():
    """Tägliche Sicherung ohne Zutun (Abstand über BACKUP_HOURS, 0 = aus)."""
    await asyncio.sleep(60)
    while True:
        try:
            if await asyncio.to_thread(backup.auto_due):
                log.info("Automatische Sicherung abgelegt: %s", await asyncio.to_thread(backup.store, True))
        except Exception:
            log.exception("Automatische Sicherung fehlgeschlagen")
        await asyncio.sleep(600)


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
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
    return response


class LoginRequired(Exception):
    pass


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, _exc):
    if request.url.path.endswith(("/state", "/aktion")):
        return JSONResponse({"detail": "Nicht angemeldet."}, status_code=401)
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(access.Denied)
async def _denied(request: Request, exc: access.Denied):
    log.warning("Zugriff verweigert: %s %s", request.method, request.url.path)
    if request.url.path.endswith(("/state", "/aktion")):
        return JSONResponse({"detail": exc.message}, status_code=403)
    response = templates.TemplateResponse(request, "verboten.html", {"message": exc.message, "user": None, "flash": None, "csrf": "", "perm": {}})
    response.status_code = 403
    return response


def get_db():
    with m.SessionLocal() as db:
        yield db


def current_user(request: Request, db: Session = Depends(get_db)) -> m.User:
    uid = request.session.get("uid")
    user = db.get(m.User, uid) if uid else None
    if not user:
        raise LoginRequired()
    now = m.utcnow()
    if user.last_seen is None or (now - user.last_seen).total_seconds() > 60:  # höchstens einmal je Minute schreiben
        user.last_seen = now
        db.commit()
    return user


def allow(*needs: str):
    """Abhängigkeit für Seiten und Aktionen: angemeldet und mit den genannten Rechten, z. B. allow("uebung:2")."""
    def dependency(request: Request, db: Session = Depends(get_db)) -> m.User:
        user = current_user(request, db)
        access.require(user, *needs)
        return user
    return dependency


def objekt_for(db: Session, user: m.User, objekt_id) -> m.Objekt:
    """Lädt ein Objekt nur, wenn der Benutzer es sehen darf. Fremde Objekte verhalten sich wie nicht vorhanden."""
    objekt = db.get(m.Objekt, int(objekt_id))
    if objekt is None or not access.allowed(user, objekt.id):
        raise HTTPException(404, "Nicht gefunden")
    return objekt


def freigeben(user: m.User, objekt: m.Objekt):
    """Wer nur einzelne Objekte sieht, bekommt ein selbst angelegtes dazu."""
    if not access.sees_all(user):
        user.objekt_ids = ",".join(str(i) for i in sorted(access.objekt_ids(user) | {objekt.id}))


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
    ctx.update(user=user, csrf=csrf_token(request), flash=request.session.pop("flash", None),
               perm=access.perms_of(user) if user else {})
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
    return sim.ergaenzen(json.loads(objekt.state)) if objekt.state else sim.neu()


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
    if not user or not user.password_hash or not sec.verify_password(str(form.get("password", "")), user.password_hash):
        _failed[username.lower()] = recent + [time.time()]
        log.warning("Fehlgeschlagene Anmeldung für %r", username)
        flash(request, "Benutzername oder Passwort falsch.", "err")
        return go("/login")
    _failed.pop(username.lower(), None)
    request.session.clear()
    request.session["uid"] = user.id
    user.last_login = user.last_seen = m.utcnow()
    db.commit()
    return go("/")


@app.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    await read_form(request)
    user = db.get(m.User, request.session.get("uid") or 0)
    if user:
        user.last_seen = None
        db.commit()
    request.session.clear()
    return go("/login")


# ---------- Objekte ----------

@app.get("/")
def home(request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    objekte = [o for o in db.scalars(select(m.Objekt).order_by(m.Objekt.name)).all() if access.allowed(user, o.id)]
    karten = []
    for o in objekte:
        st = laden(o)
        karten.append({"o": o, "sicht": sim.sicht(st), "melder": sum(len(g.melder) for g in o.gruppen),
                       "etagen": len(katalog.etagen(o))})
    return page(request, "home.html", user, karten=karten)


@app.get("/objekte/neu")
def objekt_neu(request: Request, user: m.User = Depends(allow("objekte:2"))):
    return page(request, "objekt_form.html", user, o=None)


@app.get("/objekte/{oid}/bearbeiten")
def objekt_bearbeiten(oid: int, request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    return page(request, "objekt_form.html", user, o=objekt_for(db, user, oid))


@app.post("/objekte/speichern")
async def objekt_speichern(request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    form = await read_form(request)
    name = text(form, "name", 120)
    oid = text(form, "id", 12)
    if not name:
        flash(request, "Bitte einen Namen eintragen.", "err")
        return go(f"/objekte/{oid}/bearbeiten" if oid else "/objekte/neu")
    o = objekt_for(db, user, oid) if oid.isdigit() else m.Objekt()
    o.name, o.adresse, o.bma_nr = name, text(form, "adresse", 200), text(form, "bma_nr", 40)
    o.hinweis, o.loeschanlage = text(form, "hinweis", 2000), form.get("loeschanlage") == "on"
    db.add(o)
    db.flush()
    freigeben(user, o)
    db.commit()
    flash(request, "Objekt gespeichert.")
    return go(f"/objekte/{o.id}/melder" if not oid else f"/objekte/{o.id}")


@app.post("/objekte/{oid}/loeschen")
async def objekt_loeschen(oid: int, request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    await read_form(request)
    o = objekt_for(db, user, oid)
    db.delete(o)
    db.commit()
    flash(request, f"„{o.name}“ gelöscht.")
    return go("/")


@app.post("/objekte/{oid}/kopieren")
async def objekt_kopieren(oid: int, request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    await read_form(request)
    o = objekt_for(db, user, oid)
    neu = m.Objekt(name=(o.name + " (Kopie)")[:120], adresse=o.adresse, bma_nr=o.bma_nr, hinweis=o.hinweis, loeschanlage=o.loeschanlage,
                   fiz_etage=o.fiz_etage, fiz_x=o.fiz_x, fiz_y=o.fiz_y)
    for g in o.gruppen:
        neu.gruppen.append(m.Gruppe(nummer=g.nummer, name=g.name, etage=g.etage, laufweg=g.laufweg, hinweis=g.hinweis, weg1=g.weg1, weg2=g.weg2,
                                    melder=[m.Melder(nummer=x.nummer, typ=x.typ, ort=x.ort, px=x.px, py=x.py) for x in g.melder]))
    for plan in o.plaene:
        neu.plaene.append(m.Plan(etage=plan.etage, mime=plan.mime, daten=plan.daten, schema=plan.schema))
    for sz in o.szenarien:
        neu.szenarien.append(m.Szenario(name=sz.name, beschreibung=sz.beschreibung, schritte=sz.schritte))
    db.add(neu)
    db.flush()
    freigeben(user, neu)
    db.commit()
    flash(request, "Objekt kopiert.")
    return go(f"/objekte/{neu.id}/bearbeiten")


@app.post("/objekte/{oid}/link-erneuern")
async def link_erneuern(oid: int, request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    await read_form(request)
    o = objekt_for(db, user, oid)
    o.token = m.new_token()
    db.commit()
    live.vergessen(o.id)
    flash(request, "Neue Adresse für die Anzeigen vergeben. Die alte gilt nicht mehr.")
    return go(f"/objekte/{oid}")


@app.get("/objekte/{oid}/qr.svg")
def qr(oid: int, request: Request, user: m.User = Depends(allow("uebung:1")), db: Session = Depends(get_db)):
    o = objekt_for(db, user, oid)
    out = io.BytesIO()
    segno.make(f"{str(request.base_url).rstrip('/')}/a/{o.token}", error="m").save(out, kind="svg", scale=4, border=2)
    return Response(out.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


# ---------- Melderliste ----------

@app.get("/objekte/{oid}/melder")
def melderliste(oid: int, request: Request, user: m.User = Depends(allow("objekte:1")), db: Session = Depends(get_db)):
    o = objekt_for(db, user, oid)
    return page(request, "melder.html", user, o=o, etagen=katalog.etagen(o), kopf=";".join(katalog.KOPF))


@app.post("/objekte/{oid}/melder/hinzufuegen")
async def melder_hinzufuegen(oid: int, request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    form = await read_form(request)
    o = objekt_for(db, user, oid)
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
async def melder_import(oid: int, request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    form = await read_form(request)
    o = objekt_for(db, user, oid)
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
def melder_export(oid: int, user: m.User = Depends(allow("objekte:1")), db: Session = Depends(get_db)):
    o = objekt_for(db, user, oid)
    return Response(katalog.schreiben(o), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="melderliste-{o.id}.csv"'})


@app.post("/melder/{mid}/loeschen")
async def melder_loeschen(mid: int, request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    await read_form(request)
    x = need(db.get(m.Melder, mid))
    g = x.gruppe
    oid = g.objekt_id
    objekt_for(db, user, oid)
    g.melder.remove(x)
    if not g.melder:
        db.delete(g)
    db.commit()
    return go(f"/objekte/{oid}/melder")


@app.post("/gruppen/{gid}/loeschen")
async def gruppe_loeschen(gid: int, request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    await read_form(request)
    g = need(db.get(m.Gruppe, gid))
    oid = g.objekt_id
    objekt_for(db, user, oid)
    db.delete(g)
    db.commit()
    flash(request, f"Gruppe {sim.nr(g.nummer)} gelöscht.")
    return go(f"/objekte/{oid}/melder")


# ---------- Ausbilderansicht ----------

@app.get("/objekte/{oid}")
def leitstand(oid: int, request: Request, user: m.User = Depends(allow("uebung:1")), db: Session = Depends(get_db)):
    o = objekt_for(db, user, oid)
    link = f"{str(request.base_url).rstrip('/')}/a/{o.token}"
    return page(request, "leitstand.html", user, o=o, etagen=katalog.etagen(o), link=link)


def ausbilder_antwort(db: Session, o: m.Objekt, st: dict, user: m.User) -> dict:
    geraete = live.liste(o.id)
    antwort = {"st": st, "sicht": sim.sicht(st), "live": geraete, "pv": live.signatur(geraete)}
    if access.perms_of(user)["protokoll"]:
        antwort["protokoll"] = protokoll_zeilen(db, o.id)
    return antwort


@app.get("/objekte/{oid}/state")
def leitstand_state(oid: int, v: int = 0, pv: str = "", user: m.User = Depends(allow("uebung:1")), db: Session = Depends(get_db)):
    o = objekt_for(db, user, oid)
    st = zustand(db, o)
    if v == st["v"] and pv == live.signatur(live.liste(o.id)):
        return Response(status_code=204)
    return ausbilder_antwort(db, o, st, user)


@app.post("/objekte/{oid}/aktion")
async def leitstand_aktion(oid: int, request: Request, user: m.User = Depends(allow("uebung:2")), db: Session = Depends(get_db)):
    check_csrf(request, request.headers.get("x-csrf", ""))
    data = await read_json(request)
    o = objekt_for(db, user, oid)
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
    elif aktion == "szenario":
        sz = db.get(m.Szenario, zahl(data.get("id"), 1, 2**31, 0))
        if sz is None or sz.objekt_id != o.id:
            raise HTTPException(404, "Szenario nicht gefunden")
        fn = lambda st, eintraege, now: szenario.starten(st, o, sz, eintraege, now, wer)  # noqa: E731
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
    return ausbilder_antwort(db, o, st, user)


@app.get("/objekte/{oid}/protokoll.csv")
def protokoll_export(oid: int, user: m.User = Depends(allow("protokoll:1")), db: Session = Depends(get_db)):
    o = objekt_for(db, user, oid)
    rows = db.scalars(select(m.Protokoll).where(m.Protokoll.objekt_id == o.id).order_by(m.Protokoll.id)).all()
    aus = io.StringIO()
    w = csv.writer(aus, delimiter=";", lineterminator="\r\n")
    w.writerow(["Zeit", "Quelle", "Ereignis"])
    for r in rows:
        w.writerow([r.ts.replace(tzinfo=dt.timezone.utc).astimezone(TZ).strftime("%d.%m.%Y %H:%M:%S"), r.quelle, r.text])
    return Response("﻿" + aus.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="uebungsprotokoll-{o.id}.csv"'})


@app.post("/objekte/{oid}/protokoll/leeren")
async def protokoll_leeren(oid: int, request: Request, user: m.User = Depends(allow("protokoll:2")), db: Session = Depends(get_db)):
    await read_form(request)
    o = objekt_for(db, user, oid)
    db.execute(delete(m.Protokoll).where(m.Protokoll.objekt_id == o.id))
    db.commit()
    aendern(db, o, lambda st, eintraege, now: eintraege.append((f"Ausbilder {user.username}", "Protokoll geleert")))
    return go(f"/objekte/{oid}")


# ---------- Szenarien ----------

def szenario_for(db: Session, user: m.User, sid: int) -> m.Szenario:
    sz = need(db.get(m.Szenario, sid))
    objekt_for(db, user, sz.objekt_id)
    return sz


@app.get("/objekte/{oid}/szenarien")
def szenarien(oid: int, request: Request, user: m.User = Depends(allow("uebung:1")), db: Session = Depends(get_db)):
    o = objekt_for(db, user, oid)
    liste = [{"sz": sz, "schritte": [(s.get("sek", 0), szenario.beschreiben(o, s)) for s in szenario.schritte(sz)]} for sz in o.szenarien]
    return page(request, "szenarien.html", user, o=o, liste=liste)


def szenario_formular(request: Request, user: m.User, o: m.Objekt, sz: m.Szenario | None):
    zeilen = szenario.schritte(sz) if sz else [{"sek": 0, "aktion": "alarm", "g": 0, "m": 0, "text": "", "ansteht": False}]
    return page(request, "szenario_form.html", user, o=o, sz=sz, zeilen=zeilen, aktionen=sim.AKTIONEN)


@app.get("/objekte/{oid}/szenarien/neu")
def szenario_neu(oid: int, request: Request, user: m.User = Depends(allow("uebung:2")), db: Session = Depends(get_db)):
    return szenario_formular(request, user, objekt_for(db, user, oid), None)


@app.get("/szenarien/{sid}/bearbeiten")
def szenario_bearbeiten(sid: int, request: Request, user: m.User = Depends(allow("uebung:2")), db: Session = Depends(get_db)):
    sz = szenario_for(db, user, sid)
    return szenario_formular(request, user, sz.objekt, sz)


@app.post("/objekte/{oid}/szenarien/speichern")
async def szenario_speichern(oid: int, request: Request, user: m.User = Depends(allow("uebung:2")), db: Session = Depends(get_db)):
    form = await read_form(request)
    o = objekt_for(db, user, oid)
    sid = text(form, "id", 12)
    sz = szenario_for(db, user, int(sid)) if sid.isdigit() else None
    if sz is not None and sz.objekt_id != o.id:
        raise HTTPException(404, "Nicht gefunden")
    name = text(form, "name", 120)
    schritte, fehler = szenario.aus_formular(o, form)
    if not name:
        fehler.insert(0, "Bitte einen Namen eintragen.")
    if not schritte and not fehler:
        fehler.append("Bitte mindestens einen Schritt anlegen.")
    if fehler:
        flash(request, "Nicht gespeichert. " + " ".join(fehler[:5]), "err")
        return go(f"/szenarien/{sz.id}/bearbeiten" if sz else f"/objekte/{oid}/szenarien/neu")
    if sz is None:
        sz = m.Szenario(name=name)
        o.szenarien.append(sz)
    sz.name, sz.beschreibung, sz.schritte = name, text(form, "beschreibung", 1000), json.dumps(schritte)
    db.commit()
    flash(request, f"Szenario „{name}“ mit {len(schritte)} Schritten gespeichert.")
    return go(f"/objekte/{oid}/szenarien")


@app.post("/szenarien/{sid}/loeschen")
async def szenario_loeschen(sid: int, request: Request, user: m.User = Depends(allow("uebung:2")), db: Session = Depends(get_db)):
    await read_form(request)
    sz = szenario_for(db, user, sid)
    oid = sz.objekt_id
    db.delete(sz)
    db.commit()
    flash(request, f"Szenario „{sz.name}“ gelöscht.")
    return go(f"/objekte/{oid}/szenarien")


# ---------- Laufkarten ----------

def plan_antwort(plan: m.Plan) -> Response:
    """Liefert ein Planbild. Hochgeladene SVG-Dateien dürfen nichts nachladen und nichts ausführen."""
    return Response(plan.daten, media_type=plan.mime, headers={
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox", "Cache-Control": "private, max-age=60",
        "Content-Disposition": "inline"})


@app.get("/objekte/{oid}/laufkarten")
def laufkarten(oid: int, request: Request, user: m.User = Depends(allow("objekte:1")), db: Session = Depends(get_db)):
    o = objekt_for(db, user, oid)
    return page(request, "laufkarten.html", user, o=o, etagen=katalog.etagen(o), stand=laufkarte.stand(o),
                fiz_etage=laufkarte.fiz_etage(o), plaene={pl.etage: pl for pl in o.plaene})


@app.post("/objekte/{oid}/laufkarten/fiz")
async def laufkarten_fiz(oid: int, request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    form = await read_form(request)
    o = objekt_for(db, user, oid)
    etage = text(form, "fiz_etage", 40)
    if etage in katalog.etagen(o) and etage != laufkarte.fiz_etage(o):
        o.fiz_etage, o.fiz_x, o.fiz_y = etage, None, None
        db.commit()
        flash(request, "Etage der FIZ geändert. Standort und Laufwege der Vorderseiten bitte prüfen oder die Schemapläne neu erzeugen.")
    return go(f"/objekte/{oid}/laufkarten")


@app.post("/objekte/{oid}/plan")
async def plan_hochladen(oid: int, request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    form = await read_form(request)
    o = objekt_for(db, user, oid)
    etage, datei = text(form, "etage", 40), form.get("datei")
    if etage not in katalog.etagen(o) or datei is None or not getattr(datei, "filename", ""):
        flash(request, "Bitte eine Etage und eine Bilddatei wählen.", "err")
        return go(f"/objekte/{oid}/laufkarten")
    daten = await datei.read(laufkarte.MAX_PLAN + 1)
    art = laufkarte.bildart(daten)
    if len(daten) > laufkarte.MAX_PLAN or not art:
        flash(request, "Der Plan muss ein Bild sein (PNG, JPG, WebP oder SVG) und darf höchstens 4 MB haben. Einen PDF-Plan vorher als Bild speichern.", "err")
        return go(f"/objekte/{oid}/laufkarten")
    plan = laufkarte.plan_von(o, etage)
    war_schema = plan is not None and plan.schema
    if plan is None:
        plan = m.Plan(etage=etage)
        o.plaene.append(plan)
    plan.mime, plan.daten, plan.schema = art, daten, False
    if war_schema:  # die Lagen aus dem Schemaplan passen nicht zum neuen Bild
        for g in o.gruppen:
            if g.etage == etage:
                g.weg2 = ""
                for x in g.melder:
                    x.px = x.py = None
            if etage == laufkarte.fiz_etage(o):
                g.weg1 = ""
        if etage == laufkarte.fiz_etage(o):
            o.fiz_x = o.fiz_y = None
    db.commit()
    flash(request, f"Plan für „{etage or 'Ohne Etage'}“ gespeichert." + (" Laufwege und Melder dieser Etage bitte neu einzeichnen." if war_schema else ""))
    return go(f"/objekte/{oid}/laufkarten")


@app.post("/plaene/{pid}/loeschen")
async def plan_loeschen(pid: int, request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    await read_form(request)
    plan = need(db.get(m.Plan, pid))
    o = objekt_for(db, user, plan.objekt_id)
    o.plaene.remove(plan)
    db.commit()
    flash(request, "Plan gelöscht. Eingezeichnete Wege und Melder bleiben gespeichert.")
    return go(f"/objekte/{o.id}/laufkarten")


@app.get("/plaene/{pid}")
def plan_bild(pid: int, user: m.User = Depends(allow("objekte:1")), db: Session = Depends(get_db)):
    plan = need(db.get(m.Plan, pid))
    objekt_for(db, user, plan.objekt_id)
    return plan_antwort(plan)


@app.post("/objekte/{oid}/laufkarten/schema")
async def laufkarten_schema(oid: int, request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    await read_form(request)
    o = objekt_for(db, user, oid)
    anzahl = laufkarte.schema_erzeugen(db, o)
    db.commit()
    flash(request, f"{anzahl} Schemapläne erzeugt, Melder und Laufwege dort eingetragen." if anzahl
          else "Alle Etagen haben einen hochgeladenen Plan; es wurde nichts geändert.")
    return go(f"/objekte/{oid}/laufkarten")


@app.get("/gruppen/{gid}/laufkarte")
def laufkarte_bearbeiten(gid: int, request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    g = need(db.get(m.Gruppe, gid))
    o = objekt_for(db, user, g.objekt_id)
    k = laufkarte.karte(o, g)
    daten = {"gleich": k["gleich"], "fiz": k["fiz"], "weg1": k["weg1"], "weg2": [] if k["gleich"] else k["weg2"],
             "melder": [{"id": x.id, "nr": x.nummer, "hfm": x.typ == "hfm", "x": x.px, "y": x.py} for x in g.melder]}
    nachbarn = [x.id for x in o.gruppen]
    i = nachbarn.index(g.id)
    return page(request, "laufkarte_form.html", user, o=o, k=k, daten=daten, planpfad="/plaene/",
                davor=nachbarn[i - 1] if i else None, danach=nachbarn[i + 1] if i + 1 < len(nachbarn) else None)


@app.post("/gruppen/{gid}/laufkarte")
async def laufkarte_speichern(gid: int, request: Request, user: m.User = Depends(allow("objekte:2")), db: Session = Depends(get_db)):
    form = await read_form(request)
    g = need(db.get(m.Gruppe, gid))
    o = objekt_for(db, user, g.objekt_id)
    g.laufweg, g.hinweis = text(form, "laufweg", 1500), text(form, "hinweis", 1000)
    g.weg1 = json.dumps(laufkarte.punkte(str(form.get("weg1", ""))[:4000]))
    g.weg2 = "" if g.etage == laufkarte.fiz_etage(o) else json.dumps(laufkarte.punkte(str(form.get("weg2", ""))[:4000]))
    try:
        fiz = json.loads(str(form.get("fiz", ""))[:100] or "null")
        lagen = json.loads(str(form.get("melder", ""))[:8000] or "{}")
    except ValueError:
        fiz, lagen = None, {}
    if isinstance(fiz, list) and len(fiz) == 2 and laufkarte.lage(fiz[0]) is not None and laufkarte.lage(fiz[1]) is not None:
        o.fiz_etage, o.fiz_x, o.fiz_y = laufkarte.fiz_etage(o), laufkarte.lage(fiz[0]), laufkarte.lage(fiz[1])
    if isinstance(lagen, dict):
        for x in g.melder:
            p = lagen.get(str(x.id))
            if isinstance(p, list) and len(p) == 2 and laufkarte.lage(p[0]) is not None and laufkarte.lage(p[1]) is not None:
                x.px, x.py = laufkarte.lage(p[0]), laufkarte.lage(p[1])
            elif p is None and str(x.id) in lagen:
                x.px = x.py = None
    db.commit()
    flash(request, f"Laufkarte {sim.nr(g.nummer)} gespeichert.")
    return go(f"/gruppen/{gid}/laufkarte")


@app.get("/objekte/{oid}/laufkarten/druck")
def laufkarten_druck(oid: int, request: Request, gruppe: int = 0, user: m.User = Depends(allow("objekte:1")), db: Session = Depends(get_db)):
    o = objekt_for(db, user, oid)
    karten = [laufkarte.karte(o, g) for g in o.gruppen if not gruppe or g.nummer == gruppe]
    return page(request, "laufkarten_druck.html", user, o=o, karten=karten, planpfad="/plaene/", zurueck=f"/objekte/{oid}/laufkarten")


# ---------- Anzeigen für die Übenden (ohne Anmeldung, über die geheime Adresse) ----------

def objekt_zu(db: Session, token: str) -> m.Objekt:
    return need(db.scalar(select(m.Objekt).where(m.Objekt.token == token)) if 8 <= len(token) <= 40 else None)


# ---------- Als App: Manifest, Service Worker ----------

@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(os.path.join(BASE, "static", "manifest.webmanifest"), media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
def service_worker():
    """Der Service Worker muss an der Wurzel liegen, damit er für alle Seiten gilt. Die Versionsnummer erneuert seinen Zwischenspeicher."""
    with open(os.path.join(BASE, "static", "sw.js"), encoding="utf-8") as handle:
        script = handle.read().replace("__VERSION__", VERSION)
    return Response(script, media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/offline")
def offline(request: Request):
    return templates.TemplateResponse(request, "offline.html", {})


@app.get("/a/{token}/manifest.webmanifest")
def anzeige_manifest(token: str, db: Session = Depends(get_db)):
    """Eigene App je Objekt für die Geräte der Übenden: startet ohne Anmeldung bei den Anzeigen und läuft im Vollbild."""
    o = objekt_zu(db, token)
    icons = [{"src": f"/static/icons/{name}.png", "sizes": f"{size}x{size}", "type": "image/png", "purpose": purpose}
             for name, size, purpose in (("icon-192", 192, "any"), ("icon-512", 512, "any"), ("icon-maskable-512", 512, "maskable"))]
    data = {"name": f"{o.name} (Übungsanlage)", "short_name": o.name[:24], "lang": "de", "id": f"/a/{o.token}", "start_url": f"/a/{o.token}",
            "scope": f"/a/{o.token}", "display": "fullscreen", "display_override": ["fullscreen", "standalone"],
            "background_color": "#2a2e33", "theme_color": "#1b1e22", "icons": icons}
    return JSONResponse(data, media_type="application/manifest+json", headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


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


@app.get("/a/{token}/laufkarten")
def anzeige_laufkarten(token: str, request: Request, db: Session = Depends(get_db)):
    o = objekt_zu(db, token)
    return anzeige(request, "anzeige_laufkarten.html", o, etagen=katalog.etagen(o))


@app.get("/a/{token}/laufkarten/alle")
def anzeige_laufkarten_alle(token: str, request: Request, db: Session = Depends(get_db)):
    o = objekt_zu(db, token)
    return anzeige(request, "laufkarten_druck.html", o, karten=[laufkarte.karte(o, g) for g in o.gruppen],
                   planpfad=f"/a/{token}/plan/", zurueck=f"/a/{token}/laufkarten", perm={})


@app.get("/a/{token}/laufkarte/{nummer}")
def anzeige_laufkarte(token: str, nummer: int, request: Request, db: Session = Depends(get_db)):
    o = objekt_zu(db, token)
    nummern = [g.nummer for g in o.gruppen]
    g = need(next((g for g in o.gruppen if g.nummer == nummer), None))
    i = nummern.index(nummer)
    return anzeige(request, "anzeige_laufkarte.html", o, k=laufkarte.karte(o, g), planpfad=f"/a/{token}/plan/",
                   davor=nummern[i - 1] if i else None, danach=nummern[i + 1] if i + 1 < len(nummern) else None)


@app.get("/a/{token}/plan/{pid}")
def anzeige_plan(token: str, pid: int, db: Session = Depends(get_db)):
    o = objekt_zu(db, token)
    plan = need(db.get(m.Plan, pid))
    if plan.objekt_id != o.id:
        raise HTTPException(404, "Nicht gefunden")
    return plan_antwort(plan)


@app.get("/a/{token}/state")
def anzeige_state(token: str, request: Request, v: int = 0, db: Session = Depends(get_db)):
    o = objekt_zu(db, token)
    live.melden(o.id, request.query_params)
    st = zustand(db, o)
    if v == st["v"]:
        return Response(status_code=204)
    return JSONResponse(oeffentlich(st), headers={"Cache-Control": "no-store"})


@app.get("/a/{token}/da")
def anzeige_da(token: str, request: Request, db: Session = Depends(get_db)):
    """Lebenszeichen der Seiten ohne eigene Anzeige (Auswahl, Verzeichnis) für das Live-Bild."""
    live.melden(objekt_zu(db, token).id, request.query_params)
    return Response(status_code=204)


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


# ---------- Benutzer und Rechte ----------

def einladung_starten(target: m.User) -> str:
    """Erzeugt einen Einmal-Link; gespeichert wird nur sein Hash. Ein früherer Link wird damit ungültig."""
    token = secrets.token_urlsafe(32)
    target.invite_hash = hashlib.sha256(token.encode()).hexdigest()
    target.invite_expires = m.utcnow() + dt.timedelta(hours=INVITE_HOURS)
    return token


def eingeladen(db: Session, token: str) -> m.User | None:
    digest = hashlib.sha256(token.encode()).hexdigest()
    found = db.scalar(select(m.User).where(m.User.invite_hash == digest))
    if not found or not found.invite_expires or found.invite_expires < m.utcnow():
        return None
    return found


@app.get("/benutzer")
def benutzer(request: Request, user: m.User = Depends(allow("users:2")), db: Session = Depends(get_db)):
    namen = {o.id: o.name for o in db.scalars(select(m.Objekt)).all()}
    now = m.utcnow()
    rows = [{"user": u, "role": access.role_of(u), "all": access.sees_all(u),
             "objekte": [namen[i] for i in sorted(access.objekt_ids(u)) if i in namen],
             "pending": bool(u.invite_hash and u.invite_expires and u.invite_expires > now),
             "online": bool(u.last_seen and (now - u.last_seen).total_seconds() < 180)}
            for u in db.scalars(select(m.User).order_by(m.User.username)).all()]
    return page(request, "benutzer.html", user, rows=rows)


def benutzer_formular(request: Request, user: m.User, db: Session, target: m.User | None):
    link = None
    merk = request.session.pop("einladung", None)
    if target and merk and merk[0] == target.id:
        link = f"{str(request.base_url).rstrip('/')}/einladung/{merk[1]}"
    return page(request, "benutzer_form.html", user, target=target, areas=access.AREAS, presets=access.PRESETS,
                role_names=access.ROLE_NAMES, role_hints=access.ROLE_HINTS,
                tperms=access.perms_of(target) if target else dict(access.PRESETS["ausbilder"]),
                t_all=access.sees_all(target) if target else True, t_ids=access.objekt_ids(target) if target else set(),
                objekte=db.scalars(select(m.Objekt).order_by(m.Objekt.name)).all(), link=link, hours=INVITE_HOURS,
                pending=bool(target and target.invite_hash and target.invite_expires and target.invite_expires > m.utcnow()))


@app.get("/benutzer/neu")
def benutzer_neu(request: Request, user: m.User = Depends(allow("users:2")), db: Session = Depends(get_db)):
    return benutzer_formular(request, user, db, None)


@app.get("/benutzer/{uid}/bearbeiten")
def benutzer_bearbeiten(uid: int, request: Request, user: m.User = Depends(allow("users:2")), db: Session = Depends(get_db)):
    return benutzer_formular(request, user, db, need(db.get(m.User, uid)))


@app.post("/benutzer/speichern")
async def benutzer_speichern(request: Request, user: m.User = Depends(allow("users:2")), db: Session = Depends(get_db)):
    form = await read_form(request)
    uid, password = text(form, "id", 12), str(form.get("password", ""))
    perms, everything, ids = access.from_form(form)
    if password and len(password) < 12:
        flash(request, "Das Passwort braucht mindestens 12 Zeichen.", "err")
        return go(f"/benutzer/{uid}/bearbeiten" if uid else "/benutzer/neu")
    if uid:
        target = need(db.get(m.User, int(uid)))
        if target.id == user.id and perms["users"] != 2:
            flash(request, "Das Recht, Benutzer zu verwalten, kannst du dir nicht selbst nehmen.", "err")
            return go(f"/benutzer/{uid}/bearbeiten")
    else:
        name = text(form, "username", 80)
        if not name:
            flash(request, "Bitte einen Benutzernamen eintragen.", "err")
            return go("/benutzer/neu")
        if db.scalar(select(m.User).where(func.lower(m.User.username) == name.lower())):
            flash(request, "Diesen Benutzernamen gibt es schon.", "err")
            return go("/benutzer/neu")
        target = m.User(username=name, password_hash="")
        db.add(target)
    target.perms, target.all_objekte, target.objekt_ids = json.dumps(perms), everything, ids
    target.is_admin = perms["users"] == 2
    if password:
        target.password_hash = sec.hash_password(password)
        target.invite_hash, target.invite_expires = "", None
    token = None if target.password_hash else einladung_starten(target)
    db.commit()
    if token:  # ohne Passwort angelegt: Der Einmal-Link wird genau einmal auf der Folgeseite gezeigt
        request.session["einladung"] = [target.id, token]
        flash(request, f"Benutzer „{target.username}“ angelegt. Gib ihm den Link unten weiter.")
        return go(f"/benutzer/{target.id}/bearbeiten")
    flash(request, f"Benutzer „{target.username}“ gespeichert.")
    return go("/benutzer")


@app.post("/benutzer/{uid}/einladung")
async def benutzer_einladung(uid: int, request: Request, user: m.User = Depends(allow("users:2")), db: Session = Depends(get_db)):
    await read_form(request)
    target = need(db.get(m.User, uid))
    request.session["einladung"] = [target.id, einladung_starten(target)]
    db.commit()
    flash(request, "Neuer Link erzeugt. Ein früherer Link gilt nicht mehr.")
    return go(f"/benutzer/{uid}/bearbeiten")


@app.post("/benutzer/{uid}/loeschen")
async def benutzer_loeschen(uid: int, request: Request, user: m.User = Depends(allow("users:2")), db: Session = Depends(get_db)):
    await read_form(request)
    ziel = need(db.get(m.User, uid))
    if ziel.id == user.id:
        flash(request, "Das eigene Konto lässt sich nicht löschen.", "err")
    else:
        db.delete(ziel)
        db.commit()
        flash(request, f"Benutzer „{ziel.username}“ gelöscht.")
    return go("/benutzer")


@app.get("/einladung/{token}")
def einladung_form(token: str, request: Request, db: Session = Depends(get_db)):
    return page(request, "einladung.html", None, target=eingeladen(db, token), token=token, hours=INVITE_HOURS)


@app.post("/einladung/{token}")
async def einladung_speichern(token: str, request: Request, db: Session = Depends(get_db)):
    form = await read_form(request)
    target = eingeladen(db, token)
    if target is None:
        return page(request, "einladung.html", None, target=None, token=token, hours=INVITE_HOURS)
    password = str(form.get("password", ""))
    if len(password) < 12 or password != str(form.get("repeat", "")):
        flash(request, "Das Passwort braucht mindestens 12 Zeichen, und beide Eingaben müssen gleich sein.", "err")
        return go(f"/einladung/{token}")
    target.password_hash = sec.hash_password(password)
    target.invite_hash, target.invite_expires = "", None  # Link ist damit verbraucht
    db.commit()
    log.info("%r hat über den Einladungslink ein Passwort festgelegt.", target.username)
    flash(request, "Passwort gespeichert. Du kannst dich jetzt anmelden.")
    return go("/login")


# ---------- Sicherung ----------

@app.get("/sicherung")
def sicherung(request: Request, user: m.User = Depends(allow("users:2"))):
    return page(request, "sicherung.html", user, items=backup.listing(), keep=backup.KEEP, hours=backup.AUTO_HOURS, folder=backup.DIR)


@app.post("/sicherung/herunterladen")
async def sicherung_herunterladen(request: Request, user: m.User = Depends(allow("users:2"))):
    await read_form(request)
    name, data = await asyncio.to_thread(backup.build)
    log.info("Sicherung heruntergeladen von %r.", user.username)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/sicherung/ablegen")
async def sicherung_ablegen(request: Request, user: m.User = Depends(allow("users:2"))):
    await read_form(request)
    try:
        name = await asyncio.to_thread(backup.store)
    except OSError as exc:
        flash(request, f"Die Sicherung konnte nicht abgelegt werden: {exc}", "err")
        return go("/sicherung")
    flash(request, f"Sicherung {name} abgelegt.")
    return go("/sicherung")


@app.get("/sicherung/datei/{name}")
def sicherung_datei(name: str, user: m.User = Depends(allow("users:2"))):
    return FileResponse(need(backup.path_of(name)), media_type="application/zip", filename=name)


@app.post("/sicherung/datei/{name}/loeschen")
async def sicherung_loeschen(name: str, request: Request, user: m.User = Depends(allow("users:2"))):
    await read_form(request)
    os.remove(need(backup.path_of(name)))
    flash(request, f"Sicherung {name} gelöscht.")
    return go("/sicherung")


@app.get("/konto")
def konto(request: Request, user: m.User = Depends(current_user)):
    return page(request, "konto.html", user, role=access.role_of(user))


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
