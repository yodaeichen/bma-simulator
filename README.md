# BMA Simulator

Übungsanlage für den Einsatz „ausgelöste Brandmeldeanlage": Der Ausbilder löst an seinem Gerät Melder aus,
die Übenden lesen an einem zweiten Gerät das Feuerwehr-Anzeigetableau ab und bedienen das Feuerwehr-Bedienfeld.

Aktuelle Version und Änderungen: siehe [CHANGELOG.md](CHANGELOG.md). Die laufende Version steht unten auf jeder Seite.

## Aufbau

| Ansicht | Für wen | Wofür |
|---|---|---|
| **Objekte** | Ausbilder | Übersicht aller Objekte mit ihrem Zustand |
| **Übung** (Ausbilderansicht) | Ausbilder | Melder nach Etagen und Gruppen, auslösen, stören, abschalten; Zustand der Anlage; Live-Bild der Übenden; Protokoll |
| **Melderliste** | Ausbilder | Gruppen und Melder eines Objekts anlegen, als CSV einlesen und herunterladen |
| **Szenarien** | Ausbilder | Vorbereitete Übungsabläufe mit festen Zeitpunkten, in der Übung mit einem Klick gestartet |
| **FAT und FBF** | Übende | Feuerwehr-Anzeigetableau und Feuerwehr-Bedienfeld |
| **BMZ** | Übende | Anzeige- und Bedienteil der Brandmelderzentrale |
| **Laufkarten** | Ausbilder | Pläne je Etage, Laufwege und Melder einzeichnen, alle Karten drucken |
| **Meldergruppen** | Übende | Verzeichnis der Gruppen und Melder |
| **Laufkarten** (Anzeige) | Übende | Feuerwehr-Laufkarten je Meldergruppe auf Tablet oder Beamer |
| **Benutzer** | Administrator | Benutzer anlegen, Rechte je Bereich, Beschränkung auf Objekte, Einmal-Link für das Passwort |
| **Sicherung** | Administrator | Datenbank herunterladen oder auf dem Server ablegen |

Die Ansichten der Übenden brauchen keine Anmeldung. Sie liegen unter einer Adresse mit geheimem Teil
(`/a/<token>`), die die Ausbilderansicht als Link und QR-Code zeigt. „Adresse erneuern" macht die alte ungültig.

FAT und FBF sind in Aufbau und Beschriftung an DIN 14662 und DIN 14661 angelehnt. Die BMZ ist ein allgemeines
Bedienteil ohne Vorbild eines bestimmten Herstellers. Der Simulator ersetzt keine Einweisung an der echten Anlage.

## Was die Anlage nachbildet

- **ÜE:** löst beim ersten Alarm aus (Leitstelle alarmiert, FSD entriegelt). Mit „ÜE ab" wird nichts übertragen;
  wird sie bei anstehendem Alarm wieder eingeschaltet, löst sie sofort aus.
- **Akustische Signale** und **Brandfallsteuerungen:** laufen bei Alarm, bis sie am FBF abgeschaltet werden.
- **BMZ rückstellen:** löscht Alarme und die ÜE-Auslösung. Störungen, Abschaltungen und die „ab"-Schalter bleiben.
- **Ursache steht an:** Der Melder löst fünf Sekunden nach dem Rückstellen erneut aus, bis der Ausbilder die Ursache beseitigt.
- **Verzögerung und Ausbreitung:** Auslösung nach einer Wartezeit; danach sprechen bis zu vier weitere automatische
  Melder derselben Gruppe und Etage im gewählten Abstand an.
- **Störungen und Abschaltungen:** an Meldern, Gruppen oder der Anlage (Netzausfall, Akku, ÜE-Leitung, Erdschluss).
  Abgeschaltete Melder lösen nicht aus.
