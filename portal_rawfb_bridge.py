#!/usr/bin/env python3
import argparse
import mmap
import os
import re
import secrets
import shlex
import signal
import subprocess
import sys

import dbus
import dbus.mainloop.glib
import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst


PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SC_IFACE = "org.freedesktop.portal.ScreenCast"
REQ_IFACE = "org.freedesktop.portal.Request"
SESSION_IFACE = "org.freedesktop.portal.Session"

SOURCE_MONITOR = 1
CURSOR_EMBEDDED = 2

RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
STATE_DIR = os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.join(os.path.expanduser("~"), ".local", "state")),
    "x11vnc-wayland-bridge",
)
ANSI_RE = re.compile(r"\x1B\[[0-9;]*[A-Za-z]")


def token(prefix: str) -> str:
    return f"{prefix}{secrets.token_hex(6)}"


def command_line(args):
    return " ".join(shlex.quote(str(arg)) for arg in args)


def run_for_output(args, context):
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print(f"{context}: command not found: {args[0]}", file=sys.stderr)
        return None

    if result.returncode != 0:
        print(
            f"{context}: command failed with status {result.returncode}: {command_line(args)}",
            file=sys.stderr,
        )
        detail = (result.stderr or result.stdout).strip()
        if detail:
            print(detail, file=sys.stderr)

    return result


class PortalRequest:
    def __init__(self, bus, path):
        self.bus = bus
        self.path = path
        self.loop = GLib.MainLoop()
        self.response = None
        self.results = None
        self.bus.add_signal_receiver(
            self._on_response,
            dbus_interface=REQ_IFACE,
            signal_name="Response",
            path=path,
        )

    def _on_response(self, response, results):
        self.response = int(response)
        self.results = results
        self.loop.quit()

    def wait(self):
        self.loop.run()
        self.bus.remove_signal_receiver(
            self._on_response,
            dbus_interface=REQ_IFACE,
            signal_name="Response",
            path=self.path,
        )
        return self.response, self.results


def wait_request(bus, request_path):
    req = PortalRequest(bus, request_path)
    response, results = req.wait()
    if response != 0:
        raise RuntimeError(f"Portal request failed: response={response}, results={dict(results)}")
    return results


class RawfbWriter:
    def __init__(self, raw_path, meta_path=None, ready_path=None, outputs=None):
        self.raw_path = raw_path
        self.meta_path = meta_path or (raw_path + ".meta")
        self.ready_path = ready_path
        self.outputs = outputs or []
        self.width = None
        self.height = None
        self.f = None
        self.mm = None
        self.expected = None
        self.frame_count = 0

    def _ensure_mmap(self, width, height):
        if self.width == width and self.height == height and self.mm is not None:
            return

        self.close_file()
        self.width = width
        self.height = height
        self.expected = width * height * 4
        os.makedirs(os.path.dirname(self.raw_path) or ".", exist_ok=True)
        os.makedirs(os.path.dirname(self.meta_path) or ".", exist_ok=True)
        self.f = open(self.raw_path, "w+b")
        self.f.truncate(self.expected)
        self.mm = mmap.mmap(self.f.fileno(), self.expected, access=mmap.ACCESS_WRITE)

        with open(self.meta_path, "w", encoding="utf-8") as meta:
            meta.write(f"outputs={'/'.join(self.outputs)}\n")

        print(f"rawfb file ready: {self.raw_path} ({width}x{height})", file=sys.stderr)

    def write_sample(self, sample):
        buffer = sample.get_buffer()
        ok, info = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.ERROR
        try:
            if info.size < self.expected:
                return Gst.FlowReturn.ERROR
            self.mm.seek(0)
            self.mm.write(info.data[: self.expected])
            self.mm.flush()
            self.frame_count += 1
            if self.frame_count == 1:
                if self.ready_path:
                    with open(self.ready_path, "w", encoding="utf-8") as ready:
                        ready.write("ready\n")
                print("first frame written", file=sys.stderr)
        finally:
            buffer.unmap(info)
        return Gst.FlowReturn.OK

    def close_file(self):
        if self.mm is not None:
            self.mm.close()
            self.mm = None
        if self.f is not None:
            self.f.close()
            self.f = None

    def close(self):
        self.close_file()


