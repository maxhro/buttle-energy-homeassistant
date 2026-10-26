# Powermesh Energie – Home Assistant Integration (Prototyp)

Verbindet Home Assistant mit [powermesh.de](https://powermesh.de).

> **Status: Prototyp.** Die Integration und powermesh.de befinden sich in Entwicklung.
> Sie ist nicht offiziell Teil von Home Assistant oder HACS.

## Wozu?

Ziel von Powermesh ist nicht, deinen eigenen Verbrauch zu protokollieren – das kann
Home Assistant selbst. Powermesh soll Smarthomes miteinander vergleichbar machen und
daraus Verbesserungspotenziale ableiten: Wo liegt dein Haushalt im Vergleich zu
ähnlichen Haushalten, und wo lohnt sich ein genauerer Blick?

Dieser Vergleich befindet sich in Entwicklung; derzeit werden die Messwerte nur
gespeichert. Vergleiche werden nur aus zusammengefassten Daten vieler Haushalte
gebildet – andere Nutzer sehen nie deine Einzelwerte.

## Deine Daten

- Übertragen werden nur Sensor-Kennung, Zeitpunkt und Messwert mit Einheit der
  von dir ausgewählten Energie- und Leistungssensoren – keine Namen, Adressen
  oder Geräteinformationen.
- Die Daten sind pseudonym deinem powermesh.de-Konto zugeordnet, werden
  verschlüsselt übertragen, nicht verkauft und nicht an Dritte weitergegeben.
- Übertragen wird nur nach deiner Einwilligung auf powermesh.de.
- Du kannst alle Messwerte jederzeit selbst auf powermesh.de löschen oder die
  Einwilligung widerrufen; dabei werden alle Messwerte gelöscht.

## Installation über HACS

[![In HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=maxhro&repository=powermesh-energy-homeassistant&category=integration)

Der Button öffnet das Repository direkt in deinem HACS. Alternativ von Hand:

1. HACS öffnen → Menü (⋮) → **Benutzerdefinierte Repositories**
2. Repository `https://github.com/maxhro/powermesh-energy-homeassistant`,
   Typ **Integration** → Hinzufügen
3. „Powermesh Energie“ herunterladen und Home Assistant neu starten
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Powermesh Energie**

Voraussetzung für diesen neu gestarteten Prototyp: Home Assistant 2026.10.4
(getesteter Stand) oder neuer und ein Konto auf powermesh.de.
Das Integrations-Icon zeigt Home Assistant ab Version 2026.3 an.

## Einrichtung

1. Auf powermesh.de anmelden und unter **Mein Bereich → Home Assistant** die
   Einwilligung erteilen und einen persönlichen MQTT-Zugang erstellen. Eine Anleitung
   findest du nach der Anmeldung unter **Hilfe & Wissen → Home Assistant einrichten**.
2. In Home Assistant die im Konto angezeigten Broker-Einstellungen und persönlichen
   Zugangsdaten eintragen. Die Verbindung ist TLS-gesichert und unabhängig von
   deinem bereits eingerichteten lokalen MQTT-Broker.
   **Neustart als Prototyp 0.1.0:** Die bisherige HTTP-Integration wird nicht
   automatisch migriert. Vor dem ausdrücklichen Entfernen alter Einträge lokale
   Puffer bei Bedarf sichern; das Entfernen löscht sie. Anschließend 0.1.0 aus dem
   freigegebenen Teststand manuell installieren und neu einrichten. HACS behandelt
   0.1.0 nach 1.0.0 nicht als normales Update. Alte Releases werden nicht überschrieben.
   Prüfe danach Automationen und Dashboards. Alte Zugänge sind nicht übertragbar.
3. Die Integration schlägt anhand deines **Energie-Dashboards** passende Sensoren
   vor (Netz, Solar, Batterie, Geräte). Du kannst die Auswahl anpassen und später
   über **Konfigurieren** ändern oder auf den Vorschlag zurücksetzen.
4. Im nächsten Schritt legst du je Sensor eine **Glättung** fest – ähnlich dem
   Filter-Helfer von Home Assistant: zeitgewichteter Mittelwert oder Drosselung
   über 10 Sekunden bis 1 Stunde, oder keine Glättung. Standard ist ein
   **1-Minuten-Mittelwert**; so wird höchstens ein Wert pro Minute und Sensor
   übertragen. Die gewählte Glättung wird mit jedem Wert übermittelt.

Die Integration sendet gesammelt in regelmäßigen Abständen und puffert bei
Verbindungsproblemen lokal. Werte werden erst nach bestätigter Speicherung aus
dem Puffer entfernt. Bei einem Zugangswechsel werden alte Puffer nicht stillschweigend
neu zugeordnet. Der lokale Puffer ist begrenzt; bei Überlauf werden die ältesten
noch nicht gesendeten Werte verworfen und der Verlust sichtbar gezählt/protokolliert.
Eine Broker-Verbindung allein bestätigt noch keine Speicherung.
Status, ausstehende Werte und letzte Übertragung
siehst du an den Diagnose-Sensoren. Ist ein Update der Integration nötig,
erscheint eine Reparaturmeldung in Home Assistant.

## Versionen

Für die vollständige Neuinstallation starten Webanwendung, Schnittstelle und
Integration gemeinsam bei **0.1.0**. Danach bleiben ihre Versionszyklen unabhängig.
Bestehende Git-Tags und Releases werden nicht überschrieben. Alte Einträge und
lokale Puffer werden von den Paket-Skripten weder migriert noch gelöscht.

Die Integration wird unabhängig von der Webanwendung und der Schnittstelle von powermesh.de
versioniert. Nur bei Änderungen der Schnittstellenfunktionen wird die API-Version erhöht.
Bitte halte die Integration über HACS aktuell; veraltete Versionen werden vom Server
abgelehnt, falls eine neuere Mindestversion vorausgesetzt wird.

## Lokale Tests

### Installationspaket (macOS und Windows)

Mit **PowerShell 7** lässt sich ohne Verbindung zu Home Assistant ein Paket bauen:

```powershell
pwsh -NoProfile -File ./build-package.ps1 -DryRun
pwsh -NoProfile -File ./build-package.ps1 -BuildPackage
```

Das Archiv `dist/powermesh-energy-homeassistant-0.1.0.zip` enthält
`custom_components/powermesh_energy` und die Lizenz, keine Testumgebung, Caches
oder Zugangsdaten. Vorhandene Archive werden nicht überschrieben.
Den enthaltenen Komponentenordner in das Konfigurationsverzeichnis von
Home Assistant entpacken und Home Assistant neu starten. Die Skripte installieren
nichts automatisch und veröffentlichen kein HACS-Release.

Die PowerShell-Paketprüfung läuft mit `node --test tests/package.test.mjs`
(Node wird nur für diese lokale Paketprüfung benötigt).

Mit einer separaten Python-Testumgebung: `pip install -r requirements_test.txt`,
danach `pytest -q` und `python -m compileall -q custom_components`.
Tests verwenden synthetische Daten und ersetzen den Netzwerktransport.
Die optionale, ausdrücklich aktivierte lokale Integrationstest-Strecke ist
im privaten Dienst-Repository beschrieben; sie kontaktiert keine Produktivsysteme.

## Lizenz

Der Quellcode dieser Integration steht unter der [MIT-Lizenz](LICENSE).
Die Schnittstelle und die Dienste von powermesh.de sind nicht Gegenstand dieser
Lizenz; es werden daran keine Rechte eingeräumt. Ihre Nutzung richtet sich nach
den [Nutzungsbedingungen von powermesh.de](https://powermesh.de/?r=terms) und setzt
einen persönlichen Zugang voraus.

---

**English:** Prototype Home Assistant integration for powermesh.de, installable as a
HACS custom repository. Powermesh aims to compare smart homes with each other (in
aggregate) to identify improvement potential – this comparison is in development.
Selected energy and power sensors (pre-selected from the Energy dashboard,
adjustable, smoothed per sensor – default: 1-minute time-weighted mean) are
transferred pseudonymously after consent on powermesh.de; users can
delete their data at any time. Code: MIT. The powermesh.de interface and services are
not covered by this license.
