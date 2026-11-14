"""Sicherung der Datenbank: Objekte, Melderlisten, Benutzer und Protokolle in einer ZIP-Datei."""
import datetime as dt
import io
import os
import re
import sqlite3
import tempfile
import zipfile

from . import db as m
from .version import VERSION

DIR = os.path.join(m.DATA_DIR, "backups")
KEEP = int(os.environ.get("BACKUP_KEEP", "14"))        # so viele Sicherungen bleiben auf dem Server liegen
AUTO_HOURS = int(os.environ.get("BACKUP_HOURS", "24"))  # Abstand der automatischen Sicherung, 0 = aus
NAME = re.compile(r"^bma-simulator-\d{8}-\d{6}(-auto)?\.zip$")

INFO = """BMA Simulator – Sicherung
Erstellt: {stamp} (UTC), Version {version}

Inhalt
  simulator.db   Datenbank mit allen Objekten, Melderlisten, Benutzern, Rechten und Übungsprotokollen

Hinweis
  Die Datei enthält die Benutzernamen und die Hashes der Passwörter. Nicht offen herumliegen lassen.
  Der SECRET_KEY aus /etc/bma-simulator.env gehört nicht dazu und wird für die Wiederherstellung nicht gebraucht:
  Mit einem anderen Schlüssel müssen sich nur alle neu anmelden.

Wiederherstellen (auf dem Proxmox-Host, <CTID> ist die Nummer des Containers)
  1. Diese ZIP-Datei in den Container legen, z. B. mit: pct push <CTID> sicherung.zip /root/sicherung.zip
  2. pct exec <CTID> -- systemctl stop bma-simulator
  3. pct exec <CTID> -- python3 -m zipfile -e /root/sicherung.zip /root/sicherung
  4. pct exec <CTID> -- bash -c 'rm -f /var/lib/bma-simulator/simulator.db-wal /var/lib/bma-simulator/simulator.db-shm'
  5. pct exec <CTID> -- install -o bma-sim -g bma-sim -m 600 /root/sicherung/simulator.db /var/lib/bma-simulator/simulator.db
  6. pct exec <CTID> -- systemctl start bma-simulator
"""


def _snapshot() -> bytes:
    """Ein in sich stimmiger Abzug der laufenden Datenbank (SQLite-Sicherungsfunktion, auch im WAL-Betrieb sicher)."""
    handle, path = tempfile.mkstemp(suffix=".db", dir=m.DATA_DIR)
    os.close(handle)
    try:
        source = sqlite3.connect(os.path.join(m.DATA_DIR, "simulator.db"), timeout=30)
        target = sqlite3.connect(path)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        with open(path, "rb") as file:
            return file.read()
    finally:
        os.remove(path)


def build() -> tuple[str, bytes]:
    """Erzeugt die ZIP-Datei im Speicher. Gibt Dateinamen und Inhalt zurück."""
    now = dt.datetime.now(dt.timezone.utc)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("simulator.db", _snapshot())
        archive.writestr("LIESMICH.txt", INFO.format(stamp=now.strftime("%d.%m.%Y %H:%M"), version=VERSION))
    return f"bma-simulator-{now.strftime('%Y%m%d-%H%M%S')}.zip", buffer.getvalue()


def listing() -> list[dict]:
    if not os.path.isdir(DIR):
        return []
    items = []
    for name in sorted((n for n in os.listdir(DIR) if NAME.match(n)), reverse=True):
        stat = os.stat(os.path.join(DIR, name))
        items.append({"name": name, "size": stat.st_size, "auto": name.endswith("-auto.zip"),
                      "ts": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).replace(tzinfo=None)})
    return items


def store(auto: bool = False) -> str:
    """Legt eine Sicherung im Datenverzeichnis ab und räumt alte weg. Gibt den Dateinamen zurück."""
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    name, data = build()
    if auto:
        name = name.replace(".zip", "-auto.zip")
    path = os.path.join(DIR, name)
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as file:
        file.write(data)
    for old in listing()[KEEP:]:
        os.remove(os.path.join(DIR, old["name"]))
    return name


def path_of(name: str) -> str | None:
    """Pfad einer vorhandenen Sicherung; None bei unbekanntem oder unzulässigem Namen."""
    path = os.path.join(DIR, name)
    return path if NAME.match(name or "") and os.path.isfile(path) else None


def auto_due() -> bool:
    if AUTO_HOURS <= 0:
        return False
    items = listing()
    return not items or (m.utcnow() - items[0]["ts"]).total_seconds() >= AUTO_HOURS * 3600
