#!/usr/bin/env python3
import argparse
import ctypes
import ctypes.util
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass

from evdev import AbsInfo, UInput, ecodes


@dataclass
class Geometry:
    desktop_width: int
    desktop_height: int
    clip_x: int = 0
    clip_y: int = 0


BUTTON_CODE_MAP = {
    1: ecodes.BTN_LEFT,
    2: ecodes.BTN_MIDDLE,
    3: ecodes.BTN_RIGHT,
    8: ecodes.BTN_SIDE,
    9: ecodes.BTN_EXTRA,
}

SPECIAL_KEYS = {
    "Return": (ecodes.KEY_ENTER, False),
    "BackSpace": (ecodes.KEY_BACKSPACE, False),
    "Tab": (ecodes.KEY_TAB, False),
    "ISO_Left_Tab": (ecodes.KEY_TAB, False),
    "Escape": (ecodes.KEY_ESC, False),
    "space": (ecodes.KEY_SPACE, False),
    "Shift_L": (ecodes.KEY_LEFTSHIFT, False),
    "Shift_R": (ecodes.KEY_RIGHTSHIFT, False),
    "Control_L": (ecodes.KEY_LEFTCTRL, False),
    "Control_R": (ecodes.KEY_RIGHTCTRL, False),
    "Alt_L": (ecodes.KEY_LEFTALT, False),
    "Alt_R": (ecodes.KEY_RIGHTALT, False),
    "Meta_L": (ecodes.KEY_LEFTMETA, False),
    "Meta_R": (ecodes.KEY_RIGHTMETA, False),
    "Super_L": (ecodes.KEY_LEFTMETA, False),
    "Super_R": (ecodes.KEY_RIGHTMETA, False),
    "Menu": (ecodes.KEY_MENU, False),
    "Caps_Lock": (ecodes.KEY_CAPSLOCK, False),
    "Num_Lock": (ecodes.KEY_NUMLOCK, False),
    "Scroll_Lock": (ecodes.KEY_SCROLLLOCK, False),
    "Left": (ecodes.KEY_LEFT, False),
    "Right": (ecodes.KEY_RIGHT, False),
    "Up": (ecodes.KEY_UP, False),
    "Down": (ecodes.KEY_DOWN, False),
    "Home": (ecodes.KEY_HOME, False),
    "End": (ecodes.KEY_END, False),
    "Prior": (ecodes.KEY_PAGEUP, False),
    "Page_Up": (ecodes.KEY_PAGEUP, False),
    "Next": (ecodes.KEY_PAGEDOWN, False),
    "Page_Down": (ecodes.KEY_PAGEDOWN, False),
    "Insert": (ecodes.KEY_INSERT, False),
    "Delete": (ecodes.KEY_DELETE, False),
    "Print": (ecodes.KEY_PRINT, False),
    "Sys_Req": (ecodes.KEY_SYSRQ, False),
    "Pause": (ecodes.KEY_PAUSE, False),
    "minus": (ecodes.KEY_MINUS, False),
    "equal": (ecodes.KEY_EQUAL, False),
    "bracketleft": (ecodes.KEY_LEFTBRACE, False),
    "bracketright": (ecodes.KEY_RIGHTBRACE, False),
    "backslash": (ecodes.KEY_BACKSLASH, False),
    "semicolon": (ecodes.KEY_SEMICOLON, False),
    "apostrophe": (ecodes.KEY_APOSTROPHE, False),
    "grave": (ecodes.KEY_GRAVE, False),
    "comma": (ecodes.KEY_COMMA, False),
    "period": (ecodes.KEY_DOT, False),
    "slash": (ecodes.KEY_SLASH, False),
    "exclam": (ecodes.KEY_1, True),
    "at": (ecodes.KEY_2, True),
    "numbersign": (ecodes.KEY_3, True),
    "dollar": (ecodes.KEY_4, True),
    "percent": (ecodes.KEY_5, True),
    "asciicircum": (ecodes.KEY_6, True),
    "ampersand": (ecodes.KEY_7, True),
    "asterisk": (ecodes.KEY_8, True),
    "parenleft": (ecodes.KEY_9, True),
    "parenright": (ecodes.KEY_0, True),
    "underscore": (ecodes.KEY_MINUS, True),
    "plus": (ecodes.KEY_EQUAL, True),
    "braceleft": (ecodes.KEY_LEFTBRACE, True),
    "braceright": (ecodes.KEY_RIGHTBRACE, True),
    "bar": (ecodes.KEY_BACKSLASH, True),
    "colon": (ecodes.KEY_SEMICOLON, True),
    "quotedbl": (ecodes.KEY_APOSTROPHE, True),
    "less": (ecodes.KEY_COMMA, True),
    "greater": (ecodes.KEY_DOT, True),
    "question": (ecodes.KEY_SLASH, True),
    "asciitilde": (ecodes.KEY_GRAVE, True),
    "KP_0": (ecodes.KEY_KP0, False),
    "KP_1": (ecodes.KEY_KP1, False),
    "KP_2": (ecodes.KEY_KP2, False),
    "KP_3": (ecodes.KEY_KP3, False),
    "KP_4": (ecodes.KEY_KP4, False),
    "KP_5": (ecodes.KEY_KP5, False),
    "KP_6": (ecodes.KEY_KP6, False),
    "KP_7": (ecodes.KEY_KP7, False),
    "KP_8": (ecodes.KEY_KP8, False),
    "KP_9": (ecodes.KEY_KP9, False),
    "KP_Add": (ecodes.KEY_KPPLUS, False),
    "KP_Subtract": (ecodes.KEY_KPMINUS, False),
    "KP_Multiply": (ecodes.KEY_KPASTERISK, False),
    "KP_Divide": (ecodes.KEY_KPSLASH, False),
    "KP_Decimal": (ecodes.KEY_KPDOT, False),
    "KP_Enter": (ecodes.KEY_KPENTER, False),
    "KP_Insert": (ecodes.KEY_KP0, False),
    "KP_Delete": (ecodes.KEY_KPDOT, False),
}