- **Löschanlage:** Eine ausgelöste Sprinklergruppe setzt „Löschanlage ausgelöst".
- **Übungsprotokoll:** Jede Auslösung und jede Bedienung mit Uhrzeit und Gerät, als CSV für die Nachbesprechung.
- **Brandfallsteuerungen ab** geht nur, solange die BMA nicht im Brandmeldezustand ist.
- **Historie:** Die Anlage merkt sich alle Meldungen seit der Grundstellung, auch rückgestellte.

## FAT und FBF bedienen (ab Version 1.5)

| Bedienelement | Kurz drücken | Länger als 5 Sekunden halten |
|---|---|---|
| ▲ / ▼ „weitere Meldungen" | blättert durch die Meldungen zwischen erster und letzter | – |
| „Anzeigeebene" | Alarme → Störungen → Abschaltungen | Historie |
| „Summer ab" | stellt den Summer des FAT ab | Anzeigetest (alle Leuchten, Anzeige, Summer) |

Ohne Bedienung springt das FAT nach 20 Sekunden zurück auf erste und letzte Meldung. In der Leiste der Anzeige schalten
„Summer-Ton ein" und „Hausalarm ein" die Töne auf diesem Gerät ein; der Hausalarm läuft, solange die akustischen Signale
der BMA laufen. „Erklären" macht aus jedem Bedienelement von FAT und FBF eine Erklärung, statt es auszulösen.

## Szenarien (ab Version 1.5)

Ein Szenario ist ein vorbereiteter Ablauf für ein Objekt: Je Schritt ein Zeitpunkt nach dem Start, die Art (Alarm,
Störung, Abschaltung, Löschanlage), der Melder oder die Gruppe und bei Alarmen, ob die Ursache ansteht. Angelegt werden
Szenarien beim Objekt unter „Szenarien", gestartet in der Übung mit „Szenario starten". Die Melder sind über Gruppen- und
Meldernummer gespeichert; ein Szenario übersteht deshalb das Kopieren des Objekts und das Neueinlesen der Melderliste.
Fehlt ein Melder beim Start, wird der Schritt übersprungen und im Protokoll vermerkt.

## Als App auf Handy und Tablet (ab Version 1.3)

Der Simulator ist eine installierbare Web-App (PWA). Es gibt keine App im App Store oder bei Google Play: Die App
wird direkt von der eigenen Adresse des Simulators installiert und kommt mit jeder neuen Version von selbst mit.

| App | Für wen | Installieren von | Verhalten |
|---|---|---|---|
| **BMA Simulator** | Ausbilder | einer beliebigen Seite nach der Anmeldung, Anleitung unter „Mein Konto" | eigenes Fenster, Anmeldung wie im Browser |
| **<Objektname> (Übungsanlage)** | Übende | der Auswahlseite der Anzeigen (`/a/<token>`, QR-Code der Ausbilderansicht) | Vollbild, keine Anmeldung, startet bei FAT, BMZ, Verzeichnis und Laufkarten |

| Gerät | So geht es |
|---|---|
| **Android** (Chrome) | Seite öffnen, Menü mit den drei Punkten, „App installieren" |
| **iPhone / iPad** (Safari) | Seite öffnen, „Teilen", „Zum Home-Bildschirm" |
| **Rechner** (Chrome, Edge) | Symbol „Installieren" rechts in der Adresszeile |

Auf den Anzeigen hält der Simulator den Bildschirm an, solange sie im Vordergrund offen sind, und die Leiste hat
einen Knopf „Vollbild" (nicht auf dem iPhone, dort die App installieren).

Voraussetzungen und Grenzen:

