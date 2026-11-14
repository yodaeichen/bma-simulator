"""Berechtigungen der Benutzer: Einzelrechte je Bereich, Rollen als Vorlage, Beschränkung auf Objekte."""
import json

# Bereich, Bezeichnung, erlaubte Stufen, Erklärung
AREAS = [
    ("objekte", "Objekte und Melderlisten", [(1, "nur sehen"), (2, "bearbeiten")],
     "Bearbeiten: Objekte anlegen, kopieren und löschen, Melderlisten ändern und einlesen, die Adresse der Anzeigen erneuern."),
    ("uebung", "Übungen", [(0, "kein Zugriff"), (1, "zusehen"), (2, "steuern")],
     "Zusehen: die Ausbilderansicht mit Meldungen und Live-Bild öffnen, ohne etwas auszulösen. "
     "Steuern: Melder auslösen, stören, abschalten und die Anlage zurücksetzen."),
    ("protokoll", "Übungsprotokoll", [(0, "kein Zugriff"), (1, "sehen"), (2, "sehen und leeren")],
     "Sehen schließt den Download als CSV ein."),
    ("users", "Benutzer, Rechte und Sicherung", [(0, "kein Zugriff"), (2, "verwalten")],
     "Darf Benutzer anlegen, löschen und alle Rechte vergeben sowie Sicherungen anlegen und herunterladen. Gilt immer für alle Objekte."),
]
PRESETS = {
    "admin": {"objekte": 2, "uebung": 2, "protokoll": 2, "users": 2},
    "ausbilder": {"objekte": 2, "uebung": 2, "protokoll": 2, "users": 0},
    "beobachter": {"objekte": 1, "uebung": 1, "protokoll": 1, "users": 0},
}
ROLE_NAMES = {"admin": "Administrator", "ausbilder": "Ausbilder", "beobachter": "Beobachter"}
ROLE_HINTS = {
    "admin": "darf alles",
    "ausbilder": "legt Objekte an und steuert Übungen, verwaltet aber keine Benutzer",
    "beobachter": "darf nur zusehen",
}


class Denied(Exception):
    def __init__(self, message: str = "Dafür fehlt dir die Berechtigung."):
        self.message = message


def clean(perms: dict) -> dict:
    """Bringt Rechte in gültige Form: nur bekannte Bereiche und erlaubte Stufen."""
    result = {}
    for area, _label, levels, _hint in AREAS:
        allowed_levels = [level for level, _ in levels]
        try:
            value = int(perms.get(area, allowed_levels[0]))
        except (TypeError, ValueError):
            value = allowed_levels[0]
        result[area] = value if value in allowed_levels else allowed_levels[0]
    return result


def perms_of(user) -> dict:
    """Rechte eines Benutzers. Konten aus Version 1.0 haben keine Angabe: Administrator oder Ausbilder nach is_admin."""
    if not user.perms:
        return dict(PRESETS["admin" if user.is_admin else "ausbilder"])
    try:
        return clean(json.loads(user.perms))
    except ValueError:
        return clean({})


def sees_all(user) -> bool:
    return user.all_objekte is None or bool(user.all_objekte) or perms_of(user)["users"] == 2


def objekt_ids(user) -> set[int]:
    return {int(part) for part in (user.objekt_ids or "").split(",") if part.strip().isdigit()}


def allowed(user, objekt_id: int) -> bool:
    return sees_all(user) or objekt_id in objekt_ids(user)


def role_of(user) -> str:
    perms = perms_of(user)
    for key, preset in PRESETS.items():
        if perms == preset:
            return ROLE_NAMES[key]
    return "Angepasst"


def require(user, *needs: str):
    """needs wie "uebung:2". Löst Denied aus, wenn etwas fehlt."""
    perms = perms_of(user)
    for item in needs:
        area, _, level = item.partition(":")
        if perms[area] < int(level or 1):
            label = next(text for key, text, _l, _h in AREAS if key == area)
            raise Denied(f"Dafür fehlt dir die Berechtigung im Bereich „{label}“.")


def from_form(form) -> tuple[dict, bool, str]:
    """Liest Rechte, „alle Objekte“ und die Liste der Objekte aus dem Benutzerformular."""
    perms = clean({area: form.get(f"p_{area}") for area, *_ in AREAS})
    everything = "all_objekte" in form or perms["users"] == 2  # wer Rechte vergibt, könnte sich ohnehin alles freischalten
    ids = sorted({int(v) for v in form.getlist("objekt") if str(v).isdigit()})
    return perms, everything, ",".join(str(i) for i in ids)