FKEY_RE = re.compile(r"^F([1-9]|1[0-9]|2[0-4])$")
KDE_LAYOUT_RE = re.compile(r'"([^"]*)",\s*"([^"]*)",\s*"([^"]*)"')
XKB_KEYSYM_CASE_INSENSITIVE = 1
XKB_EVDEV_OFFSET = 8
IGNORED_MOD_NAMES = {"Lock", "NumLock"}
MOD_NAME_TO_KEYCODE = {
    "Shift": ecodes.KEY_LEFTSHIFT,
    "Control": ecodes.KEY_LEFTCTRL,
    "Mod1": ecodes.KEY_LEFTALT,
    "Alt": ecodes.KEY_LEFTALT,
    "Mod4": ecodes.KEY_LEFTMETA,
    "Meta": ecodes.KEY_LEFTMETA,
    "Super": ecodes.KEY_LEFTMETA,
    "LevelThree": ecodes.KEY_RIGHTALT,
    "Mod5": ecodes.KEY_RIGHTALT,
}
DIRECT_MODIFIER_KEYCODES = {
    ecodes.KEY_LEFTSHIFT,
    ecodes.KEY_RIGHTSHIFT,
    ecodes.KEY_LEFTCTRL,
    ecodes.KEY_RIGHTCTRL,
    ecodes.KEY_LEFTALT,
    ecodes.KEY_RIGHTALT,
    ecodes.KEY_LEFTMETA,
    ecodes.KEY_RIGHTMETA,
}


class XkbRuleNames(ctypes.Structure):
    _fields_ = [
        ("rules", ctypes.c_char_p),
        ("model", ctypes.c_char_p),
        ("layout", ctypes.c_char_p),
        ("variant", ctypes.c_char_p),
        ("options", ctypes.c_char_p),
    ]


def _decode_qdbus_value(value: str) -> str:
    return value.strip().strip('"')


def env_int(name: str, default: int = 0) -> int:
    value = os.environ.get(name, "")
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        print(f"ignoring invalid integer for {name}: {value!r}", file=sys.stderr)
        return default


def env_int_list(name: str):
    value = os.environ.get(name, "")
    if not value:
        return []
    result = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.append(int(item))
        except ValueError:
            print(f"ignoring invalid integer in {name}: {item!r}", file=sys.stderr)
    return result


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


