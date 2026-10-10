# Jira in MICA

Stand: **11.10.2026**. Weitere Jira-Arbeit und die Verbindung mit einem echten
Konto sind bis zum Nachmittag zurückgestellt. Die bereits implementierte
Anbindung bleibt erhalten; diese Anleitung beschreibt ihren aktuellen Umfang.

Im Bereich **Betrieb → Jira** (Seite „MICA im Alltag“) kannst du dein Atlassian-Konto verbinden,
Websites auswählen, deine offenen Vorgänge suchen und einzelne Vorgänge lesen.
Die Abfragen starten auf Klick und laufen im Hintergrund, ohne die Oberfläche zu blockieren.

1. Erstelle im Atlassian-Konto einen eingeschränkten API-Token mit den für Jira
   erforderlichen Scopes `read:jira:agent-interface` und `search:jira:agent-interface`.
2. Deine Organisation muss die Token-Authentifizierung für Atlassian MCP erlauben.
3. Gib deine Atlassian-E-Mail und den Token ein und klicke **Zugang speichern und verbinden**.
4. Wähle eine freigegebene Website. Die voreingestellte Suche zeigt deine offenen
   Vorgänge; alternativ gib einen JQL-Ausdruck oder eine Vorgangsnummer ein.

Zugangsdaten werden ausschließlich im Windows Credential Manager gespeichert.
MICA nutzt den offiziellen Server `https://mcp.atlassian.com/v2/mcp` mit TLS,
Basic-Authentifizierung und MCP-Initialisierung. Die E-Mail allein ist kein
Zugriffsschlüssel. Browser-OAuth ist in dieser ersten Anbindung noch nicht eingebaut.
Die Anbindung führt nur fest freigegebene Lesewerkzeuge aus; Änderungen an Jira
sind über diesen Bereich noch nicht möglich. Ergebnisse werden als Text angezeigt.

Nach **Vorgang lesen** kannst du den Vorgang **als lokale Aufgabe übernehmen**.
Prüfe Titel und Beschreibung im Bestätigungsdialog. Die Aufgabe bleibt zunächst
lokal vorgemerkt; unter Tagesplanung kannst du die anfängliche 30-Minuten-Dauer
anpassen und den Backend-Abgleich ausdrücklich ausführen. Jira selbst wird dabei
nicht geändert. Doppelte Übernahmen überschreiben keine bestehende lokale Aufgabe.
Der Import benötigt den Modus mit Speicherung.

**Zugang entfernen** löscht die lokal gespeicherten Zugangsdaten. Zum Widerrufen
des Tokens selbst verwende deine Atlassian-Kontoeinstellungen.
Bei 401/403 prüfe Token, Scopes, MCP-Freigabe und die IP-Regeln deiner Organisation.
MICA veröffentlicht keine Token oder Server-Fehlertexte in Diagnosemeldungen.

Offizielle Quellen:

- [Atlassian MCP und Token-Authentifizierung](https://atlassian.github.io/atlassian-mcp-server/)
- [Werkzeuge und Scopes](https://support.atlassian.com/atlassian-ai-gateway/docs/supported-tools/)
- [MCP-Transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)

Die lokale Testabdeckung beweist den Protokoll- und Oberflächenpfad mit einem
Testserver. Eine echte Jira-Verbindung muss mit deinem Konto geprüft werden.
