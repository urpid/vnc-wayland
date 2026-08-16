# Quickstart mit Script-Listener

## 1. Voraussetzungen

- laufende grafische Benutzer-Session
- KDE Plasma unter Wayland
- Python 3
- funktionierendes `xdg-desktop-portal-kde` / PipeWire-Setup
- `socat` fuer den Listener

## 2. Pakete installieren

```bash
sudo pacman -S --needed x11vnc xorg-xrandr xorg-setxkbmap qt6-tools libkscreen python-dbus python-gobject python-evdev gstreamer gst-plugins-base-libs gst-plugin-pipewire pipewire wireplumber xdg-desktop-portal xdg-desktop-portal-kde socat
```

## 3. In den Ordner wechseln

```bash
cd ~/Documents/x11vnc-wayland-bridge
```

Zentrale Pfade, Ports und Log-Limits stehen in [load-vars.sh](/home/worker/Documents/x11vnc-wayland-bridge/load-vars.sh).

## 4. Scripts ausfuehrbar machen

```bash
chmod +x start_x11vnc_wayland_listener.sh
chmod +x start_x11vnc_wayland_ondemand.sh
chmod +x run_component.sh
chmod +x portal_rawfb_bridge.py
chmod +x x11vnc_pipeinput.py
chmod +x pipe-logs.py
```

## 5. Firewall freigeben

Falls `ufw` aktiv ist:

```bash
sudo ufw allow 5900/tcp
```

## 6. uinput fuer Maus und Tastatur pruefen

Fuer Maus- und Tastatureingaben muss `/dev/uinput` vorhanden und fuer den Benutzer beschreibbar sein.

```bash
ls -l /dev/uinput
```

Wenn `/dev/uinput` fehlt:

```bash
sudo modprobe uinput
```

## 7. Bei Bedarf State leeren

```bash
./start_x11vnc_wayland_ondemand.sh --clear
```

Das loescht alle Dateien direkt in `~/.local/state/x11vnc-wayland-bridge`, also auch:
- `pwfb.meta`
- `pwfb.restore_token`
- alle Logs

## 8. Listener starten

```bash
./start_x11vnc_wayland_listener.sh
```

Optional:

```bash
LISTEN_HOST=127.0.0.1 LISTEN_PORT=5901 ./start_x11vnc_wayland_listener.sh
```

## 9. Verbinden

Mit dem VNC-Client auf `host:5900` verbinden oder auf den von dir gewaehlten Port.

Dabei gilt:
- `socat` lauscht auf dem Port
- pro Verbindung startet es intern denselben `--inetd`-Pfad
- wenn `pwfb.meta` oder `pwfb.restore_token` fehlen, oeffnet diese erste Verbindung automatisch den KDE-Freigabedialog
- `pwfb.meta` und `pwfb.restore_token` liegen beide dauerhaft im State-Verzeichnis
- die Geometrie der gespeicherten Outputs wird pro Verbindung frisch aus `xrandr` gelesen
- die eingehende Verbindung versucht den ausgewaehlten Monitor zuerst aufzuwecken
- `listener`, `inetd`, `bridge` und `pipeinput` schreiben jeweils in eine feste Logdatei mit Groessenlimit
- wenn der ausgewaehlte Monitor schlaeft, wartet die Verbindung auf `dpms=On`

## 10. Logs

```bash
tail -f ~/.local/state/x11vnc-wayland-bridge/listener.log
tail -f ~/.local/state/x11vnc-wayland-bridge/inetd.log
tail -f ~/.local/state/x11vnc-wayland-bridge/bridge.log
tail -f ~/.local/state/x11vnc-wayland-bridge/pipeinput.log
```