def query_kde_layout():
    current = run_for_output(
        ["qdbus6", "org.kde.keyboard", "/Layouts", "org.kde.KeyboardLayouts.getLayout"],
        "query KDE keyboard layout index",
    )
    if current is None:
        return None

    layouts = run_for_output(
        ["qdbus6", "--literal", "org.kde.keyboard", "/Layouts", "org.kde.KeyboardLayouts.getLayoutsList"],
        "query KDE keyboard layout list",
    )
    if layouts is None:
        return None

    if current.returncode != 0 or layouts.returncode != 0:
        return None

    try:
        index = int(current.stdout.strip())
    except ValueError:
        return None

    entries = KDE_LAYOUT_RE.findall(layouts.stdout)
    if index < 0 or index >= len(entries):
        return None

    layout, variant, _label = entries[index]
    if not layout:
        return None
    return layout, variant


def query_rules_model():
    rules = "evdev"
    model = "pc105"

    result = run_for_output(["setxkbmap", "-query"], "query XKB rules/model with setxkbmap")
    if result is None:
        return rules, model

    if result.returncode != 0:
        return rules, model

    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key == "rules" and value:
            rules = value
        elif key == "model" and value:
            model = value
    return rules, model


def query_layout_variant():
    kde_layout = query_kde_layout()
    if kde_layout is not None:
        return kde_layout

    layout = ""
    variant = ""
    result = run_for_output(["localectl", "status"], "query keyboard layout with localectl")

    if result is not None and result.returncode == 0:
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("X11 Layout:"):
                layout = line.split(":", 1)[1].strip()
            elif line.startswith("X11 Variant:"):
                variant = line.split(":", 1)[1].strip()
        if layout:
            return layout, variant

    result = run_for_output(["setxkbmap", "-query"], "query keyboard layout with setxkbmap")
    if result is None:
        return "us", ""

    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            if key == "layout":
                layout = value
            elif key == "variant":
                variant = value
    return layout or "us", variant


