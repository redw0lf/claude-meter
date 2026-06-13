"""Transports deliver rendered bytes to a physical display."""
from __future__ import annotations

from typing import Protocol


class Transport(Protocol):
    """Push rendered bytes somewhere visible."""

    def push(self, payload: bytes) -> int:
        """Send the payload. Return bytes-on-wire for logging."""


def get(name: str, **kwargs) -> Transport:
    if name == "geekmagic":
        from claude_meter.transports.geekmagic import GeekmagicTransport
        return GeekmagicTransport(host=kwargs["host"], mode=kwargs.get("mode", "gif80"))
    if name == "geekmagic-ultra":
        from claude_meter.transports.geekmagic_ultra import GeekmagicUltraTransport
        # pass only the kwargs this transport understands
        return GeekmagicUltraTransport(
            host=kwargs["host"],
            image_dwell_sec=kwargs.get("image_dwell_sec", 30),
            theme_switch=kwargs.get("theme_switch", "client"),
        )
    raise ValueError(f"unknown transport: {name!r}")
