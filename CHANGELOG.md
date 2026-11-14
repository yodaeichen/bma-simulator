# Änderungen

Die Versionsnummer steht in `app/version.py` und wird unten auf jeder Seite des Simulators angezeigt.

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