class XkbMapper:
    def __init__(self):
        lib_path = ctypes.util.find_library("xkbcommon")
        if not lib_path:
            raise RuntimeError("libxkbcommon not found")

        self.lib = ctypes.CDLL(lib_path)
        self._init_signatures()
        self.ctx = self.lib.xkb_context_new(0)
        if not self.ctx:
            raise RuntimeError("xkb_context_new failed")

        rules, model = query_rules_model()
        layout, variant = query_layout_variant()
        self.layout = layout
        self.variant = variant

        names = XkbRuleNames(
            rules=rules.encode(),
            model=model.encode(),
            layout=layout.encode(),
            variant=variant.encode() if variant else None,
            options=None,
        )
        self.keymap = self.lib.xkb_keymap_new_from_names(self.ctx, ctypes.byref(names), 0)
        if not self.keymap:
            self.lib.xkb_context_unref(self.ctx)
            self.ctx = None
            raise RuntimeError(f"xkb_keymap_new_from_names failed for layout={layout!r} variant={variant!r}")

        self.min_keycode = self.lib.xkb_keymap_min_keycode(self.keymap)
        self.max_keycode = self.lib.xkb_keymap_max_keycode(self.keymap)
        self.num_mods = self.lib.xkb_keymap_num_mods(self.keymap)
        self.mod_names = []
        for idx in range(self.num_mods):
            raw = self.lib.xkb_keymap_mod_get_name(self.keymap, idx)
            self.mod_names.append(raw.decode() if raw else "")

        self.cache = {}

    def _init_signatures(self):
        self.lib.xkb_context_new.argtypes = [ctypes.c_int]
        self.lib.xkb_context_new.restype = ctypes.c_void_p
        self.lib.xkb_context_unref.argtypes = [ctypes.c_void_p]
        self.lib.xkb_context_unref.restype = None
        self.lib.xkb_keymap_new_from_names.argtypes = [ctypes.c_void_p, ctypes.POINTER(XkbRuleNames), ctypes.c_int]
        self.lib.xkb_keymap_new_from_names.restype = ctypes.c_void_p
        self.lib.xkb_keymap_unref.argtypes = [ctypes.c_void_p]
        self.lib.xkb_keymap_unref.restype = None
        self.lib.xkb_keymap_min_keycode.argtypes = [ctypes.c_void_p]
        self.lib.xkb_keymap_min_keycode.restype = ctypes.c_uint32
        self.lib.xkb_keymap_max_keycode.argtypes = [ctypes.c_void_p]
        self.lib.xkb_keymap_max_keycode.restype = ctypes.c_uint32
        self.lib.xkb_keymap_num_mods.argtypes = [ctypes.c_void_p]
        self.lib.xkb_keymap_num_mods.restype = ctypes.c_uint32
        self.lib.xkb_keymap_mod_get_name.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.lib.xkb_keymap_mod_get_name.restype = ctypes.c_char_p
        self.lib.xkb_keymap_num_layouts_for_key.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.lib.xkb_keymap_num_layouts_for_key.restype = ctypes.c_uint32
        self.lib.xkb_keymap_num_levels_for_key.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        self.lib.xkb_keymap_num_levels_for_key.restype = ctypes.c_uint32
        self.lib.xkb_keymap_key_get_syms_by_level.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32)),
        ]
        self.lib.xkb_keymap_key_get_syms_by_level.restype = ctypes.c_int
        self.lib.xkb_keymap_key_get_mods_for_level.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_size_t,
        ]
        self.lib.xkb_keymap_key_get_mods_for_level.restype = ctypes.c_int
        self.lib.xkb_keysym_from_name.argtypes = [ctypes.c_char_p, ctypes.c_int]
        self.lib.xkb_keysym_from_name.restype = ctypes.c_uint32
        self.lib.xkb_utf32_to_keysym.argtypes = [ctypes.c_uint32]
        self.lib.xkb_utf32_to_keysym.restype = ctypes.c_uint32

    def keysym_from_name(self, name: str) -> int:
        keysym = self.lib.xkb_keysym_from_name(name.encode(), XKB_KEYSYM_CASE_INSENSITIVE)
        if keysym:
            return int(keysym)
        if len(name) == 1:
            return int(self.lib.xkb_utf32_to_keysym(ord(name)))
        return 0

    def mask_to_modifier_codes(self, mask: int):
        codes = []
        unknown = []
        for idx, mod_name in enumerate(self.mod_names):
            if not (mask & (1 << idx)):
                continue
            if mod_name in IGNORED_MOD_NAMES:
                continue
            code = MOD_NAME_TO_KEYCODE.get(mod_name)
            if code is None:
                unknown.append(mod_name)
                continue
            if code not in codes:
                codes.append(code)
        return tuple(codes), tuple(unknown)

    def resolve(self, name: str):
        cached = self.cache.get(name)
        if cached is not None:
            return cached

        keysym = self.keysym_from_name(name)
        if not keysym:
            self.cache[name] = None
            return None

        best = None
        masks = (ctypes.c_uint32 * 16)()

        for keycode in range(self.min_keycode, self.max_keycode + 1):
            evdev_code = keycode - XKB_EVDEV_OFFSET
            if evdev_code <= 0:
                continue
            layout_count = self.lib.xkb_keymap_num_layouts_for_key(self.keymap, keycode)
            if layout_count == 0:
                continue
            for layout_index in range(layout_count):
                level_count = self.lib.xkb_keymap_num_levels_for_key(self.keymap, keycode, layout_index)
                if level_count == 0:
                    continue
                for level in range(level_count):
                    syms_ptr = ctypes.POINTER(ctypes.c_uint32)()
                    sym_count = self.lib.xkb_keymap_key_get_syms_by_level(
                        self.keymap,
                        keycode,
                        layout_index,
                        level,
                        ctypes.byref(syms_ptr),
                    )
                    if sym_count <= 0:
                        continue
                    if not any(int(syms_ptr[i]) == keysym for i in range(sym_count)):
                        continue

                    mask_count = self.lib.xkb_keymap_key_get_mods_for_level(
                        self.keymap,
                        keycode,
                        layout_index,
                        level,
                        masks,
                        len(masks),
                    )
                    candidate_masks = [0] if mask_count <= 0 else [int(masks[i]) for i in range(mask_count)]
                    for mask in candidate_masks:
                        modifier_codes, unknown_mods = self.mask_to_modifier_codes(mask)
                        if unknown_mods:
                            continue
                        score = (len(modifier_codes), 0 if ecodes.KEY_RIGHTALT in modifier_codes else 1, evdev_code)
                        candidate = (evdev_code, modifier_codes, score)
                        if best is None or candidate[2] < best[2]:
                            best = candidate

        resolved = None if best is None else (best[0], best[1])
        self.cache[name] = resolved
        return resolved

    def close(self):
        if getattr(self, "keymap", None):
            self.lib.xkb_keymap_unref(self.keymap)
            self.keymap = None
        if getattr(self, "ctx", None):
            self.lib.xkb_context_unref(self.ctx)
            self.ctx = None


