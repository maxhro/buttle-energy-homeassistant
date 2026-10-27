# Powermesh Energie – Home Assistant Integration (Prototyp)

Verbindet Home Assistant mit [powermesh.de](https://powermesh.de).

> **Status: Prototyp.** Die Integration und powermesh.de befinden sich in Entwicklung.
> Sie ist nicht offiziell Teil von Home Assistant oder HACS.

## Wozu?

Ein Vergleich von Smarthomes und die Ableitung von Verbesserungspotenzial befinden
sich in Entwicklung und sind nicht implementiert. Derzeit speichert Powermesh
ausschließlich die von dir freigegebenen Sensorwerte; es gibt keine Auswertung oder
Anzeige der Messwerte.

## Deine Daten

Übertragen werden Sensor-Kennung, Zeitpunkt, Zahlenwert und Einheit. Zusätzlich
können Home-Assistant-Metadaten wie Anzeigename, Geräte- und Zustandsklasse, Bereich,
Etage, Labels und Gerätekennung gespeichert werden. Diese Angaben können Rückschlüsse
auf deinen Haushalt ermöglichen.

Die Messwerte und Metadaten werden pseudonym deinem Benutzerkonto zugeordnet und bis
zum Ende der Aufbewahrungsfrist gespeichert. Sie werden nicht verkauft oder an Dritte
weitergegeben. Du kannst deine Einwilligung jederzeit widerrufen; dann werden alle
API-Schlüssel gesperrt und alle gespeicherten Messwerte einschließlich Metadaten
gelöscht.

Bei einer Registrierung aus Home Assistant werden E-Mail-Adresse, Passwort und
Einladungscode nur für das Anlegen des Kontos an powermesh.de übermittelt und
nicht in Home Assistant gespeichert. Gespeichert wird lokal der persönliche
API-Schlüssel, wie bei der Einrichtung mit einem vorhandenen Schlüssel.

## Installation über HACS

[![In HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=maxhro&repository=powermesh-energy-homeassistant&category=integration)

Der Button öffnet das Repository direkt in deinem HACS. Alternativ von Hand:

1. HACS öffnen → Menü (⋮) → **Benutzerdefinierte Repositories**
2. Repository `https://github.com/maxhro/powermesh-energy-homeassistant`,
   Typ **Integration** → Hinzufügen
3. „Powermesh Energie“ herunterladen und Home Assistant neu starten
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Powermesh Energie**

Voraussetzung: Home Assistant 2026.10.4
(getesteter Stand) oder neuer und entweder ein Konto auf powermesh.de mit
persönlichem API-Schlüssel oder ein Einladungscode für ein neues Konto.
Das Integrations-Icon zeigt Home Assistant ab Version 2026.3 an.

## Einrichtung

Beim Hinzufügen der Integration wählst du einen von zwei Wegen. Andere
Home-Assistant-Integrationen und lokale Broker-Einstellungen werden davon nicht
geändert. Für beide Wege gelten die
[Nutzungsbedingungen von powermesh.de](https://powermesh.de/?r=terms).

### Vorhandenen API-Schlüssel verwenden

1. Auf powermesh.de anmelden, die Informationen zur Speicherung prüfen, die
   Einwilligung erteilen und einen persönlichen API-Schlüssel erstellen.
2. In Home Assistant **Vorhandenen API-Schlüssel verwenden** wählen und den
   Schlüssel eintragen.
3. Sensoren und Glättung wie unten beschrieben auswählen.

### Neues Konto mit Einladungscode anlegen

Für ein neues Konto direkt aus Home Assistant benötigst du einen Einladungscode,
den dir der Betreiber von powermesh.de persönlich zur Verfügung stellt. Der Code
ist 24 Stunden gültig und erlaubt genau eine Registrierung, auch wenn das Konto
später gelöscht oder Home Assistant neu eingerichtet wird. Er ist eine
Berechtigung zur Registrierung, kein Nachweis für eine bestimmte Installation.
Für eine E-Mail-Adresse mit bestehendem Konto ist dieser Weg nicht möglich;
verwende dann einen API-Schlüssel.

1. **Neues Konto mit Einladungscode anlegen** wählen und die Datenschutzhinweise,
   die Nutzungsbedingungen sowie die Einwilligung zur Speicherung der Messwerte
   jeweils einzeln bestätigen.
2. Sensoren und Glättung auswählen (siehe unten). Erst danach wird registriert.
3. E-Mail-Adresse, Passwort und Einladungscode eingeben. Die Angaben werden einmal
   verschlüsselt an powermesh.de gesendet. Home Assistant speichert anschließend nur
   den ausgegebenen persönlichen API-Schlüssel – nicht E-Mail-Adresse, Passwort
   oder Einladungscode. Die Registrierung wird nie automatisch wiederholt.
4. Die Integration startet sofort. Gleichzeitig erscheinen ein Hinweis und eine
   Reparaturmeldung mit der Frist für die Kontoeinrichtung.
5. Innerhalb von **168 Stunden (7 Tagen)** nach der Registrierung auf powermesh.de
   mit E-Mail-Adresse und Passwort anmelden (beim ersten Besuch ohne
   Authenticator-Code), den Bestätigungslink per E-Mail anfordern, ihn bestätigen
   und danach den Authenticator einrichten. Die Reparaturmeldung verschwindet erst,
   wenn powermesh.de den Abschluss bestätigt.

Wird die Einrichtung nicht rechtzeitig abgeschlossen, sperrt powermesh.de das
Konto zur Frist. Die automatische Löschung erfolgt erst durch einen eingerichteten
Bereinigungslauf; ein solcher Lauf ist für den Produktivbetrieb derzeit nicht
eingerichtet. Eine automatische Kontolöschung ist daher nicht garantiert.
Home Assistant zeigt die Sperre als Fehlermeldung an und legt weder ein neues
Konto noch einen neuen Schlüssel automatisch an. Ausstehende Messwerte bleiben
lokal, bis du den Eintrag entfernst.

Liefert powermesh.de nach der Registrierung zwar einen API-Schlüssel, aber keinen
gültigen Kontostatus, wird der Schlüssel trotzdem gespeichert und ein
Protokollfehler mit unbekannter Frist gemeldet. Schließe die Einrichtung dann so
bald wie möglich ab; die Meldung verschwindet, sobald powermesh.de den
Kontostatus meldet.

Bleibt das Ergebnis der Registrierung unklar (zum Beispiel bei einem
Verbindungsabbruch), wurde das Konto möglicherweise trotzdem angelegt und der
Einladungscode verbraucht. Melde dich dann auf powermesh.de an; gelingt das,
schließe die Einrichtung ab, erstelle einen API-Schlüssel und verwende ihn.
Andernfalls fordere beim Betreiber einen neuen Code an.

### Sensoren und Glättung

1. Die Integration schlägt anhand deines **Energie-Dashboards** Sensoren vor. Das ist
   nur eine Orientierung: Du kannst jeden numerischen Sensor auswählen, auch
   Temperatur-Sensoren. Die Auswahl lässt sich später über **Konfigurieren** ändern
   oder auf den Vorschlag zurücksetzen.
2. Im nächsten Schritt legst du je Sensor eine **Glättung** fest – ähnlich dem
   Filter-Helfer von Home Assistant: zeitgewichteter Mittelwert oder Drosselung
   über 10 Sekunden bis 1 Stunde, oder keine Glättung. Standard ist ein
   **1-Minuten-Mittelwert**; dadurch entstehen weniger übertragene Werte.

Die Integration sendet gesammelt in regelmäßigen Abständen und puffert bei
Verbindungsproblemen lokal. Werte werden erst nach einer ausdrücklichen
Speicherbestätigung aus dem Puffer entfernt. Bei einem Schlüsselwechsel werden
ausstehende Werte nicht stillschweigend neu zugeordnet. Der lokale Puffer ist begrenzt; bei
Überlauf werden die ältesten noch nicht gesendeten Werte verworfen und der Verlust
sichtbar gezählt/protokolliert.
Status, ausstehende Werte und letzte Übertragung
siehst du an den Diagnose-Sensoren. Ist ein Update der Integration nötig,
erscheint eine Reparaturmeldung in Home Assistant.

Für Updates über HACS öffne **HACS → Integrationen → Powermesh Energie**,
installiere die angebotene neue Version und starte Home Assistant danach neu.

## Versionen

Diese Integration ist ein Entwicklungsstand in Version **0.5.0**. Sie wird
unabhängig von der Website und dem Dienst versioniert. Vergleiche und Auswertungen
sind nicht implementiert. Halte die Integration über HACS aktuell.

## Lokale Tests

### Installationspaket (macOS und Windows)

Mit **PowerShell 7** lässt sich ohne Verbindung zu Home Assistant ein Paket bauen:

```powershell
pwsh -NoProfile -File ./build-package.ps1 -DryRun
pwsh -NoProfile -File ./build-package.ps1 -BuildPackage
```

Das Archiv `dist/powermesh-energy-homeassistant-0.5.0.zip` enthält
`custom_components/powermesh_energy` und die Lizenz, keine Testumgebung, Caches
oder Zugangsdaten. Vorhandene Archive werden nicht überschrieben.
Den enthaltenen Komponentenordner in das Konfigurationsverzeichnis von
Home Assistant entpacken und Home Assistant neu starten. Die Skripte installieren
nichts automatisch und veröffentlichen kein HACS-Release.

Die PowerShell-Paketprüfung läuft mit `node --test tests/package.test.mjs`
(Node wird nur für diese lokale Paketprüfung benötigt).

Mit einer separaten Python-Testumgebung: `pip install -r requirements_test.txt`,
danach `pytest -q` und `python -m compileall -q custom_components`.
Tests verwenden synthetische Daten und ersetzen den Netzwerktransport; sie kontaktieren
keine Produktivsysteme.

## Lizenz

Der Quellcode dieser Integration steht unter der [MIT-Lizenz](LICENSE).
Die Schnittstelle und die Dienste von powermesh.de sind nicht Gegenstand dieser
Lizenz; es werden daran keine Rechte eingeräumt. Ihre Nutzung richtet sich nach
den [Nutzungsbedingungen von powermesh.de](https://powermesh.de/?r=terms) und setzt
einen persönlichen Zugang voraus.

---

**English:** Prototype Home Assistant integration for powermesh.de. Smart-home
comparison and improvement analysis are in development and not implemented. The
service currently stores only selected sensor readings. Readings and optional
Home Assistant metadata are pseudonymously associated with the account; see the
German privacy description above. Setup works with an existing personal API key
or, with a single-use operator invitation, by creating a new account whose email
confirmation and authenticator setup must be completed on powermesh.de within
168 hours; otherwise the account and all its data are deleted. The powermesh.de
terms of use apply. Code: MIT. The service is not covered by this
license.
