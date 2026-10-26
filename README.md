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

1. Auf powermesh.de anmelden, die Informationen zur Speicherung prüfen und die
   Einwilligung erteilen. Für die Nutzung muss ein passender persönlicher API-Schlüssel
   und ein verfügbarer Dienst bereitgestellt sein.
2. In Home Assistant die Integration hinzufügen und den persönlichen API-Schlüssel
   eintragen. Andere Home-Assistant-Integrationen und lokale Broker-Einstellungen
   werden davon nicht geändert.
   Ältere Einträge und lokal gepufferte Daten werden nicht automatisch umgewandelt;
   sichere benötigte lokale Daten, bevor du einen alten Eintrag ausdrücklich entfernst.
3. Die Integration schlägt anhand deines **Energie-Dashboards** Sensoren vor. Das ist
   nur eine Orientierung: Du kannst jeden numerischen Sensor auswählen, auch
   Temperatur-Sensoren. Die Auswahl lässt sich später über **Konfigurieren** ändern
   oder auf den Vorschlag zurücksetzen.
4. Im nächsten Schritt legst du je Sensor eine **Glättung** fest – ähnlich dem
   Filter-Helfer von Home Assistant: zeitgewichteter Mittelwert oder Drosselung
   über 10 Sekunden bis 1 Stunde, oder keine Glättung. Standard ist ein
   **1-Minuten-Mittelwert**; dadurch entstehen weniger übertragene Werte.

Die Integration sendet gesammelt in regelmäßigen Abständen und puffert bei
Verbindungsproblemen lokal. Werte werden erst nach einer ausdrücklichen
Speicherbestätigung aus dem Puffer entfernt. Bei einem Schlüsselwechsel werden alte
Puffer nicht stillschweigend neu zugeordnet. Der lokale Puffer ist begrenzt; bei
Überlauf werden die ältesten noch nicht gesendeten Werte verworfen und der Verlust
sichtbar gezählt/protokolliert.
Status, ausstehende Werte und letzte Übertragung
siehst du an den Diagnose-Sensoren. Ist ein Update der Integration nötig,
erscheint eine Reparaturmeldung in Home Assistant.

## Versionen

Diese Integration ist ein Entwicklungsstand in Version **0.1.0**. Sie wird
unabhängig von der Website und dem Dienst versioniert. Vergleiche und Auswertungen
sind nicht implementiert. Halte die Integration über HACS aktuell.

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
German privacy description above. Code: MIT. The service is not covered by this
license.
