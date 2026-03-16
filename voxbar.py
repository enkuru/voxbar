"""Voxbar — macOS menu bar voice chat app for Claude.

Features:
  - Click icon to open/close settings popover
  - Global Fn double-tap hotkey (requires Accessibility permissions)
  - Inline menu bar timer during calls
"""

import json
import logging
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSApplicationActivationPolicyAccessory,
    NSAttributedString,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSFlagsChangedMask,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImage,
    NSKeyDownMask,
    NSLeftMouseDownMask,
    NSMakeRect,
    NSObject,
    NSPopover,
    NSPopoverBehaviorApplicationDefined,
    NSRightMouseDownMask,
    NSRunningApplication,
    NSSize,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSViewController,
    NSWorkspace,
)
from Foundation import NSURL
from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventKeyDown,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
)
from objc import protocolNamed
from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log = logging.getLogger("voxbar")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = Path(os.environ.get("VOXBAR_CONFIG", str(SCRIPT_DIR / "config.json")))
SIGNAL_PATH = SCRIPT_DIR / ".call_signal"
CLICLICK = shutil.which("cliclick") or "/opt/homebrew/bin/cliclick"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.voxbar.agent.plist"

FN_KEY_MASK = 0x800000
ESC_KEYCODE = 53
NS_MAX_Y_EDGE = 3  # NSMaxYEdge — popover appears below the status item

FN_HOLD_MS = 500  # ms to hold Fn after double-tap to enter push-to-talk
FOCUS_POLL_INTERVAL = 0.5
SIGNAL_POLL_INTERVAL = 0.5
TYPING_POLL_INTERVAL = 0.5
TYPING_SETTLE_SECS = 0.8
TYPING_TIMEOUT_POLLS = 60
TIMER_UPDATE_INTERVAL = 1.0
ICON_ANIM_INTERVAL = 0.2

# Delays for sequencing keypress simulation and focus switching (seconds)
FOCUS_SETTLE_DELAY = 0.15
WISPR_SETTLE_DELAY = 0.3
PROCESS_STEP_DELAY = 0.2

# UI sound paths
SOUNDS = {
    "start": "/System/Library/Sounds/Tink.aiff",
    "end": "/System/Library/Sounds/Pop.aiff",
    "cancel": "/System/Library/Sounds/Basso.aiff",
}

DEFAULT_CONFIG = {
    "target_app": "iTerm2",
    "wispr": {"cliclick_handsfree": "kd:fn,cmd ku:fn,cmd"},
    "ring_sound": "/System/Library/Sounds/Ping.aiff",
    "ring_interval": 2,
    "auto_enter": True,
    "fn_hotkey_enabled": True,
    "double_tap_ms": 400,
    "sounds_enabled": True,
    "launch_at_login": False,
}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def get_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        log.warning("Config load failed (%s), using defaults", e)
        return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
            f.write("\n")
    except OSError as e:
        log.error("Config save failed: %s", e)


def _ensure_config() -> None:
    """Copy config.example.json on first run if config.json is missing."""
    if CONFIG_PATH.exists():
        return
    example = SCRIPT_DIR / "config.example.json"
    if example.exists():
        CONFIG_PATH.write_text(example.read_text())
        log.info("Created %s from example", CONFIG_PATH)
    else:
        save_config(dict(DEFAULT_CONFIG))
        log.info("Created %s with defaults", CONFIG_PATH)


# ---------------------------------------------------------------------------
# Terminal / Wispr helpers
# ---------------------------------------------------------------------------
def trigger_wispr() -> None:
    config = get_config()
    keys = config.get("wispr", {}).get("cliclick_handsfree", "kd:fn,cmd ku:fn,cmd")
    subprocess.run([CLICLICK] + keys.split(), check=False)


def focus_terminal() -> None:
    config = get_config()
    app_name = config.get("target_app", "iTerm2")
    try:
        for a in NSWorkspace.sharedWorkspace().runningApplications():
            if app_name.lower() in str(a.localizedName()).lower():
                a.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                return
    except Exception:
        log.warning("Failed to focus %s via NSWorkspace, trying osascript", app_name)
    subprocess.run(
        ["osascript", "-e", f'tell application "{app_name}" to activate'],
        check=False,
    )


