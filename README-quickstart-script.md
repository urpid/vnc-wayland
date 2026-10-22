# Quickstart mit Script-Listener

## Voraussetzungen

- laufende KDE-Plasma-Sitzung unter Wayland
- laufendes `systemd --user` fuer die kurzlebige krfb-Scope
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

Die Ports und Wartezeiten stehen in [load-vars.sh](load-vars.sh). Voreingestellt sind `5900` oeffentlich und `5901` fuer `krfb`.

## krfb einmalig einrichten

```bash
./start_krfb_wayland_ondemand.sh --setup
```

Der Setup-Befehl loescht zuerst den bisherigen Portal-Restore-Token von `krfb`. Setup und automatische Starts laufen mit der Portal-Anwendungsidentitaet `org.kde.krfb`. Das KDE-Portal erzeugt dadurch einen neuen Token, den `krfb` bei seinen automatischen Neustarts wiederverwendet.

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

Die Script-Version installiert und aktiviert keine systemd-Unit und benoetigt keine symbolischen Links. Sie startet nur den jeweiligen `krfb`-Prozess mit `systemd-run` in einer kurzlebigen Scope-Unit, damit das KDE-Portal bei Setup und Normalbetrieb dieselbe Anwendungsidentitaet erkennt. Die Scope verschwindet nach dem Beenden von `krfb`. Die automatische App-ID-Erkennung der Scope wird verwendet; die zusaetzliche Qt-Portalregistrierung ist fuer `krfb` deaktiviert, damit dieselbe D-Bus-Verbindung nicht doppelt registriert wird. Port `5900` darf nicht gleichzeitig von einem anderen Listener belegt sein.

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

Die Script-Version startet `krfb` bei der ersten VNC-Verbindung mit `--nodialog`. Wenn die vom Listener gestartete Instanz keine VNC-Clients mehr bedient, beendet das Script sie sauber, damit die PipeWire-Bildschirmaufnahme nicht im Leerlauf weiterlaeuft. Bei der naechsten Verbindung startet es `krfb` neu. Bereits laufende, separat gestartete KRFB-Instanzen werden dabei nicht durch diese Bereinigung beendet. Die Script-Version verwendet nicht `krfb-wayland-server.service`; fuer den laufenden `krfb`-Prozess wird eine nicht installierte, kurzlebige Scope-Unit erzeugt. KDE startet das Anmeldeskript einmal; falls der Listener selbst endet, wird er nicht automatisch neu gestartet.

Script-Listener im KDE-Autostart und systemd-Socket sind alternative Betriebsarten. Beide verwenden standardmaessig Port `5900`; deshalb darf jeweils nur einer aktiv sein.

Beide Betriebsarten verwenden `start_krfb_wayland_ondemand.sh`: Der Script-Listener ruft es mit `--script` auf, die systemd-Units verwenden `--socket` fuer die Verbindung und `--server` fuer den KRFB-Dienst.

## Verbinden

Mit dem VNC-Client auf `host:5900` oder den gesetzten `LISTEN_PORT` verbinden.

Der Ablauf pro Verbindung ist:

- `socat` nimmt die Verbindung an.
- Das Script sendet immer einen Wake-Impuls gegen eine moegliche Abdunkelung.
- War mindestens ein aktivierter Monitor in DPMS-Standby, wartet das Script, bis alle aktivierten Monitore `DPMS On` melden.
- Nach einem Standby startet das Script `krfb` neu, damit eine neue PipeWire-Sitzung entsteht.
- Vor einem Neustart beendet das Script `krfb` sauber ueber D-Bus, damit der aktuelle Portal-Restore-Token gespeichert wird. Nur wenn das nicht funktioniert, folgen `TERM` und danach `KILL`.
- War kein Monitor im Standby, startet das Script `krfb` nur, wenn sein interner Port nicht verfuegbar ist.
- `socat` leitet die unveraenderte VNC-Verbindung an `krfb` auf `127.0.0.1:5901` weiter.
- Bildschirmaufnahme sowie Maus- und Tastatureingaben laufen vollstaendig ueber `krfb` und das KDE-Portal.
- Nach dem Verbindungsende prueft das Script alle `0,25` Sekunden auf noch bestehende TCP-Verbindungen am internen KRFB-Port. Sobald keine mehr bestehen, beendet es eine von dieser Verbindung gestartete KRFB-Instanz ueber D-Bus. Nach bis zu fuenf Sekunden stoppt es bei Bedarf deren eigene Scope-Unit. Der Listener bleibt aktiv.
- Schlaegt die Verbindungspruefung fehl, bleibt KRFB aktiv und das Script protokolliert den Fehler.
- Bei einem TCP-Abbruch waehrend der Weiterleitung sowie bei `HUP`, `INT` und `TERM` in dieser Phase beendet der Verbindungshandler seine Weiterleitung und fuehrt die Bereinigung aus.

Die Wake-Pruefung gilt fuer alle verbundenen und aktivierten DRM-Ausgaenge.

## Status und Logs

Bei manuellem Start schreibt der Listener direkt ins Terminal. Statuspruefung fuer Listener und `krfb`:

```bash
pgrep -af start_krfb_wayland_listener.sh
pgrep -a -x krfb
ss -ltnp 'sport = :5900'
```

Fuer jede angenommene VNC-Verbindung protokolliert der Listener den Zeitpunkt, die Client-Adresse, den Startmodus und den Zustand aller DRM-Ausgaenge vor dem Wake-Befehl. Beim Plasma-Autostart stehen diese Eintraege im Journal:

```bash
journalctl --user -u 'app-start_krfb_wayland_listener.sh@autostart.service'
```
