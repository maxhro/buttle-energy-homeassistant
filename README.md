# Buttle Energie – Home Assistant Integration (Prototyp)

Verbindet Home Assistant mit [buttle.de](https://buttle.de).

> **Status: Prototyp.** Die Integration und buttle.de befinden sich in Entwicklung.
> Sie ist nicht offiziell Teil von Home Assistant oder HACS.

## Wozu?

Ziel von Buttle ist nicht, deinen eigenen Verbrauch zu protokollieren – das kann
Home Assistant selbst. Buttle soll Smarthomes miteinander vergleichbar machen und
daraus Verbesserungspotenziale ableiten: Wo liegt dein Haushalt im Vergleich zu
ähnlichen Haushalten, und wo lohnt sich ein genauerer Blick?

Dieser Vergleich befindet sich in Entwicklung; derzeit werden die Messwerte nur
gespeichert. Vergleiche werden nur aus zusammengefassten Daten vieler Haushalte
gebildet – andere Nutzer sehen nie deine Einzelwerte.

## Deine Daten

- Übertragen werden nur Sensor-Kennung, Zeitpunkt und Messwert mit Einheit der
  von dir ausgewählten Energie- und Leistungssensoren – keine Namen, Adressen
  oder Geräteinformationen.
- Die Daten sind pseudonym deinem buttle.de-Konto zugeordnet, werden
  verschlüsselt übertragen, nicht verkauft und nicht an Dritte weitergegeben.
- Übertragen wird nur nach deiner Einwilligung auf buttle.de.
- Du kannst alle Messwerte jederzeit selbst auf buttle.de löschen oder die
  Einwilligung widerrufen; dabei werden alle Messwerte gelöscht.

## Installation über HACS

[![In HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=maxhro&repository=buttle-energy-homeassistant&category=integration)

Der Button öffnet das Repository direkt in deinem HACS. Alternativ von Hand:

1. HACS öffnen → Menü (⋮) → **Benutzerdefinierte Repositories**
2. Repository `https://github.com/maxhro/buttle-energy-homeassistant`,
   Typ **Integration** → Hinzufügen
3. „Buttle Energie“ herunterladen und Home Assistant neu starten
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Buttle Energie**

Voraussetzung: Home Assistant 2024.11 oder neuer und ein Konto auf buttle.de.
Das Integrations-Icon zeigt Home Assistant ab Version 2026.3 an.

## Einrichtung

1. Auf buttle.de anmelden und unter **Mein Bereich → Home Assistant** die
   Einwilligung erteilen und einen Zugangsschlüssel erstellen. Eine Anleitung
   findest du nach der Anmeldung unter **Hilfe & Wissen → Home Assistant einrichten**.
2. In Home Assistant den Zugangsschlüssel eintragen.
3. Die Integration schlägt anhand deines **Energie-Dashboards** passende Sensoren
   vor (Netz, Solar, Batterie, Geräte). Du kannst die Auswahl anpassen und später
   über **Konfigurieren** ändern oder auf den Vorschlag zurücksetzen.

Die Integration sendet gesammelt in regelmäßigen Abständen und puffert bei
Verbindungsproblemen lokal. Status, ausstehende Werte und letzte Übertragung
siehst du an den Diagnose-Sensoren. Ist ein Update der Integration nötig,
erscheint eine Reparaturmeldung in Home Assistant.

## Versionen

Die Integration wird unabhängig von der Webanwendung und der Schnittstelle von buttle.de
versioniert. Nur bei Änderungen der Schnittstellenfunktionen wird die API-Version erhöht.
Bitte halte die Integration über HACS aktuell; veraltete Versionen werden vom Server
abgelehnt, falls eine neuere Mindestversion vorausgesetzt wird.

## Lizenz

Der Quellcode dieser Integration steht unter der [MIT-Lizenz](LICENSE).
Die Schnittstelle und die Dienste von buttle.de sind nicht Gegenstand dieser
Lizenz; es werden daran keine Rechte eingeräumt. Ihre Nutzung richtet sich nach
den [Nutzungsbedingungen von buttle.de](https://buttle.de/?r=terms) und setzt
einen persönlichen Zugang voraus.

---

**English:** Prototype Home Assistant integration for buttle.de, installable as a
HACS custom repository. Buttle aims to compare smart homes with each other (in
aggregate) to identify improvement potential – this comparison is in development.
Selected energy and power sensors (pre-selected from the Energy dashboard,
adjustable) are transferred pseudonymously after consent on buttle.de; users can
delete their data at any time. Code: MIT. The buttle.de interface and services are
not covered by this license.