def send_enter() -> None:
    config = get_config()
    app_name = config.get("target_app", "iTerm2")
    subprocess.run(
        [
            "osascript",
            "-e",
            f'tell application "{app_name}" to tell current session of current window to write text (ASCII character 10)',
        ],
        check=False,
    )


def _get_terminal_tail() -> str:
    config = get_config()
    app_name = config.get("target_app", "iTerm2")
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                f'tell application "{app_name}" to tell current session of current window to return contents',
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
        )
        return result.stdout[-500:] if result.stdout else ""
    except Exception:
        return ""


def wait_for_typing_then_enter(baseline: Optional[str] = None) -> None:
    prev = baseline if baseline is not None else _get_terminal_tail()
    typing_started = False
    last_change = time.time()
    for _ in range(TYPING_TIMEOUT_POLLS):
        time.sleep(TYPING_POLL_INTERVAL)
        current = _get_terminal_tail()
        if current != prev:
            typing_started = True
            last_change = time.time()
            prev = current
        elif typing_started and (time.time() - last_change) >= TYPING_SETTLE_SECS:
            send_enter()
            return
    if typing_started:
        send_enter()


# ---------------------------------------------------------------------------
# WKScriptMessageHandler
# ---------------------------------------------------------------------------
WKScriptMessageHandlerProtocol = protocolNamed("WKScriptMessageHandler")


