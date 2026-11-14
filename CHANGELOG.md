# Änderungen

Die Versionsnummer steht in `app/version.py` und wird unten auf jeder Seite des Simulators angezeigt.

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