- **HTTPS mit gültigem Zertifikat** (z. B. über den Nginx Proxy Manager mit Let's Encrypt). Über `http://` oder mit
  selbst signiertem Zertifikat gibt es weder Installation noch „Bildschirm bleibt an".
- Die Geräte müssen den Simulator **erreichen** können (WLAN oder VPN). Die App speichert keine Seiten und keinen
  Zustand der Anlage auf dem Gerät; ohne Verbindung zeigt sie „Simulator nicht erreichbar".
- Die App der Übenden gehört zur Adresse des Objekts. Nach „Adresse erneuern" die App auf dem Gerät entfernen und
  von der neuen Adresse neu installieren.

## Logo und Erscheinungsbild

Das App-Symbol liegt in `app/static/icons/`, die Bilder des Seitenfußes (Flammen `feuer.webp`, Atemschutzträger
`atemschutz.svg`) in `app/static/img/`. Wer das Projekt für die eigene Wehr anpasst, tauscht diese Dateien aus;
die Farben stehen am Ende von `app/static/style.css` unter „Erscheinungsbild". Die Vorlagen für Flammen und
Zeichnung stammen von der Löschgruppe Eichen.

## Live-Bild der Übenden

Die Ausbilderansicht zeigt für jede geöffnete Anzeige eine kleine Kachel: den Text, den FAT oder BMZ gerade zeigt,
die Anzeigeebene, ob das FBF aufgeschlossen ist, ob der Ton eingeschaltet ist und welche Taste zuletzt gedrückt wurde,
auch wenn sie ohne Wirkung blieb (verschlossenes FBF). Ein Gerät, das sich sechs Sekunden nicht meldet, verschwindet.
Das Live-Bild wird nicht gespeichert; was die Anlage verändert, steht wie bisher im Übungsprotokoll.

## Feuerwehr-Laufkarten

Jede Meldergruppe hat eine Laufkarte mit zwei Seiten: vorn die Etage der FIZ mit dem Laufweg, hinten die Etage der Gruppe
mit ihren Meldern. Am Rand stehen der Laufweg in Worten, Besonderheiten und die Zeichenerklärung.

- **Pläne:** je Etage ein eigenes Bild (PNG, JPG, WebP oder SVG, höchstens 4 MB; einen PDF-Plan vorher als Bild speichern)
  oder ein **Schemaplan**. Den zeichnet der Simulator aus der Melderliste: Flur in der Mitte, die Räume darüber und darunter,
  Treppenraum links, Zugang der Feuerwehr rechts. Er ist nicht maßstäblich und trägt Melder, FIZ und Laufwege gleich mit ein.
- **Bearbeiten:** unter „Laufkarten" bei der Gruppe „Bearbeiten". Ein Klick in den Plan setzt den Standort der FIZ,
  verlängert den Laufweg oder setzt den gewählten Melder.
- **Aushändigen:** „Alle Laufkarten drucken" öffnet die Druckansicht (A4 quer, je Karte zwei Seiten; beidseitig drucken und
  an der kurzen Kante wenden).
- **Digital:** Die Übenden öffnen „Laufkarten" unter der Adresse der Anzeigen, auf dem Tablet oder am Beamer.

Echte Laufkarten nach DIN 14675 erstellt der Errichter der Anlage aus den Bestandsplänen. Die Karten des Simulators sind
daran angelehnt und für Übungen gedacht.

## Benutzer und Rechte

| Bereich | Stufen |
|---|---|
| Objekte und Melderlisten | nur sehen, bearbeiten |
| Übungen | kein Zugriff, zusehen, steuern |
| Übungsprotokoll | kein Zugriff, sehen, sehen und leeren |
| Benutzer, Rechte und Sicherung | kein Zugriff, verwalten |

Die Rollen **Administrator**, **Ausbilder** und **Beobachter** füllen diese Rechte als Vorlage aus; danach lässt sich jedes
Recht einzeln ändern. Je Benutzer lässt sich festlegen, ob er alle Objekte sieht oder nur ausgewählte.

Wird ein Benutzer ohne Passwort angelegt, zeigt der Simulator einmalig einen Link, über den der Benutzer sein Passwort
selbst festlegt (48 Stunden gültig, nur einmal verwendbar). „Neuen Einmal-Link erzeugen" hilft bei vergessenem Passwort.

