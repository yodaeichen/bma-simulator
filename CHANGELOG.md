# Änderungen

Die Versionsnummer steht in `app/version.py` und wird unten auf jeder Seite des Simulators angezeigt.

## 1.4.1

- **Fester Rahmen:** Die Kopfzeile bleibt oben, Flammen und Fußzeile mit der Versionsnummer bleiben unten am
  Fensterrand stehen, der Inhalt läuft dazwischen. Die Fußzeile ist damit auf jeder Seite ohne Scrollen zu sehen
- Die Höhe der Flammen richtet sich nach der Fensterhöhe; auf dem Handy sind sie flacher und die Kopfzeile läuft mit
  dem Inhalt mit, damit mehr Platz bleibt. Bei sehr niedrigen Fenstern (Handy quer) steht der Fuß am Seitenende
- Alle Seiten haben dieselbe Inhaltsbreite (bis 1400 Pixel)

## 1.4.0

- **Neues Logo:** App-Symbol mit Feuerhintergrund, Atemschutzträger und dem Kürzel „BMA"; es erscheint auf dem
  Startbildschirm, im Browser-Tab, in der Kopfzeile und auf der Anmeldeseite
- **Neues Erscheinungsbild** der Ausbilderansicht und der Verwaltung: Flammen und Atemschutzträger als Seitenfuß,
  dazu passende Farben (dunkle Kopfzeile mit orangefarbener Linie, warmer heller Grund, dunkle Schaltflächen,
  Links in Glutorange). Alarmrot bleibt den Alarmen vorbehalten
- Die Anzeigen der Übenden (FAT, FBF, BMZ, Laufkarten) bleiben unverändert: Sie bilden die Geräte nach
- Kurze Seiten füllen jetzt das ganze Fenster, der Seitenfuß steht immer unten
- Wer die App schon installiert hat, bekommt das neue Symbol je nach Gerät erst nach erneutem Installieren

## 1.3.0

- **Als App auf Handy und Tablet:** Der Simulator lässt sich auf Android, iPhone, iPad und am Rechner installieren
  (eigenes Symbol, eigenes Fenster, ohne App Store). Die Anleitung für das jeweilige Gerät steht unter „Mein Konto"
- **Eigene App für die Geräte der Übenden:** Von der Auswahlseite der Anzeigen aus installiert, heißt die App wie das
  Objekt, startet ohne Anmeldung direkt bei FAT, BMZ und Laufkarten und läuft im Vollbild
- Auf den Anzeigen bleibt der Bildschirm an, solange sie offen sind; dazu ein Knopf „Vollbild" in der Leiste
- Ausbilderansicht und Verwaltung für das Handy überarbeitet: Menü als Leiste zum Wischen, Melder als große
  Schaltflächen in zwei Spalten, größere Eingabefelder, breite Tabellen lassen sich seitlich schieben
- Hinweisseite „Simulator nicht erreichbar", wenn die App den Server nicht erreicht (z. B. WLAN oder VPN nicht verbunden)

## 1.2.0

- **Feuerwehr-Laufkarten** je Meldergruppe: Vorderseite mit dem Laufweg von der FIZ durch deren Etage, Rückseite mit der Etage
  der Gruppe und der Lage ihrer Melder; dazu Laufweg in Worten, Besonderheiten und Zeichenerklärung
- Ausdruck aller Karten oder einer einzelnen im Querformat A4 (je Seite der Karte ein Blatt, für beidseitigen Druck)
- Die Übenden öffnen die Laufkarten auf Tablet oder Beamer unter „Laufkarten", nach Nummern geordnet wie im Laufkartendepot;
  das Live-Bild zeigt, welche Karte gerade offen ist
- Pläne je Etage: eigenes Bild hochladen (PNG, JPG, WebP, SVG bis 4 MB) oder einen Schemaplan erzeugen lassen, den der Simulator
  aus der Melderliste zeichnet und in den er Melder, FIZ und Laufwege einträgt
- Laufkarte bearbeiten: Standort der FIZ, Laufwege und Melder durch Klicken in den Plan setzen
- Die Beispielobjekte bekommen beim ersten Start Schemapläne; bei vorhandenen Objekten genügt „Schemapläne erzeugen"
- Pläne liegen in der Datenbank und sind damit Teil der Sicherung; „Objekt kopieren" nimmt Pläne und Laufkarten mit

## 1.1.0

- **Live-Bild der Übenden** in der Ausbilderansicht: je geöffneter Anzeige eine kleine Kachel mit dem Text, den FAT oder BMZ
  gerade zeigt, der Anzeigeebene, dem Schloss (FBF aufgeschlossen, Bedienung frei), „Ton an/aus" und der zuletzt gedrückten Taste;
  auch Geräte, die das Meldergruppenverzeichnis lesen, erscheinen dort
- **Benutzer und Rechte** wie im DIVERA Gateway: Einzelrechte je Bereich (Objekte, Übungen, Protokoll, Benutzer), die Rollen
  Administrator, Ausbilder und Beobachter als Vorlage, Beschränkung auf einzelne Objekte
- Benutzer ohne Passwort anlegen: Der Simulator erzeugt einen Einmal-Link (48 Stunden gültig), über den der Benutzer sein
  Passwort selbst festlegt; derselbe Weg hilft bei vergessenem Passwort
- Die Benutzerliste zeigt, wer gerade angemeldet aktiv ist
- Neue Seite **Sicherung** (nur mit dem Recht „Benutzer, Rechte und Sicherung"): die ganze Datenbank als ZIP herunterladen oder
  per Knopf auf dem Server ablegen
- Automatische Sicherung alle 24 Stunden nach `/var/lib/bma-simulator/backups`, die neuesten 14 bleiben erhalten
  (einstellbar über `BACKUP_HOURS` und `BACKUP_KEEP`); jede Sicherung enthält eine LIESMICH.txt mit den Schritten zur Wiederherstellung
- Bestehende Konten behalten ihre Rolle: Administratoren bleiben Administratoren, alle anderen werden Ausbilder mit Zugriff auf alle Objekte

## 1.0.0

Neuaufbau als Serveranwendung. Die frühere Fassung war eine einzelne HTML-Datei, in der Ausbilderansicht und Anzeigen
im selben Browserfenster liefen.

- Ausbilderansicht und Anzeigen laufen auf getrennten Geräten und bleiben über den Server im Gleichstand
- Anzeigen für die Übenden ohne Anmeldung über eine geheime Adresse, mit QR-Code: FAT mit FBF, BMZ, Meldergruppenverzeichnis
- FAT und FBF in Aufbau und Beschriftung an DIN 14662 und DIN 14661 angelehnt, ohne Herstellerbezug
- Anlagenverhalten: ÜE, akustische Signale, Brandfallsteuerungen, Löschanlage, Summer, Rückstellen
- Objekte, Etagen, Meldergruppen und Melder frei anlegbar; Melderliste als CSV einlesen und herunterladen; Objekte kopieren
- Auslösen mit Verzögerung, Brandausbreitung und anstehender Ursache (Melder löst nach dem Rückstellen erneut aus)
- Störungen und Abschaltungen von Meldern und Gruppen
- Übungsprotokoll je Objekt mit Download als CSV
- Anmeldung mit lokalen Benutzern, Rollen Administrator und Ausbilder
- Installation per Einzeiler auf Proxmox, per Skript auf Debian und Ubuntu oder mit Docker
