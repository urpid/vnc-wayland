# Quickstart mit Script-Listener

## Voraussetzungen

- laufende KDE-Plasma-Sitzung unter Wayland
- funktionierendes `xdg-desktop-portal-kde`-/PipeWire-Setup

## Pakete installieren

```bash
sudo pacman -S --needed krfb qt6-tools pipewire wireplumber xdg-desktop-portal xdg-desktop-portal-kde socat iproute2 procps-ng
```

## Scripts ausfuehrbar machen

```bash
chmod +x start_krfb_wayland_ondemand.sh
chmod +x start_krfb_wayland_listener.sh
```

Die Ports und Wartezeiten stehen in [load-vars.sh](load-vars.sh). Voreingestellt sind `5900` oeffentlich und `5901` fuer `krfb`.

## krfb einmalig einrichten

```bash
./start_krfb_wayland_ondemand.sh --setup
```

Der Setup-Befehl loescht zuerst den bisherigen Portal-Restore-Token von `krfb`. Das KDE-Portal erzeugt beim Start einen neuen Token, den `krfb` bei seinen automatischen Neustarts wiederverwendet.

Das aktuelle KDE-Portal bietet fuer die Remote-Desktop-Sitzung von `krfb` keine Monitorauswahl an. Bei mehreren Monitoren uebertraegt `krfb` die gesamte Arbeitsflaeche.

In `krfb`:

- Freigabe der Arbeitsflaeche aktivieren
- Steuerung durch Maus und Tastatur erlauben

Die gewuenschte Passwort-Deaktivierung ist noch nicht umgesetzt. Das unveraenderte `krfb` erzwingt VNC-Authentifizierung und bietet dafuer keine Einstellung. Ohne Quellcode-Aenderung verlangt es entweder sein angezeigtes Sitzungskennwort mit lokaler Bestaetigung oder ein Passwort fuer den unbeaufsichtigten Zugriff.

Danach das `krfb`-Fenster mit **X** schliessen. Im Setup-Modus beendet das den Prozess vollstaendig. Beim normalen Start durch den Listener wird `krfb` ohne Hauptfenster im Tray gestartet.

## Firewall konfigurieren

`krfb` bindet seinen internen Port an alle Netzwerkadressen. Deshalb muss `5901` von aussen gesperrt bleiben; nur der Wake-Listener auf `5900` soll erreichbar sein.

Falls `ufw` aktiv ist:

```bash
sudo ufw allow 5900/tcp
sudo ufw deny 5901/tcp
```

## Listener starten

Die Script-Version benoetigt keine systemd-Unit und keine symbolischen Links. Port `5900` darf nicht gleichzeitig von einem anderen Listener belegt sein.

```bash
./start_krfb_wayland_listener.sh
```

Optional kann der oeffentliche Listener anders gebunden werden:

```bash
LISTEN_HOST=127.0.0.1 LISTEN_PORT=5902 ./start_krfb_wayland_listener.sh
```

Der interne `krfb`-Port bleibt dabei `5901`.

## Listener automatisch mit Plasma starten

Unter **Systemeinstellungen -> Autostart -> Hinzufuegen -> Anmeldeskript hinzufuegen** die Datei `start_krfb_wayland_listener.sh` direkt aus diesem Projektordner auswaehlen.

Die Script-Version startet `krfb` bei der ersten VNC-Verbindung direkt mit `--nodialog` im Tray. Sie verwendet weder `krfb-wayland-server.service` noch eine andere systemd-Unit. KDE startet das Anmeldeskript einmal; falls der Listener selbst endet, wird er nicht automatisch neu gestartet.

## Verbinden

Mit dem VNC-Client auf `host:5900` oder den gesetzten `LISTEN_PORT` verbinden.

Der Ablauf pro Verbindung ist:

- `socat` nimmt die Verbindung an.
- Das Script sendet immer einen Wake-Impuls gegen eine moegliche Abdunkelung.
- War mindestens ein aktivierter Monitor in DPMS-Standby, wartet das Script, bis alle aktivierten Monitore `DPMS On` melden.
- Nach einem Standby startet das Script `krfb` neu, damit eine neue PipeWire-Sitzung entsteht.
- War kein Monitor im Standby, startet das Script `krfb` nur, wenn sein interner Port nicht verfuegbar ist.
- `socat` leitet die unveraenderte VNC-Verbindung an `krfb` auf `127.0.0.1:5901` weiter.
- Bildschirmaufnahme sowie Maus- und Tastatureingaben laufen vollstaendig ueber `krfb` und das KDE-Portal.

Die Wake-Pruefung gilt fuer alle verbundenen und aktivierten DRM-Ausgaenge.

## Status und Logs

Bei manuellem Start schreibt der Listener direkt ins Terminal. Statuspruefung fuer Listener und `krfb`:

```bash
pgrep -af start_krfb_wayland_listener.sh
pgrep -a -x krfb
ss -ltnp 'sport = :5900'
```