def build_key_capabilities():
    codes = set(BUTTON_CODE_MAP.values())
    for code, _ in SPECIAL_KEYS.values():
        codes.add(code)
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        codes.add(getattr(ecodes, f"KEY_{ch}"))
    for ch in "0123456789":
        codes.add(getattr(ecodes, f"KEY_{ch}"))
    for n in range(1, 25):
        codes.add(getattr(ecodes, f"KEY_F{n}"))
    codes.update(DIRECT_MODIFIER_KEYCODES)
    codes.add(ecodes.KEY_102ND)
    return sorted(codes)


def load_geometry(meta_path: str, desktop_width: int, desktop_height: int) -> Geometry:
    outputs = []
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key == "outputs" and value:
                    outputs = [name for name in value.split("/") if name]
    except FileNotFoundError:
        pass

    if outputs:
        min_x = None
        min_y = None
        result = run_for_output(["xrandr", "--query"], "query output offsets with xrandr")

        if result is not None:
            output_re = re.compile(
                r"^([A-Za-z0-9.-]+)\s+connected(?:\s+primary)?\s+(\d+)x(\d+)\+(\d+)\+(\d+)"
            )
            for line in result.stdout.splitlines():
                match = output_re.match(line)
                if not match or match.group(1) not in outputs:
                    continue
                x = int(match.group(4))
                y = int(match.group(5))
                min_x = x if min_x is None else min(min_x, x)
                min_y = y if min_y is None else min(min_y, y)
            if min_x is not None and min_y is not None:
                return Geometry(
                    desktop_width=desktop_width,
                    desktop_height=desktop_height,
                    clip_x=min_x,
                    clip_y=min_y,
                )

    return Geometry(
        desktop_width=desktop_width,
        desktop_height=desktop_height,
    )


def clamp(value: int, lo: int, hi: int) -> int:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def resolve_keysym(name: str, mapper=None):
    if not name or name == "null":
        return None, ()
    if mapper is not None:
        resolved = mapper.resolve(name)
        if resolved is not None:
            code, modifiers = resolved
            return code, tuple(modifiers)
    if name in SPECIAL_KEYS:
        code, need_shift = SPECIAL_KEYS[name]
        return code, (ecodes.KEY_LEFTSHIFT,) if need_shift else ()
    match = FKEY_RE.match(name)
    if match:
        return getattr(ecodes, f"KEY_F{match.group(1)}"), ()
    if len(name) == 1:
        ch = name
        if "a" <= ch <= "z":
            return getattr(ecodes, f"KEY_{ch.upper()}"), ()
        if "A" <= ch <= "Z":
            return getattr(ecodes, f"KEY_{ch}"), (ecodes.KEY_LEFTSHIFT,)
        if "0" <= ch <= "9":
            return getattr(ecodes, f"KEY_{ch}"), ()
    return None, ()


