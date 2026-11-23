"""Datenmodell (SQLite über SQLAlchemy)."""
import datetime as dt
import os
import secrets

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

DATA_DIR = os.environ.get("DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)
engine = create_engine(f"sqlite:///{DATA_DIR}/simulator.db", connect_args={"check_same_thread": False, "timeout": 30})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(conn, _):
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(engine, expire_on_commit=False)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def new_token() -> str:
    return secrets.token_urlsafe(12)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    # Aus Version 1.0: nur noch Vorgabe für Konten ohne eigene Rechte (siehe access.py)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Rechte als JSON (siehe access.py). Leer = Konto aus Version 1.0, Rechte ergeben sich aus is_admin.
    perms: Mapped[str | None] = mapped_column(Text, nullable=True)
    all_objekte: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    objekt_ids: Mapped[str] = mapped_column(Text, default="", server_default="")  # freigegebene Objekt-IDs, mit Komma
    # Einladung: nur der Hash des Einmal-Links wird gespeichert, mit Ablaufzeit
    invite_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    invite_expires: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_login: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)  # letzte Aktivität; leer nach dem Abmelden


class Objekt(Base):
    """Ein Übungsobjekt mit eigener Brandmeldeanlage."""
    __tablename__ = "objekte"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    adresse: Mapped[str] = mapped_column(String(200), default="", server_default="")
    bma_nr: Mapped[str] = mapped_column(String(40), default="", server_default="")
    hinweis: Mapped[str] = mapped_column(Text, default="", server_default="")
    loeschanlage: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Geheimer Teil der Adresse, unter der die Anzeigen (FAT, FBF, BMZ) ohne Anmeldung erreichbar sind
    token: Mapped[str] = mapped_column(String(40), unique=True, default=new_token)
    # Laufender Zustand der Anlage als JSON (siehe sim.py)
    state: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Laufkarten: Etage, in der die Feuerwehr-Informationszentrale (FIZ) liegt, und ihr Standort im Plan (0 bis 1)
    fiz_etage: Mapped[str] = mapped_column(String(40), default="", server_default="")
    fiz_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    fiz_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    gruppen: Mapped[list["Gruppe"]] = relationship(back_populates="objekt", cascade="all, delete-orphan",
                                                    order_by="Gruppe.nummer")
    plaene: Mapped[list["Plan"]] = relationship(back_populates="objekt", cascade="all, delete-orphan")
    szenarien: Mapped[list["Szenario"]] = relationship(back_populates="objekt", cascade="all, delete-orphan",
                                                       order_by="Szenario.name")
    protokoll: Mapped[list["Protokoll"]] = relationship(cascade="all, delete-orphan")


