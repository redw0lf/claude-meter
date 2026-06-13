"""HTTP upload to a GeeKmagic SmallTV-Ultra (V9 firmware).

The Ultra firmware (V9.x) uses a two-step API that differs from the
original SmallTV:

  1. POST /doUpload?dir=/image/   — multipart field "file", filename kept
  2. GET  /set?img=/image/<name>  — activate the uploaded file on-screen
  3. GET  /set?theme=<n>          — switch active theme

Theme numbers (from the device web UI):
  1 = Weather Clock Today   2 = Weather Forecast   3 = Photo Album

Who switches the screen is controlled by theme_switch:

  "client"   — after each *changed* upload, switch to Photo Album so the
               new card is visible, then restore the weather theme
               image_dwell_sec seconds later (0 = stay on the image).
  "firmware" — never touch themes. Only upload + activate the image and
               let the device's own theme auto-rotation (enabled in its
               web UI) cycle the Photo Album into view. Cheapest option
               for the device: zero extra requests, no forced UI rebuilds.

The device is an ESP8266-class MCU: a handful of LWIP sockets, a small
heap, and flash writes that block its main loop. Every request therefore
sends Connection: close (so the firmware frees the socket immediately),
successive requests are paced apart (so the watchdog isn't starved while
it commits flash), and all device I/O is serialized behind a lock (so the
dwell-restore timer never opens a second concurrent connection).
"""
from __future__ import annotations

import hashlib
import threading
import time

import requests
import urllib3.exceptions

# The Ultra firmware sends duplicate Content-Length headers in its HTTP
# responses after a successful write.  Newer urllib3/requests versions treat
# this as an error; older ones silently ignore it.  Catch both spellings so
# the transport works across library versions.
_INVALID_HEADER = (
    requests.exceptions.InvalidHeader,
    urllib3.exceptions.InvalidHeader,
)

_FILENAME      = "claude-meter.jpg"
_DIR           = "/image/"
_THEME_WEATHER = 1
_THEME_PHOTO   = 3

# Ask the firmware to drop the socket as soon as it has answered; its LWIP
# stack only has a handful of TCP slots and keep-alive leaks them.
_HEADERS = {"Connection": "close"}

# Gap between successive requests. Flash writes block the device's main
# loop; a follow-up request fired back-to-back can starve its watchdog.
_REQUEST_GAP_SEC = 0.5


class GeekmagicUltraTransport:
    def __init__(self, host: str, image_dwell_sec: int = 30,
                 theme_switch: str = "client"):
        if not host.startswith("http"):
            host = f"http://{host}"
        self._base         = host.rstrip("/")
        self._dwell        = image_dwell_sec
        self._theme_switch = theme_switch
        self._restore_timer: threading.Timer | None = None
        self._last_hash: str = ""
        self._io = threading.Lock()   # one connection to the device at a time

    def push(self, payload: bytes) -> int:
        digest = hashlib.md5(payload).hexdigest()
        if digest == self._last_hash:
            # Device already has and shows this exact image; nothing to do.
            return 0

        with self._io:
            self._upload(payload)
            time.sleep(_REQUEST_GAP_SEC)
            self._set(img=_DIR + _FILENAME)
        self._last_hash = digest

        if self._theme_switch == "client":
            time.sleep(_REQUEST_GAP_SEC)
            with self._io:
                self._set(theme=_THEME_PHOTO)
            # After dwell seconds, restore the weather theme.
            if self._dwell > 0:
                if self._restore_timer is not None:
                    self._restore_timer.cancel()
                self._restore_timer = threading.Timer(
                    self._dwell, self._restore_weather
                )
                self._restore_timer.daemon = True
                self._restore_timer.start()

        return len(payload)

    def _upload(self, payload: bytes) -> None:
        # The Ultra firmware often sends duplicate Content-Length headers in
        # its response — urllib3 raises InvalidHeader even with stream=True.
        # Treat that as a successful upload since the device has already
        # written the file by the time it sends the response.
        try:
            resp = requests.post(
                f"{self._base}/doUpload",
                params={"dir": _DIR},
                files={"file": (_FILENAME, payload, "image/jpeg")},
                headers=_HEADERS,
                timeout=(5, 15),
                stream=True,
            )
            try:
                resp.raise_for_status()
            finally:
                resp.close()
        except _INVALID_HEADER:
            pass  # malformed response headers; upload already committed

    def _restore_weather(self) -> None:
        try:
            with self._io:
                self._set(theme=_THEME_WEATHER)
        except Exception:
            pass  # best-effort; loop will retry on next push cycle

    def _set(self, **params) -> None:
        try:
            r = requests.get(
                f"{self._base}/set", params=params, headers=_HEADERS,
                timeout=(5, 10), stream=True,
            )
            try:
                r.raise_for_status()
            finally:
                r.close()
        except _INVALID_HEADER:
            pass  # malformed response headers; command already applied