class PipeInput:
    def __init__(self, geometry: Geometry, mapper=None, debug=None, key_refresh_nudge=0, key_refresh_delays_ms=None):
        self.geometry = geometry
        self.mapper = mapper
        self.debug = debug or (lambda *_args, **_kwargs: None)
        self.key_refresh_nudge = max(0, key_refresh_nudge)
        self.key_refresh_delays = tuple(max(0, delay) / 1000 for delay in (key_refresh_delays_ms or []))
        self.io_lock = threading.RLock()
        self.nudge_lock = threading.Lock()
        self.nudge_generation = 0
        self.last_abs_x = None
        self.last_abs_y = None
        self.prev_mask = 0
        self.real_mod_counts = defaultdict(int)
        self.synthetic_mod_users = defaultdict(set)
        self.unknown = set()

        caps = {
            ecodes.EV_KEY: build_key_capabilities(),
            ecodes.EV_ABS: [
                (
                    ecodes.ABS_X,
                    AbsInfo(
                        value=0,
                        min=0,
                        max=max(0, geometry.desktop_width - 1),
                        fuzz=0,
                        flat=0,
                        resolution=0,
                    ),
                ),
                (
                    ecodes.ABS_Y,
                    AbsInfo(
                        value=0,
                        min=0,
                        max=max(0, geometry.desktop_height - 1),
                        fuzz=0,
                        flat=0,
                        resolution=0,
                    ),
                ),
            ],
            ecodes.EV_REL: [ecodes.REL_WHEEL, ecodes.REL_HWHEEL],
        }
        self.ui = UInput(events=caps, name="x11vnc-wayland-bridge", version=0x1)

    def write(self, etype, code, value):
        self.ui.write(etype, code, value)

    def syn(self):
        self.ui.syn()

    def handle_pointer(self, x: int, y: int, mask: int):
        with self.io_lock:
            abs_x = clamp(self.geometry.clip_x + x, 0, self.geometry.desktop_width - 1)
            abs_y = clamp(self.geometry.clip_y + y, 0, self.geometry.desktop_height - 1)
            self.debug(
                f"pointer x={x} y={y} mask={mask} -> abs_x={abs_x} abs_y={abs_y} "
                f"clip_x={self.geometry.clip_x} clip_y={self.geometry.clip_y}"
            )

            self.write(ecodes.EV_ABS, ecodes.ABS_X, abs_x)
            self.write(ecodes.EV_ABS, ecodes.ABS_Y, abs_y)
            self.last_abs_x = abs_x
            self.last_abs_y = abs_y

            for button in range(1, 10):
                bit = 1 << (button - 1)
                old = bool(self.prev_mask & bit)
                new = bool(mask & bit)
                if old == new:
                    continue
                if button == 4 and new:
                    self.write(ecodes.EV_REL, ecodes.REL_WHEEL, 1)
                elif button == 5 and new:
                    self.write(ecodes.EV_REL, ecodes.REL_WHEEL, -1)
                elif button == 6 and new:
                    self.write(ecodes.EV_REL, ecodes.REL_HWHEEL, -1)
                elif button == 7 and new:
                    self.write(ecodes.EV_REL, ecodes.REL_HWHEEL, 1)
                else:
                    code = BUTTON_CODE_MAP.get(button)
                    if code is not None:
                        self.write(ecodes.EV_KEY, code, 1 if new else 0)

            self.syn()
            self.prev_mask = mask

    def nudge_pointer_refresh(self):
        with self.io_lock:
            if not self.key_refresh_nudge or self.last_abs_x is None or self.last_abs_y is None:
                return

            x = self.last_abs_x
            y = self.last_abs_y
            delta = self.key_refresh_nudge
            if x + delta <= self.geometry.desktop_width - 1:
                nudged_x = x + delta
            elif x - delta >= 0:
                nudged_x = x - delta
            else:
                return

            self.debug(f"key refresh nudge x={x}->{nudged_x}->{x} y={y}")
            self.write(ecodes.EV_ABS, ecodes.ABS_X, nudged_x)
            self.write(ecodes.EV_ABS, ecodes.ABS_Y, y)
            self.syn()
            time.sleep(0.005)
            self.write(ecodes.EV_ABS, ecodes.ABS_X, x)
            self.write(ecodes.EV_ABS, ecodes.ABS_Y, y)
            self.syn()

    def schedule_pointer_refresh_nudges(self):
        if not self.key_refresh_nudge:
            return

        with self.nudge_lock:
            self.nudge_generation += 1
            generation = self.nudge_generation

        self.nudge_pointer_refresh()
        for delay in self.key_refresh_delays:
            timer = threading.Timer(delay, self._delayed_pointer_refresh_nudge, args=(generation,))
            timer.daemon = True
            timer.start()

    def _delayed_pointer_refresh_nudge(self, generation):
        with self.nudge_lock:
            if generation != self.nudge_generation:
                return
        self.nudge_pointer_refresh()

    def handle_keysym(self, down: int, name: str):
        should_nudge = False
        with self.io_lock:
            code, modifiers = resolve_keysym(name, self.mapper)
            if code is None:
                self.debug(f"keysym name={name!r} down={down} -> unsupported")
                if name not in self.unknown:
                    self.unknown.add(name)
                    print(f"ignoring unsupported keysym: {name}", file=sys.stderr)
                return
            self.debug(
                f"keysym name={name!r} down={down} -> code={code} "
                f"modifiers={[int(m) for m in modifiers]}"
            )

            synth_tag = (name, code)
            if code in DIRECT_MODIFIER_KEYCODES:
                if down:
                    self.real_mod_counts[code] += 1
                else:
                    self.real_mod_counts[code] = max(0, self.real_mod_counts[code] - 1)

            if down:
                for modifier_code in modifiers:
                    if self.real_mod_counts[modifier_code] == 0 and synth_tag not in self.synthetic_mod_users[modifier_code]:
                        if not self.synthetic_mod_users[modifier_code]:
                            self.write(ecodes.EV_KEY, modifier_code, 1)
                        self.synthetic_mod_users[modifier_code].add(synth_tag)

            self.write(ecodes.EV_KEY, code, 1 if down else 0)

            if not down:
                for modifier_code in modifiers:
                    users = self.synthetic_mod_users.get(modifier_code)
                    if not users or synth_tag not in users:
                        continue
                    users.remove(synth_tag)
                    if not users and self.real_mod_counts[modifier_code] == 0:
                        self.write(ecodes.EV_KEY, modifier_code, 0)

            self.syn()
            should_nudge = not down

        if should_nudge:
            self.schedule_pointer_refresh_nudges()

    def close(self):
        if self.mapper is not None:
            self.mapper.close()
        if self.ui is not None:
            self.ui.close()


