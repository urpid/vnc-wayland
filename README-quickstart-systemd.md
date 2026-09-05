# Quickstart mit systemd --user

## Voraussetzungen

- laufende KDE-Plasma-Sitzung unter Wayland
- `systemd --user`
- funktionierendes `xdg-desktop-portal-kde`-/PipeWire-Setup

## Pakete installieren

```bash
sudo pacman -S --needed krfb qt6-tools pipewire wireplumber xdg-desktop-portal xdg-desktop-portal-kde socat iproute2 procps-ng systemd
```

Beachte: `krfb` selbst nicht per `pacman` installieren, sondern das gepinnte Paket aus `packages/` verwenden. Siehe Abschnitt [krfb auf 26.04.3 pinnen](#krfb-auf-26043-pinnen-wichtig).

## krfb auf 26.04.3 pinnen (wichtig)

Seit Version 26.07 bindet das Haupt-Binary von `krfb` den VNC-Port nicht mehr: `RfbServer::start()` ruft `listen` nur auf, wenn das interne `passwordSet`-Flag gesetzt ist. Das normale `krfb` setzt dieses Flag nie (nur `krfb-virtualmonitor`), daher ist der Port nie offen und jede VNC-Verbindung wartet 60 Sekunden und scheitert. Ursache: krfb-Commit `842c91e` (April 2026, BUG 497071), auf `master` nicht gefixt.

Dieses Projekt pinnt deshalb:

- `krfb 26.04.3` (letzte Version ohne den Bug)
- Paket lokal: `packages/krfb-26.04.3-1-x86_64.pkg.tar.zst`
- Auto-Upgrade per `pacman -Syu` gesperrt via `IgnorePkg = krfb` in `/etc/pacman.conf`

Nach einer Neuinstallation oder wenn `krfb` versehentlich geupgradet wurde:

```bash
sudo pacman -U packages/krfb-26.04.3-1-x86_64.pkg.tar.zst
pkill -x krfb
```

`IgnorePkg` blockt nur `pacman -Syu`, nicht explizite `pacman -S krfb`-Aufrufe. Die Installationszeile oben darf daher nicht ohne Weiteres ausgefuehrt werden.

Gesundheit pruefen:

```bash
pacman -Q krfb    # => krfb 26.04.3-1
ss -ltnp 'sport = :5901'   # nach krfb-Start: LISTEN-Eintrag muss da sein
```

So bald upstream den Bug behebt: `IgnorePkg = krfb` in `/etc/pacman.conf` entfernen und `krfb` per `pacman -Syu` aktualisieren.

## Scripts ausfuehrbar machen

```bash
chmod +x start_krfb_wayland_ondemand.sh
chmod +x start_krfb_wayland_listener.sh
```

Der interne `krfb`-Port und die Wartezeiten stehen in [load-vars.sh](load-vars.sh). Der oeffentliche systemd-Port steht in [krfb-wayland.socket](krfb-wayland.socket). Voreingestellt sind `5900` oeffentlich und `5901` fuer `krfb`.

## Alte x11vnc-Units deaktivieren

Falls die vorherige Version installiert war:

```bash
systemctl --user disable --now x11vnc-wayland.socket
rm -f ~/.config/systemd/user/x11vnc-wayland.socket
rm -f ~/.config/systemd/user/x11vnc-wayland@.service
```

## Projekt und Units verlinken

Die Units verwenden den festen Link `~/.local/lib/krfb-wayland`, damit das Projekt selbst an einem beliebigen Ort liegen kann.

```bash
mkdir -p ~/.local/lib ~/.config/systemd/user
ln -sfnT "$PWD" ~/.local/lib/krfb-wayland
ln -sf ~/.local/lib/krfb-wayland/krfb-wayland-server.service ~/.config/systemd/user/krfb-wayland-server.service
ln -sf ~/.local/lib/krfb-wayland/krfb-wayland.socket ~/.config/systemd/user/krfb-wayland.socket
ln -sf ~/.local/lib/krfb-wayland/krfb-wayland@.service ~/.config/systemd/user/krfb-wayland@.service
systemctl --user daemon-reload
```

## krfb einmalig einrichten

```bash
./start_krfb_wayland_ondemand.sh --setup
```

Der Setup-Befehl loescht zuerst den bisherigen Portal-Restore-Token von `krfb`. Setup und automatische Starts laufen mit der Portal-Anwendungsidentitaet `org.kde.krfb`. Die automatische App-ID-Erkennung der krfb-Scope wird verwendet; die zusaetzliche Qt-Portalregistrierung ist fuer `krfb` deaktiviert, damit dieselbe D-Bus-Verbindung nicht doppelt registriert wird. Das KDE-Portal erzeugt dadurch einen neuen Token, den `krfb` bei seinen automatischen Neustarts wiederverwendet.

Das aktuelle KDE-Portal bietet fuer die Remote-Desktop-Sitzung von `krfb` keine Monitorauswahl an. Bei mehreren Monitoren uebertraegt `krfb` die gesamte Arbeitsflaeche.

In `krfb`:

- Freigabe der Arbeitsflaeche aktivieren
- Steuerung durch Maus und Tastatur erlauben

Die gewuenschte Passwort-Deaktivierung ist noch nicht umgesetzt. Das unveraenderte `krfb` erzwingt VNC-Authentifizierung und bietet dafuer keine Einstellung. Ohne Quellcode-Aenderung verlangt es entweder sein angezeigtes Sitzungskennwort mit lokaler Bestaetigung oder ein Passwort fuer den unbeaufsichtigten Zugriff.

Danach das `krfb`-Fenster mit **X** schliessen. Im Setup-Modus beendet das den Prozess vollstaendig. Der Verbindungs-Listener startet `krfb` spaeter ohne Hauptfenster im Tray als `krfb-wayland-server.service`.

## Firewall konfigurieren

`krfb` bindet seinen internen Port an alle Netzwerkadressen. Deshalb muss `5901` von aussen gesperrt bleiben; nur der Wake-Listener auf `5900` soll erreichbar sein.

Falls `ufw` aktiv ist:

```bash
sudo ufw allow 5900/tcp
sudo ufw deny 5901/tcp
```

## Socket aktivieren

```bash
systemctl --user enable --now krfb-wayland.socket
```

## Verbinden

Mit dem VNC-Client auf `host:5900` verbinden.

Der Ablauf pro Verbindung ist:

- Der systemd-Socket nimmt die Verbindung an.
- Das Script sendet immer einen Wake-Impuls gegen eine moegliche Abdunkelung.
- War mindestens ein aktivierter Monitor in DPMS-Standby, wartet das Script, bis alle aktivierten Monitore `DPMS On` melden.
- Nach einem Standby startet das Script `krfb` neu, damit eine neue PipeWire-Sitzung entsteht.
- Vor einem Neustart beendet das Script `krfb` sauber ueber D-Bus, damit der aktuelle Portal-Restore-Token gespeichert wird. Nur wenn das nicht funktioniert, folgen `TERM` und danach `KILL`.
- War kein Monitor im Standby, startet das Script `krfb` nur, wenn sein interner Port nicht verfuegbar ist.
- `socat` leitet die unveraenderte VNC-Verbindung an `krfb` auf `127.0.0.1:5901` weiter.
- Bildschirmaufnahme sowie Maus- und Tastatureingaben laufen vollstaendig ueber `krfb` und das KDE-Portal.

Die Wake-Pruefung gilt fuer alle verbundenen und aktivierten DRM-Ausgaenge.

## Status und Logs

```bash
systemctl --user status krfb-wayland.socket
systemctl --user status krfb-wayland-server.service
journalctl --user -u krfb-wayland.socket
journalctl --user -u krfb-wayland-server.service
journalctl --user -u 'krfb-wayland@*'
```

Fuer jede angenommene VNC-Verbindung protokolliert `krfb-wayland@.service` den Zeitpunkt, die Client-Adresse, den Startmodus und den Zustand aller DRM-Ausgaenge vor dem Wake-Befehl.