## Installation auf Proxmox (Einzeiler)

Auf dem Proxmox-Host als root:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/yodaeichen/bma-simulator/main/proxmox/install.sh)"
```

Das Skript legt einen unprivilegierten Debian-LXC an (1 Kern, 512 MB RAM, 4 GB Platte, DHCP),
installiert die Anwendung als systemd-Dienst und zeigt am Ende Adresse und Startpasswort an.
Docker wird dabei nicht verwendet.

Anpassen über Variablen vor dem Befehl:

```bash
CTID=150 STORAGE=local-zfs BRIDGE=vmbr1 IP=192.168.10.50/24 GW=192.168.10.1 \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/yodaeichen/bma-simulator/main/proxmox/install.sh)"
```

| Variable | Standard | Bedeutung |
|---|---|---|
| `CTID` | nächste freie ID | Container-ID |
| `CT_HOSTNAME` | `bma-simulator` | Hostname |
| `STORAGE` | erster aktiver Container-Speicher | Speicher für die Platte |
| `TEMPLATE_STORAGE` | erster aktiver Vorlagen-Speicher | Speicher für die Debian-Vorlage |
| `CORES` / `MEMORY` / `SWAP` / `DISK` | 1 / 512 / 512 / 4 | Kerne, MB, MB, GB |
| `BRIDGE` / `VLAN` | `vmbr0` / leer | Netzwerk |
| `IP` / `GW` | `dhcp` / leer | feste Adresse im Format `192.168.1.50/24` plus Gateway |

**Danach:**

1. Mit dem angezeigten Startpasswort anmelden und es unter „Mein Konto" ändern.
2. Im Reverse Proxy (z. B. Nginx Proxy Manager) einen Host mit HTTPS auf `http://<Container-IP>:8000` legen.
3. Im Container in `/etc/bma-simulator.env` den Wert `COOKIE_SECURE=true` setzen und
   `systemctl restart bma-simulator` ausführen. Bis dahin läuft die Anmeldung unverschlüsselt im internen Netz.

### Aktualisieren

```bash
pct exec <CTID> -- /usr/local/bin/bma-simulator-update
```

### Wo liegt was im Container?

| Pfad | Inhalt |
|---|---|
| `/opt/bma-simulator` | Programm |
| `/var/lib/bma-simulator/simulator.db` | Datenbank (Objekte, Melder, Benutzer, Protokolle) |
| `/etc/bma-simulator.env` | Einstellungen und `SECRET_KEY` |
| `/var/lib/bma-simulator/backups` | Sicherungen (automatisch und per Knopf) |
| `/root/bma-simulator-zugang.txt` | Startpasswort (nach der ersten Anmeldung löschen) |
| `journalctl -u bma-simulator` | Dienstprotokoll |

### Sicherung und Wiederherstellung

Unter **Sicherung** lässt sich die ganze Datenbank (Objekte, Melderlisten, Benutzer, Rechte, Protokolle) als ZIP
herunterladen oder auf dem Server ablegen. Zusätzlich legt der Simulator alle 24 Stunden selbst eine Sicherung ab und
behält die neuesten 14 (`BACKUP_HOURS`, `BACKUP_KEEP` in `/etc/bma-simulator.env`; `BACKUP_HOURS=0` schaltet die Automatik ab).
Der `SECRET_KEY` wird für die Wiederherstellung nicht gebraucht. Wiederherstellen:

```bash
pct push <CTID> sicherung.zip /root/sicherung.zip
pct exec <CTID> -- systemctl stop bma-simulator
pct exec <CTID> -- python3 -m zipfile -e /root/sicherung.zip /root/sicherung
pct exec <CTID> -- bash -c 'rm -f /var/lib/bma-simulator/simulator.db-wal /var/lib/bma-simulator/simulator.db-shm'
pct exec <CTID> -- install -o bma-sim -g bma-sim -m 600 /root/sicherung/simulator.db /var/lib/bma-simulator/simulator.db
pct exec <CTID> -- systemctl start bma-simulator
```