def parse_pointer(parts):
    if len(parts) < 5:
        return None
    uid = int(parts[1])
    x = int(parts[2])
    y = int(parts[3])
    mask = int(parts[4])
    return uid, x, y, mask


def parse_keysym(parts):
    if len(parts) < 5:
        return None
    uid = int(parts[1])
    down = int(parts[2])
    name = parts[4]
    return uid, down, name


def main():
    parser = argparse.ArgumentParser(description="Offset-aware x11vnc pipeinput helper for KDE Wayland rawfb bridge.")
    parser.add_argument("--meta", required=True)
    parser.add_argument("--desktop", required=True, help="Desktop geometry as WIDTHxHEIGHT")
    args = parser.parse_args()

    m = re.match(r"^(\d+)x(\d+)$", args.desktop)
    if not m:
        raise SystemExit(f"invalid --desktop value: {args.desktop}")

    desktop_width = int(m.group(1))
    desktop_height = int(m.group(2))
    geometry = load_geometry(args.meta, desktop_width, desktop_height)
    key_refresh_nudge = env_int("X11VNC_PIPEINPUT_KEY_REFRESH_NUDGE", 0)
    key_refresh_delays_ms = env_int_list("X11VNC_PIPEINPUT_KEY_REFRESH_DELAYS_MS")

    def debug(message: str):
        print(message, file=sys.stderr, flush=True)

    debug(
        f"startup meta={args.meta} desktop={desktop_width}x{desktop_height} "
        f"clip_x={geometry.clip_x} clip_y={geometry.clip_y}"
    )
    mapper = None
    try:
        mapper = XkbMapper()
        print(
            f"using XKB layout mapping: layout={mapper.layout!r} variant={mapper.variant!r}",
            file=sys.stderr,
        )
        debug(f"xkb layout={mapper.layout!r} variant={mapper.variant!r}")
    except Exception as exc:
        print(f"XKB mapper unavailable, falling back to static key mapping: {exc}", file=sys.stderr)
        debug(f"xkb mapper unavailable: {exc}")
    helper = PipeInput(
        geometry,
        mapper=mapper,
        debug=debug,
        key_refresh_nudge=key_refresh_nudge,
        key_refresh_delays_ms=key_refresh_delays_ms,
    )

    try:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            kind = parts[0]
            if kind == "Pointer":
                parsed = parse_pointer(parts)
                if not parsed:
                    continue
                uid, x, y, mask = parsed
                debug(f"parsed Pointer uid={uid} x={x} y={y} mask={mask}")
                if uid < 0:
                    continue
                helper.handle_pointer(x, y, mask)
            elif kind == "Keysym":
                parsed = parse_keysym(parts)
                if not parsed:
                    continue
                uid, down, name = parsed
                debug(f"parsed Keysym uid={uid} down={down} name={name!r}")
                if uid < 0:
                    continue
                helper.handle_keysym(down, name)
    except KeyboardInterrupt:
        pass
    finally:
        debug("shutdown")
        helper.close()


if __name__ == "__main__":
    main()
