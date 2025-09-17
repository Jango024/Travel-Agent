# Travel Agent

Hybrides Agentensystem zur Recherche von Pauschalreisen mit Web-Oberfläche, asynchronem Flask-Backend
und Telegram-Bot-Steuerung. Das Projekt besteht aus vier entkoppelten Hauptkomponenten:

> **Hinweis:** Der Telegram-Bot-Token wird nicht im Repository gespeichert und muss vor dem Start über die
> Umgebungsvariable `TELEGRAM_BOT_TOKEN` gesetzt werden.

1. **Frontend (Web-UI)** – HTML-Formular zur Eingabe aller Reiseparameter.
2. **Backend (Flask API & Orchestrator)** – nimmt Anfragen der UI und des Bots entgegen und verwaltet
die Hintergrundtasks.
3. **Agent-Core** – modulare Python-Bibliothek für Konfiguration, Scraping, Datenaufbereitung und
   Berichtserstellung.
4. **Bot-Interface (Telegram)** – Python-Skript auf Basis von `python-telegram-bot`, das Anfragen an das Backend delegiert.

## Projektstruktur

```
agent_core/
├── __init__.py
├── config.py          # Erzeugt AgentConfig-Objekte aus Formularen oder Freitext
├── processor.py       # Normalisierung, Filterung & Zusammenfassung der Angebote
├── reporter.py        # Erstellt den finalen Textreport
├── scraper.py         # Stellt die Scraping-Schnittstelle bereit (Mockdaten als Default)
└── workflow.py        # run_agent_workflow orchestriert den Gesamtprozess
bot.py                 # Telegram-Bot-Einstiegspunkt
requirements.txt       # Python-Abhängigkeiten
templates/
├── index.html         # UI für neue Suchen
└── status.html        # Status- und Ergebnisanzeige
webapp.py              # Flask-App inklusive Task-Manager und API-Routen
```

## Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Für Playwright-basiertes Scraping zusätzlich:

```bash
playwright install
```

## Entwicklung & Start der Komponenten

### Flask-Webanwendung

```bash
export FLASK_APP=webapp.py
flask run
```

Alternativ kann `python webapp.py` verwendet werden. Die Oberfläche ist anschließend unter
`http://127.0.0.1:5000/` erreichbar.

### Telegram-Bot

```bash
export TELEGRAM_BOT_TOKEN="<bot-token>"
export TRAVEL_AGENT_BACKEND_URL="https://<backend-host>"
python bot.py
```

Nach dem Start akzeptiert der Bot Freitext-Anfragen (z.B. „2 Personen nach Kreta im August, Budget 1200€“).
Das Backend analysiert die Anfrage, startet einen Hintergrundtask und sendet das Ergebnis nach Fertigstellung
per Telegram-Nachricht zurück.

## Filter & bevorzugte Quellen

Über die Web-Oberfläche lassen sich neben Budget, Abflugdatum und Unterkunft nun auch

* bevorzugte Reiseportale (z. B. `holidaycheck.de, tui.com`) hinterlegen. Diese Domains werden bei der Suche
  priorisiert über DuckDuckGo abgefragt.
* Mindest-Sternebewertung und Weiterempfehlungsquote festlegen. Angebote, die diese Schwellen nicht erfüllen,
  werden aus der Ergebnisliste gefiltert.

Freitext-Anfragen erkennen ebenfalls einfache Formulierungen wie „mindestens 4 Sterne“ oder „90% Empfehlung“
und übernehmen sie automatisch in die Suche.

## Systemd-Deployment (Beispiel)

`/etc/systemd/system/travel-agent.service`

```
[Unit]
Description=Gunicorn instance to serve Travel Agent App
After=network.target

[Service]
User=root
Group=www-data
WorkingDirectory=/root/travel-agent
Environment="TELEGRAM_BOT_TOKEN=<token>"
ExecStart=/root/travel-agent/venv/bin/gunicorn --workers 3 --bind unix:travel-agent.sock -m 007 webapp:app

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/travel-agent-bot.service`

```
[Unit]
Description=Telegram bot for Travel Agent
After=network.target travel-agent.service

[Service]
User=root
Group=www-data
WorkingDirectory=/root/travel-agent
Environment="TRAVEL_AGENT_BACKEND_URL=https://<backend-host>"
Environment="TELEGRAM_BOT_TOKEN=<token>"
ExecStart=/root/travel-agent/venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Nach Änderungen an den Service-Dateien:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now travel-agent.service travel-agent-bot.service
```

## Erweiterungsideen

* Austausch der Mock-Scraper durch echte Playwright-Scraper für verschiedene Portale.
* Persistente Speicherung von Suchergebnissen (z.B. PostgreSQL).
* Nutzung der OpenAI-API zur automatisierten Konfigurationserstellung aus Freitext.
* Benutzer-Authentifizierung und individuelle Historie der Reiseanfragen.