Dasselbe Installationsskript läuft auch auf jeder Debian- oder Ubuntu-Maschine ohne Proxmox:

```bash
curl -fsSL https://raw.githubusercontent.com/yodaeichen/bma-simulator/main/scripts/setup.sh | bash
```

## Installation mit Docker

```bash
cp .env.example .env
# SECRET_KEY (openssl rand -base64 48) und ADMIN_PASSWORD eintragen
mkdir -p data && sudo chown 10001 data
docker compose up -d --build
```

Die Anwendung lauscht danach auf `127.0.0.1:8080`. Ohne HTTPS funktioniert die Anmeldung nicht, solange
`COOKIE_SECURE=true` gesetzt ist.

## Erste Schritte

1. Anmelden. Beim ersten Start sind vier Beispielobjekte angelegt (abschaltbar mit `BEISPIELE=false`).
2. Bei einem Objekt „Übung öffnen".
3. Auf dem Gerät der Übenden den QR-Code scannen, „FAT und FBF" wählen und „Ton ein" drücken.
4. Einen Melder anklicken.

## Melderliste als CSV

Je Zeile ein Melder; Trennzeichen Semikolon, Komma oder Tabulator, die Kopfzeile ist freiwillig:

```
Gruppe;Melder;Typ;Etage;Gruppenname;Ort
1;1;hfm;EG;Haupteingang;Windfang
2;1;rm;EG;Foyer;Foyer Mitte
```

| Typ | Bedeutung | | Typ | Bedeutung |
|---|---|---|---|---|
| `rm` | Rauchmelder | | `lm` | Linearer Rauchmelder |
| `wm` | Wärmemelder | | `ras` | Rauchansaugsystem |
| `mm` | Mehrkriterienmelder | | `hfm` | Handfeuermelder |
| `fm` | Flammenmelder | | `spr` | Sprinklergruppe |
| `gm` | Gasmelder | | | |

Das FAT zeigt vom Ort die ersten 20 Zeichen. Enthält eine Zeile einen Fehler, wird nichts übernommen.

## Dank

Aufbau von FAT und FBF, Anzeigetest, Historie, die Sperre der Brandfallsteuerungen und die Töne (Summer, Hausalarm)
folgen dem BMA-Simulator [safetydaysBMA](https://github.com/safetydays/safetydaysBMA), entwickelt bei den safety days 2019
in Zusammenarbeit mit dem Institut der Feuerwehr NRW. Die beiden Töne stehen unter der MIT-Lizenz, der Hinweis liegt in
`app/static/ton/LIZENZ.txt`.

## Entwicklung

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt httpx
.venv/bin/python tests/smoke_test.py
SECRET_KEY=$(openssl rand -hex 32) ADMIN_PASSWORD=ein-langes-passwort COOKIE_SECURE=false DATA_DIR=./data \
  .venv/bin/uvicorn app.main:app --reload
```

Der Dienst läuft bewusst als ein einzelner Prozess; die Anzeigen fragen den Zustand im Sekundentakt ab.

## Lizenz

Der Code steht unter der [MIT-Lizenz](LICENSE): Jeder darf ihn verwenden, ändern und weitergeben, auch in eigenen
Fassungen, solange der Lizenzhinweis erhalten bleibt.

**Ausgenommen** sind das Logo und die Bilder in `app/static/icons/`, `app/static/img/feuer.webp` und
`app/static/img/atemschutz.svg`. Alle Rechte daran liegen bei yodaeichen; wer den Simulator weitergibt oder eine eigene
Fassung betreibt, ersetzt sie durch eigene.

Die Töne in `app/static/ton/` stammen aus safetydaysBMA und stehen unter deren MIT-Lizenz (siehe Abschnitt „Dank“).