class Gruppe(Base):
    """Meldergruppe: gehört zu einem Objekt und liegt in einer Etage bzw. einem Bereich."""
    __tablename__ = "gruppen"
    __table_args__ = (UniqueConstraint("objekt_id", "nummer"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    objekt_id: Mapped[int] = mapped_column(ForeignKey("objekte.id", ondelete="CASCADE"))
    nummer: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(80), default="")
    etage: Mapped[str] = mapped_column(String(40), default="")
    # Laufkarte: Laufweg in Worten (je Zeile ein Schritt), Besonderheiten und die gezeichneten Wege als JSON [[x, y], ...]
    laufweg: Mapped[str] = mapped_column(Text, default="", server_default="")
    hinweis: Mapped[str] = mapped_column(Text, default="", server_default="")
    weg1: Mapped[str] = mapped_column(Text, default="", server_default="")  # im Plan der FIZ-Etage (Vorderseite)
    weg2: Mapped[str] = mapped_column(Text, default="", server_default="")  # im Plan der eigenen Etage, falls eine andere
    objekt: Mapped[Objekt] = relationship(back_populates="gruppen")
    melder: Mapped[list["Melder"]] = relationship(back_populates="gruppe", cascade="all, delete-orphan",
                                                   order_by="Melder.nummer")


class Melder(Base):
    __tablename__ = "melder"
    __table_args__ = (UniqueConstraint("gruppe_id", "nummer"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    gruppe_id: Mapped[int] = mapped_column(ForeignKey("gruppen.id", ondelete="CASCADE"))
    nummer: Mapped[int] = mapped_column(Integer)
    typ: Mapped[str] = mapped_column(String(10), default="rm")
    ort: Mapped[str] = mapped_column(String(80), default="")
    px: Mapped[float | None] = mapped_column(Float, nullable=True)  # Lage im Plan der Etage (0 bis 1)
    py: Mapped[float | None] = mapped_column(Float, nullable=True)
    gruppe: Mapped[Gruppe] = relationship(back_populates="melder")


class Szenario(Base):
    """Vorbereiteter Übungsablauf: Schritte mit Zeitpunkt, Art und Melder (siehe szenario.py)."""
    __tablename__ = "szenarien"
    id: Mapped[int] = mapped_column(primary_key=True)
    objekt_id: Mapped[int] = mapped_column(ForeignKey("objekte.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    beschreibung: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Schritte als JSON: [{"sek", "aktion", "g", "m", "text", "ansteht"}]; Melder über Gruppen- und Meldernummer,
    # damit ein Szenario das Kopieren des Objekts und das Neueinlesen der Melderliste übersteht
    schritte: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    objekt: Mapped[Objekt] = relationship(back_populates="szenarien")


class Plan(Base):
    """Grundriss einer Etage für die Laufkarten: hochgeladenes Bild oder erzeugter Schemaplan."""
    __tablename__ = "plaene"
    __table_args__ = (UniqueConstraint("objekt_id", "etage"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    objekt_id: Mapped[int] = mapped_column(ForeignKey("objekte.id", ondelete="CASCADE"))
    etage: Mapped[str] = mapped_column(String(40), default="")
    mime: Mapped[str] = mapped_column(String(40))
    daten: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    schema: Mapped[bool] = mapped_column(Boolean, default=False)  # vom Simulator gezeichnet, nicht maßstäblich
    objekt: Mapped[Objekt] = relationship(back_populates="plaene")


class Protokoll(Base):
    """Übungsprotokoll: wer hat wann was ausgelöst oder bedient."""
    __tablename__ = "protokoll"
    id: Mapped[int] = mapped_column(primary_key=True)
    objekt_id: Mapped[int] = mapped_column(ForeignKey("objekte.id", ondelete="CASCADE"), index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    quelle: Mapped[str] = mapped_column(String(40), default="")
    text: Mapped[str] = mapped_column(Text, default="")


# Spalten, die nach Version 1.0 dazukamen (Rechte in 1.1, Laufkarten in 1.2): bestehende Datenbanken werden beim Start ergänzt.
ADDED_COLUMNS = {
    "objekte": {"fiz_etage": "VARCHAR(40) NOT NULL DEFAULT ''", "fiz_x": "FLOAT", "fiz_y": "FLOAT"},
    "gruppen": {"laufweg": "TEXT NOT NULL DEFAULT ''", "hinweis": "TEXT NOT NULL DEFAULT ''",
                "weg1": "TEXT NOT NULL DEFAULT ''", "weg2": "TEXT NOT NULL DEFAULT ''"},
    "melder": {"px": "FLOAT", "py": "FLOAT"},
    "users": {
        "perms": "TEXT",
        "all_objekte": "BOOLEAN NOT NULL DEFAULT 1",
        "objekt_ids": "TEXT NOT NULL DEFAULT ''",
        "invite_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
        "invite_expires": "DATETIME",
        "last_seen": "DATETIME",
    },
}


def add_missing_columns():
    with engine.begin() as conn:
        for table, columns in ADDED_COLUMNS.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if not existing:
                continue  # Tabelle gibt es noch nicht: create_all legt sie vollständig an
            for name, ddl in columns.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db():
    Base.metadata.create_all(engine)
    add_missing_columns()