class MessageHandler(NSObject, protocols=[WKScriptMessageHandlerProtocol]):
    app = objc.ivar()

    def userContentController_didReceiveScriptMessage_(
        self, controller: Any, message: Any
    ) -> None:
        body = message.body()
        action = body.get("action", "") if body else ""
        if action == "start_call":
            self.app.on_start_call()
        elif action == "hang_up":
            self.app.on_hang_up()
        elif action == "cancel_call":
            self.app.on_cancel_call()
        elif action == "reject_call":
            self.app.on_reject_call()
        elif action == "silence_call":
            self.app.on_silence_call()
        elif action == "toggle_launch_at_login":
            enabled = body.get("enabled", False)
            self.app.on_toggle_launch_at_login(enabled)
        elif action == "set_config":
            key = body.get("key", "")
            value = body.get("value")
            if key:
                config = get_config()
                config[key] = value
                save_config(config)
        elif action == "quit":
            NSApplication.sharedApplication().terminate_(None)


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------
class VoxbarApp(NSObject):
    def init(self):
        self = objc.super(VoxbarApp, self).init()
        if self is None:
            return None

        # Call state
        self._call_active = False
        self._ringing = False

        # Focus tracking
        self._last_external_app = None
        self._restore_target = None
        self._own_bundle_id = (
            NSRunningApplication.currentApplication().bundleIdentifier()
            or "com.voxbar"
        )
        self._own_pid = os.getpid()

        # Inline timer state
        self._inline_timer_running = False
        self._inline_timer_start = 0

        # Fn hotkey state
        self._fn_last_down = 0
        self._fn_is_down = False
        self._fn_other_key_pressed = False
        self._fn_ptt_mode = False
        self._fn_hold_timer = None
        self._fn_suppressed = False
        self._fn_ignore_next_release = False

        self._setup_status_item()
        self._setup_popover()
        self._setup_outside_click_monitor()
        self._start_signal_watcher()
        self._start_focus_poller()
        self._setup_fn_monitor()
        self._setup_escape_tap()

        log.info("Voxbar initialized")
        return self

    # ------------------------------------------------------------------
    # Status item
    # ------------------------------------------------------------------
    def _setup_status_item(self) -> None:
        sb = NSStatusBar.systemStatusBar()
        self._status_item = sb.statusItemWithLength_(NSVariableStatusItemLength)
        button = self._status_item.button()
        self._update_icon("orange")
        button.setToolTip_("Voxbar — Ready")
        button.setAction_("iconClicked:")
        button.setTarget_(self)

    # ------------------------------------------------------------------
    # Icon rendering
    # ------------------------------------------------------------------
    def _make_waveform_icon(
        self,
        color_rgba: tuple,
        is_template: bool = False,
        bar_heights: Optional[list] = None,
    ) -> Any:
        """Draw a 5-bar waveform icon for the menu bar."""
        w, h = 18, 18
        img = NSImage.alloc().initWithSize_(NSSize(w, h))
        img.lockFocus()

        color = NSColor.colorWithRed_green_blue_alpha_(*color_rgba)
        color.set()

        if bar_heights is None:
            bar_heights = [0.35, 0.6, 1.0, 0.7, 0.4]
        bar_w = 2.0
        gap = 1.5
        total_w = len(bar_heights) * bar_w + (len(bar_heights) - 1) * gap
        start_x = (w - total_w) / 2
        padding_y = 3

        for i, frac in enumerate(bar_heights):
            bar_h = frac * (h - padding_y * 2)
            x = start_x + i * (bar_w + gap)
            y = (h - bar_h) / 2
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, y, bar_w, bar_h), 1.0, 1.0
            )
            path.fill()

        img.unlockFocus()
        img.setTemplate_(is_template)
        return img

    def _update_icon(self, color: str, text: Optional[str] = None) -> None:
        if color == "green":
            rgba = (0.20, 0.78, 0.35, 1.0)
        elif color == "orange":
            rgba = (0.85, 0.47, 0.34, 1.0)
        else:
            rgba = (0.55, 0.55, 0.60, 1.0)

        button = self._status_item.button()

        if text:
            icon = self._make_waveform_icon(rgba)
            button.setImage_(icon)
            attrs = {
                NSForegroundColorAttributeName: NSColor.colorWithRed_green_blue_alpha_(*rgba),
                NSFontAttributeName: NSFont.monospacedSystemFontOfSize_weight_(11.0, 0.0),
            }
            title = NSAttributedString.alloc().initWithString_attributes_(
                f" {text}", attrs
            )
            button.setAttributedTitle_(title)
        else:
            is_idle = color == "orange"
            if is_idle:
                icon = self._make_waveform_icon((0, 0, 0, 1), is_template=True)
            else:
                icon = self._make_waveform_icon(rgba)
            button.setImage_(icon)
            button.setAttributedTitle_(NSAttributedString.alloc().initWithString_(""))

    # ------------------------------------------------------------------
    # Popover
    # ------------------------------------------------------------------
    @objc.typedSelector(b"v@:@")
    def iconClicked_(self, sender) -> None:
        if self._popover.isShown():
            self._popover.close()
        else:
            self._open_popover()

    def _open_popover(self) -> None:
        if not self._call_active:
            self._restore_target = self._last_external_app
        self.eval_js("resetToMain()")
        if self._call_active:
            self.eval_js("setCallState('in-call')")
        else:
            self.eval_js("setCallState('idle')")
        self._popover.showRelativeToRect_ofView_preferredEdge_(
            self._status_item.button().bounds(),
            self._status_item.button(),
            NS_MAX_Y_EDGE,
        )
        self._sync_settings_state()

    def _setup_popover(self) -> None:
        self._popover = NSPopover.alloc().init()
        self._popover.setBehavior_(NSPopoverBehaviorApplicationDefined)
        self._popover.setContentSize_((180, 200))

        wk_config = WKWebViewConfiguration.alloc().init()
        content_controller = WKUserContentController.alloc().init()

        handler = MessageHandler.alloc().init()
        handler.app = self
        self._message_handler = handler

        content_controller.addScriptMessageHandler_name_(handler, "voxbar")
        wk_config.setUserContentController_(content_controller)

        self._webview = WKWebView.alloc().initWithFrame_configuration_(
            ((0, 0), (180, 200)), wk_config
        )

        html_path = SCRIPT_DIR / "call_ui.html"
        html_content = html_path.read_text(encoding="utf-8")
        base_url = NSURL.fileURLWithPath_(str(SCRIPT_DIR))
        self._webview.loadHTMLString_baseURL_(html_content, base_url)

        vc = NSViewController.alloc().init()
        vc.setView_(self._webview)
        self._popover.setContentViewController_(vc)
        self._vc = vc

    def eval_js(self, script: str) -> None:
        self._webview.evaluateJavaScript_completionHandler_(script, None)

    def _setup_outside_click_monitor(self) -> None:
        def handler(event):
            if self._popover.isShown() and not self._call_active:
                self._popover.close()

        self._click_monitor = (
            NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSLeftMouseDownMask | NSRightMouseDownMask, handler
            )
        )

    # ------------------------------------------------------------------
    # Focus tracking
    # ------------------------------------------------------------------
    def _start_focus_poller(self) -> None:
        def poll():
            while True:
                if not self._call_active:
                    try:
                        front = NSWorkspace.sharedWorkspace().frontmostApplication()
                        if front and front.processIdentifier() != self._own_pid:
                            self._last_external_app = front
                    except Exception:
                        pass
                time.sleep(FOCUS_POLL_INTERVAL)

        threading.Thread(target=poll, daemon=True).start()

    def restore_focus(self) -> None:
        target = self._restore_target or self._last_external_app
        if target:
            target.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        self._restore_target = None

    @objc.typedSelector(b"v@:@")
    def doRestoreFocus_(self, _=None) -> None:
        self.restore_focus()

    # ------------------------------------------------------------------
    # Fn double-tap hotkey
    # ------------------------------------------------------------------
    def _setup_fn_monitor(self) -> None:
        try:
            def key_handler(event):
                if self._fn_is_down:
                    self._fn_other_key_pressed = True

            self._fn_key_monitor = (
                NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                    NSKeyDownMask, key_handler
                )
            )

            def fn_handler(event):
                if self._fn_suppressed:
                    return
                if not get_config().get("fn_hotkey_enabled", True):
                    return
                flags = event.modifierFlags()
                fn_down = bool(flags & FN_KEY_MASK)

                if fn_down and not self._fn_is_down:
                    self._fn_is_down = True
                    self._fn_other_key_pressed = False
                    now = time.time() * 1000

                    if self._call_active:
                        return

                    elapsed = now - self._fn_last_down
                    self._fn_last_down = now

                    double_tap_ms = get_config().get("double_tap_ms", 400)
                    if elapsed < double_tap_ms:
                        self._fn_ignore_next_release = True
                        self._restore_target = self._last_external_app
                        self.performSelectorOnMainThread_withObject_waitUntilDone_(
                            "fnStartCall:", None, False
                        )
                        if self._fn_hold_timer:
                            self._fn_hold_timer.cancel()

                        def check_hold():
                            if self._fn_is_down and self._call_active:
                                self._fn_ptt_mode = True
                                self._fn_ignore_next_release = False

                        self._fn_hold_timer = threading.Timer(
                            FN_HOLD_MS / 1000, check_hold
                        )
                        self._fn_hold_timer.start()

                elif not fn_down and self._fn_is_down:
                    self._fn_is_down = False
                    if self._fn_hold_timer:
                        self._fn_hold_timer.cancel()
                        self._fn_hold_timer = None

                    if self._fn_ignore_next_release:
                        self._fn_ignore_next_release = False
                        return

                    if self._fn_ptt_mode and self._call_active:
                        self._fn_ptt_mode = False
                        self.performSelectorOnMainThread_withObject_waitUntilDone_(
                            "fnHangUp:", None, False
                        )
                        return

                    if self._call_active and not self._fn_other_key_pressed:
                        self.performSelectorOnMainThread_withObject_waitUntilDone_(
                            "fnHangUp:", None, False
                        )

            self._fn_flags_monitor = (
                NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                    NSFlagsChangedMask, fn_handler
                )
            )
        except Exception as e:
            log.warning("Fn monitor setup failed (Accessibility?): %s", e)

    # ------------------------------------------------------------------
    # Escape key tap (low-level CGEventTap, catches before Wispr)
    # ------------------------------------------------------------------
    def _setup_escape_tap(self) -> None:
        try:
            def callback(proxy, event_type, event, refcon):
                keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                if keycode == ESC_KEYCODE and self._call_active:
                    self.performSelectorOnMainThread_withObject_waitUntilDone_(
                        "fnCancelCallNoEsc:", None, False
                    )
                return event

            tap = CGEventTapCreate(
                kCGSessionEventTap,
                kCGHeadInsertEventTap,
                0,  # active tap (not passive)
                CGEventMaskBit(kCGEventKeyDown),
                callback,
                None,
            )

            if tap:
                source = CFMachPortCreateRunLoopSource(None, tap, 0)
                CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
                CGEventTapEnable(tap, True)
                self._escape_tap = tap
                self._escape_source = source
        except Exception as e:
            log.warning("Escape tap setup failed (Accessibility?): %s", e)

    @objc.typedSelector(b"v@:@")
    def fnStartCall_(self, _=None) -> None:
        if not self._call_active:
            self.on_start_call()

    @objc.typedSelector(b"v@:@")
    def fnHangUp_(self, _=None) -> None:
        if self._call_active:
            self.on_hang_up()

    # ------------------------------------------------------------------
    # Inline menu bar timer
    # ------------------------------------------------------------------
    def _start_inline_timer(self) -> None:
        self._inline_timer_start = time.time()
        self._inline_timer_running = True

        def timer_loop():
            while self._inline_timer_running:
                elapsed = int(time.time() - self._inline_timer_start)
                mins = elapsed // 60
                secs = elapsed % 60
                text = f"{mins:02d}:{secs:02d}"
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "updateInlineTimer:", text, False
                )
                time.sleep(TIMER_UPDATE_INTERVAL)

        def anim_loop():
            while self._inline_timer_running:
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "animateIcon:", None, False
                )
                time.sleep(ICON_ANIM_INTERVAL)

        threading.Thread(target=timer_loop, daemon=True).start()
        threading.Thread(target=anim_loop, daemon=True).start()

    def _stop_inline_timer(self) -> None:
        self._inline_timer_running = False

    @objc.typedSelector(b"v@:@")
    def animateIcon_(self, _=None) -> None:
        if self._call_active:
            bars = [random.uniform(0.2, 1.0) for _ in range(5)]
            icon = self._make_waveform_icon((0.20, 0.78, 0.35, 1.0), bar_heights=bars)
            self._status_item.button().setImage_(icon)

    @objc.typedSelector(b"v@:@")
    def updateInlineTimer_(self, text) -> None:
        if self._call_active:
            self._update_icon("green", str(text))

    @objc.typedSelector(b"v@:@")
    def resetIcon_(self, _=None) -> None:
        self._update_icon("orange")
        self._status_item.button().setToolTip_("Voxbar — Ready")

    # ------------------------------------------------------------------
    # Call lifecycle
    # ------------------------------------------------------------------
    def on_start_call(self) -> None:
        self._stop_ringing()
        self._call_active = True
        self._update_icon("green", "00:00")
        self._start_inline_timer()
        self._play_sound("start")
        self._status_item.button().setToolTip_("Voxbar — Listening")
        log.info("Call started")

        def activate():
            focus_terminal()
            time.sleep(FOCUS_SETTLE_DELAY)
            self._fn_suppressed = True
            trigger_wispr()
            time.sleep(WISPR_SETTLE_DELAY)
            self._fn_suppressed = False
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "notifyListening:", None, False
            )

        threading.Thread(target=activate, daemon=True).start()

    @objc.typedSelector(b"v@:@")
    def notifyListening_(self, _=None) -> None:
        self.eval_js("setCallState('in-call')")

    def on_hang_up(self) -> None:
        if not self._call_active:
            return
        self._call_active = False
        self._stop_inline_timer()
        self._update_icon("orange", "...")
        self._play_sound("end")
        self._status_item.button().setToolTip_("Voxbar — Processing")
        self._popover.close()
        log.info("Call ended")

        def process():
            time.sleep(PROCESS_STEP_DELAY)
            focus_terminal()
            time.sleep(PROCESS_STEP_DELAY)

            baseline = _get_terminal_tail()

            self._fn_suppressed = True
            trigger_wispr()
            time.sleep(WISPR_SETTLE_DELAY)
            self._fn_suppressed = False

            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "resetIcon:", None, False
            )

            config = get_config()
            if config.get("auto_enter", True):
                wait_for_typing_then_enter(baseline)

            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "doRestoreFocus:", None, False
            )

        threading.Thread(target=process, daemon=True).start()

    def on_cancel_call(self, send_esc: bool = True) -> None:
        """Cancel call, optionally send Escape to Wispr, then restore focus."""
        if not self._call_active:
            return
        self._call_active = False
        self._stop_inline_timer()
        self._update_icon("orange")
        self._play_sound("cancel")
        self._status_item.button().setToolTip_("Voxbar — Ready")
        self._popover.close()
        self.eval_js("setCallState('idle')")
        log.info("Call cancelled")

        def process():
            time.sleep(PROCESS_STEP_DELAY)
            if send_esc:
                self._fn_suppressed = True
                subprocess.run([CLICLICK, "kp:esc"], check=False)
                time.sleep(WISPR_SETTLE_DELAY)
                self._fn_suppressed = False
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "doRestoreFocus:", None, False
            )

        threading.Thread(target=process, daemon=True).start()

    @objc.typedSelector(b"v@:@")
    def fnCancelCall_(self, _=None) -> None:
        if self._call_active:
            self.on_cancel_call(send_esc=True)

    @objc.typedSelector(b"v@:@")
    def fnCancelCallNoEsc_(self, _=None) -> None:
        if self._call_active:
            self.on_cancel_call(send_esc=False)

    def on_reject_call(self) -> None:
        self._stop_ringing()
        self._popover.close()
        self.eval_js("setCallState('idle')")

    def on_silence_call(self) -> None:
        self._stop_ringing()

    # ------------------------------------------------------------------
    # Sound & settings helpers
    # ------------------------------------------------------------------
    def _play_sound(self, name: str) -> None:
        config = get_config()
        if not config.get("sounds_enabled", True):
            return
        path = SOUNDS.get(name)
        if path:
            subprocess.Popen(
                ["afplay", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _sync_settings_state(self) -> None:
        config = get_config()
        js = "setSettings({autoEnter:%s,fnHotkey:%s,launchAtLogin:%s,sounds:%s,tapSpeed:%d})" % (
            "true" if config.get("auto_enter", True) else "false",
            "true" if config.get("fn_hotkey_enabled", True) else "false",
            "true" if config.get("launch_at_login", False) else "false",
            "true" if config.get("sounds_enabled", True) else "false",
            config.get("double_tap_ms", 400),
        )
        self.eval_js(js)

    # ------------------------------------------------------------------
    # Ringing
    # ------------------------------------------------------------------
    def _start_ringing(self) -> None:
        self._ringing = True
        config = get_config()
        sound = config.get("ring_sound", "/System/Library/Sounds/Ping.aiff")
        interval = config.get("ring_interval", 2)

        def ring_loop():
            while self._ringing:
                subprocess.run(["afplay", sound], check=False)
                time.sleep(interval)

        threading.Thread(target=ring_loop, daemon=True).start()

    def _stop_ringing(self) -> None:
        self._ringing = False

    # ------------------------------------------------------------------
    # Signal watcher (incoming calls from external processes)
    # ------------------------------------------------------------------
    def _start_signal_watcher(self) -> None:
        def watch():
            while True:
                if SIGNAL_PATH.exists():
                    try:
                        SIGNAL_PATH.read_text().strip()
                        SIGNAL_PATH.unlink()
                        self.performSelectorOnMainThread_withObject_waitUntilDone_(
                            "handleIncomingCall:", "Claude", False
                        )
                    except Exception:
                        pass
                time.sleep(SIGNAL_POLL_INTERVAL)

        threading.Thread(target=watch, daemon=True).start()

    @objc.typedSelector(b"v@:@")
    def handleIncomingCall_(self, name) -> None:
        self._ringing = True
        if not self._popover.isShown():
            self._popover.showRelativeToRect_ofView_preferredEdge_(
                self._status_item.button().bounds(),
                self._status_item.button(),
                NS_MAX_Y_EDGE,
            )
        safe_name = str(name).replace("'", "\\'") if name else "Claude"
        self.eval_js(f"setIncomingCall('{safe_name}')")
        self._start_ringing()

    # ------------------------------------------------------------------
    # Launch at login
    # ------------------------------------------------------------------
    def on_toggle_launch_at_login(self, enabled: bool) -> None:
        config = get_config()
        config["launch_at_login"] = enabled
        save_config(config)

        if enabled:
            self._install_launch_agent()
        else:
            PLIST_PATH.unlink(missing_ok=True)

    def _install_launch_agent(self) -> None:
        """Generate LaunchAgent plist with correct paths for this machine."""
        python_path = sys.executable
        script_path = str(Path(__file__).resolve())
        working_dir = str(Path(__file__).resolve().parent)
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.voxbar.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{script_path}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{working_dir}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardErrorPath</key>
    <string>/tmp/voxbar.err.log</string>
</dict>
</plist>"""
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        PLIST_PATH.write_text(plist)
        log.info("Installed LaunchAgent to %s", PLIST_PATH)


_voxbar_ref = None


def main() -> None:
    global _voxbar_ref
    _ensure_config()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    _voxbar_ref = VoxbarApp.alloc().init()

    app.run()


if __name__ == "__main__":
    main()