class PortalRawfbBridge:
    def __init__(
        self,
        raw_path,
        meta_path=None,
        use_restore_token=True,
        token_file=None,
        ready_path=None,
        framerate=15,
    ):
        self.raw_path = raw_path
        self.use_restore_token = use_restore_token
        self.token_file = token_file
        self.framerate = framerate
        self.bus = None
        self.session_handle = None
        self.pw_fd = None
        self.streams = []
        self.pipeline = None
        self.loop = GLib.MainLoop()
        self.selected_outputs = []
        self.writer = RawfbWriter(
            raw_path,
            meta_path=meta_path,
            ready_path=ready_path,
            outputs=self.selected_outputs,
        )

    @staticmethod
    def _rectangles_overlap(a_rect, b_rect):
        ax, ay, aw, ah = a_rect
        bx, by, bw, bh = b_rect
        return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah

    @staticmethod
    def _parse_xrandr_outputs(text):
        outputs = []
        pattern = re.compile(
            r"^([A-Za-z0-9.-]+)\s+connected(?:\s+primary)?\s+(\d+)x(\d+)\+(\d+)\+(\d+)"
        )
        for line in text.splitlines():
            match = pattern.match(line)
            if not match:
                continue
            outputs.append(
                {
                    "name": match.group(1),
                    "width": int(match.group(2)),
                    "height": int(match.group(3)),
                    "x": int(match.group(4)),
                    "y": int(match.group(5)),
                }
            )
        return outputs

    @staticmethod
    def _parse_kscreen_outputs(text):
        outputs = []
        clean = ANSI_RE.sub("", text)
        current = None
        output_re = re.compile(r"^Output:\s+\d+\s+([A-Za-z0-9.-]+)\b")
        geom_re = re.compile(r"^\s*Geometry:\s*(\d+),(\d+)\s+(\d+)x(\d+)\b")
        for line in clean.splitlines():
            match = output_re.match(line)
            if match:
                current = {"name": match.group(1)}
                continue
            if current is None:
                continue
            match = geom_re.match(line)
            if not match:
                continue
            outputs.append(
                {
                    "name": current["name"],
                    "width": int(match.group(3)),
                    "height": int(match.group(4)),
                    "x": int(match.group(1)),
                    "y": int(match.group(2)),
                }
            )
            current = None
        return outputs

    @classmethod
    def _current_outputs(cls):
        outputs = []
        result = run_for_output(["xrandr", "--query"], "detect outputs with xrandr")

        if result is not None:
            outputs = cls._parse_xrandr_outputs(result.stdout)
            if outputs:
                return outputs

        result = run_for_output(["kscreen-doctor", "-o"], "detect outputs with kscreen-doctor")
        if result is None:
            return outputs

        outputs = cls._parse_kscreen_outputs(result.stdout)
        return outputs

    def resolve_selected_outputs(self):
        outputs = self._current_outputs()
        resolved = []
        for stream in self.streams:
            sx, sy = stream["position"]
            sw, sh = stream["size"]
            stream_rect = (sx, sy, sw, sh)
            for output in outputs:
                output_rect = (output["x"], output["y"], output["width"], output["height"])
                if self._rectangles_overlap(stream_rect, output_rect) and output["name"] not in resolved:
                    resolved.append(output["name"])
        return resolved

    @staticmethod
    def _tuple_prop(props, key, default):
        value = props.get(key)
        if value is None:
            return default
        try:
            return tuple(int(v) for v in value)
        except Exception:
            return default

    def load_restore_token(self):
        if not self.token_file:
            return None
        try:
            token = open(self.token_file, "r", encoding="utf-8").read().strip()
            return token or None
        except FileNotFoundError:
            return None

    def save_restore_token(self, token_value):
        if not self.token_file or not token_value:
            return
        os.makedirs(os.path.dirname(self.token_file) or ".", exist_ok=True)
        with open(self.token_file, "w", encoding="utf-8") as f:
            f.write(token_value + "\n")
        print(f"saved restore_token: {self.token_file}", file=sys.stderr)

    def setup_portal(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SessionBus()
        obj = self.bus.get_object(PORTAL_BUS, PORTAL_PATH)
        sc = dbus.Interface(obj, SC_IFACE)

        create_opts = {
            "handle_token": token("create"),
            "session_handle_token": token("session"),
        }
        create_request = sc.CreateSession(create_opts)
        create_results = wait_request(self.bus, create_request)
        self.session_handle = str(create_results["session_handle"])

        restore_token = self.load_restore_token() if self.use_restore_token else None

        select_opts = {
            "handle_token": token("select"),
            "types": dbus.UInt32(SOURCE_MONITOR),
            "multiple": dbus.Boolean(True),
            "cursor_mode": dbus.UInt32(CURSOR_EMBEDDED),
            "persist_mode": dbus.UInt32(2),
        }
        if restore_token:
            select_opts["restore_token"] = restore_token
            print(f"using restore_token from {self.token_file}", file=sys.stderr)
        select_request = sc.SelectSources(self.session_handle, select_opts)
        wait_request(self.bus, select_request)

        print("Portal selection may appear now.", file=sys.stderr)
        start_opts = {"handle_token": token("start")}
        start_request = sc.Start(self.session_handle, "", start_opts)
        start_results = wait_request(self.bus, start_request)

        streams = start_results.get("streams", [])
        if not streams:
            raise RuntimeError("Portal returned no streams.")
        new_restore_token = start_results.get("restore_token")
        if new_restore_token:
            self.save_restore_token(str(new_restore_token))
        else:
            print("portal returned no restore_token", file=sys.stderr)

        self.streams = []
        for idx, stream in enumerate(streams):
            node_id = int(stream[0])
            props = stream[1]
            position = self._tuple_prop(props, "position", (0, 0))
            size = self._tuple_prop(props, "size", (0, 0))
            self.streams.append(
                {
                    "index": idx,
                    "node_id": node_id,
                    "position": position,
                    "size": size,
                }
            )
            print(
                f"PipeWire stream[{idx}] node_id={node_id} position={position} size={size}",
                file=sys.stderr,
            )

        self.selected_outputs = self.resolve_selected_outputs()
        if not self.selected_outputs:
            raise RuntimeError("Could not map portal selection to current xrandr outputs.")
        self.writer.outputs = self.selected_outputs
        print(
            f"Selected outputs: {'/'.join(self.selected_outputs)}",
            file=sys.stderr,
        )

        fd = sc.OpenPipeWireRemote(self.session_handle, {})
        self.pw_fd = fd.take() if hasattr(fd, "take") else int(fd)
        print(f"PipeWire remote fd: {self.pw_fd}", file=sys.stderr)

    def setup_pipeline(self):
        Gst.init(None)
        self.pipeline = Gst.Pipeline.new("portal-rawfb")

        compositor = Gst.ElementFactory.make("compositor", "mix")
        rate = Gst.ElementFactory.make("videorate", "rate")
        postconv = Gst.ElementFactory.make("videoconvert", "postconv")
        capsf = Gst.ElementFactory.make("capsfilter", "caps")
        sink = Gst.ElementFactory.make("appsink", "sink")
        if not all((compositor, rate, postconv, capsf, sink)):
            raise RuntimeError("Failed to create GStreamer elements.")
        rate.set_property("max-rate", self.framerate)
        rate.set_property("drop-only", True)

        min_x = None
        min_y = None
        max_x = 0
        max_y = 0
        for stream in self.streams:
            x, y = stream["position"]
            w, h = stream["size"]
            if w > 0 and h > 0:
                min_x = x if min_x is None else min(min_x, x)
                min_y = y if min_y is None else min(min_y, y)
                max_x = max(max_x, x + w)
                max_y = max(max_y, y + h)

        if min_x is None or min_y is None:
            raise RuntimeError("Portal returned streams without usable size information.")

        max_width = max_x
        max_height = max_y

        capsf.set_property(
            "caps",
            Gst.Caps.from_string(
                f"video/x-raw,format=BGRx,width={max_width},height={max_height},framerate={self.framerate}/1"
            ),
        )
        print(f"Bridge framerate limit: {self.framerate} fps", file=sys.stderr)

        sink.set_property("emit-signals", True)
        sink.set_property("sync", False)
        sink.set_property("max-buffers", 2)
        sink.set_property("drop", True)
        sink.connect("new-sample", self.on_sample)

        self.pipeline.add(compositor)
        self.pipeline.add(rate)
        self.pipeline.add(postconv)
        self.pipeline.add(capsf)
        self.pipeline.add(sink)
        if (
            not compositor.link(rate)
            or not rate.link(postconv)
            or not postconv.link(capsf)
            or not capsf.link(sink)
        ):
            raise RuntimeError("Failed to link GStreamer pipeline.")

        for stream in self.streams:
            idx = stream["index"]
            src = Gst.ElementFactory.make("pipewiresrc", f"src{idx}")
            conv = Gst.ElementFactory.make("videoconvert", f"conv{idx}")
            queue = Gst.ElementFactory.make("queue", f"queue{idx}")
            if not all((src, conv, queue)):
                raise RuntimeError("Failed to create per-stream GStreamer elements.")

            src.set_property("fd", self.pw_fd)
            src.set_property("path", str(stream["node_id"]))
            src.set_property("do-timestamp", True)
            src.set_property("keepalive-time", 1000)

            self.pipeline.add(src)
            self.pipeline.add(conv)
            self.pipeline.add(queue)
            if not src.link(conv) or not conv.link(queue):
                raise RuntimeError("Failed to link per-stream pipeline.")

            sink_pad = compositor.get_request_pad("sink_%u")
            if sink_pad is None:
                raise RuntimeError("Failed to get compositor sink pad.")
            x, y = stream["position"]
            sink_pad.set_property("xpos", x)
            sink_pad.set_property("ypos", y)
            src_pad = queue.get_static_pad("src")
            if src_pad.link(sink_pad) != Gst.PadLinkReturn.OK:
                raise RuntimeError("Failed to connect stream to compositor.")

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_bus_message)

    def on_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.ERROR
        caps = sample.get_caps()
        structure = caps.get_structure(0)
        width = structure.get_value("width")
        height = structure.get_value("height")
        self.writer._ensure_mmap(width, height)
        return self.writer.write_sample(sample)

    def on_bus_message(self, _bus, message):
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"GStreamer error: {err} ({debug})", file=sys.stderr)
            self.stop()
        elif t == Gst.MessageType.EOS:
            print("GStreamer EOS", file=sys.stderr)
            self.stop()

    def run(self):
        self.setup_portal()
        self.setup_pipeline()
        self.pipeline.set_state(Gst.State.PLAYING)
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        self.loop.run()

    def stop(self):
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        if self.pw_fd is not None:
            try:
                os.close(self.pw_fd)
            except OSError:
                pass
            self.pw_fd = None
        if self.bus is not None and self.session_handle is not None:
            try:
                session = self.bus.get_object(PORTAL_BUS, self.session_handle)
                dbus.Interface(session, SESSION_IFACE).Close()
            except Exception:
                pass
        self.writer.close()
        if self.loop.is_running():
            self.loop.quit()


def main():
    parser = argparse.ArgumentParser(description="Bridge XDG Portal/PipeWire screencast to a rawfb file for x11vnc.")
    parser.add_argument("-o", "--output", default=os.path.join(RUNTIME_DIR, "pwfb.raw"))
    parser.add_argument("--meta-file", default=os.path.join(STATE_DIR, "pwfb.meta"))
    parser.add_argument("--token-file", default=os.path.join(STATE_DIR, "pwfb.restore_token"))
    parser.add_argument("--ready-file", default=None)
    parser.add_argument("--framerate", type=int, default=15, help="Maximum bridge output framerate in frames per second.")
    parser.add_argument("--no-restore", action="store_true", help="Ignore any saved restore token and force a fresh portal selection.")
    args = parser.parse_args()
    if args.framerate < 1:
        parser.error("--framerate must be at least 1")

    bridge = PortalRawfbBridge(
        raw_path=args.output,
        meta_path=args.meta_file,
        use_restore_token=not args.no_restore,
        token_file=args.token_file,
        ready_path=args.ready_file,
        framerate=args.framerate,
    )
    bridge.run()


if __name__ == "__main__":
    main()
