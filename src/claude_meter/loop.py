"""Push loop: fetch usage, render, push, dedup, sleep."""
from __future__ import annotations

import datetime
import sys
import time

from claude_meter import providers, renderers, transports
from claude_meter.config import Config
from claude_meter.usage import RateLimited


def run(cfg: Config) -> None:
    if not cfg.device_host:
        raise SystemExit(
            "device_host is not set. Run `claude-meter configure "
            "--device-host <ip>` first."
        )
    renderer  = renderers.get(cfg.mode)
    transport = transports.get(
        cfg.transport,
        host=cfg.device_host,
        mode=cfg.mode,
        image_dwell_sec=cfg.image_dwell_sec,
        theme_switch=cfg.theme_switch,
    )
    provider_list = [providers.get(svc, cfg) for svc in cfg.services]

    # Per-provider dedup state.
    last_keys:    list[tuple | None] = [None] * len(provider_list)
    last_push_ts: list[float]        = [0.0]  * len(provider_list)

    provider_idx = 0
    logged_once  = False

    while True:
        sleep_for = cfg.push_interval_sec
        idx       = provider_idx % len(provider_list)
        provider  = provider_list[idx]

        try:
            card = provider.fetch()
            if not logged_once:
                print(f"first card from {card.title!r}: "
                      f"{card.row1_label}={card.row1_pct:.0f}%  "
                      f"{card.row2_label}={card.row2_pct:.0f}%", flush=True)
                logged_once = True

            key = (int(round(card.row1_pct)), int(round(card.row2_pct)))
            now = time.time()

            # Only touch the device when the numbers actually moved (or as a
            # periodic refresh). The clock is an ESP8266-class MCU; hammering
            # it with uploads/theme switches every cycle eventually hangs it.
            if last_keys[idx] == key and (now - last_push_ts[idx]) < cfg.force_push_sec:
                print(f"{_ts()} [{card.title}] "
                      f"{card.row1_label} {card.row1_pct:.0f}%  "
                      f"{card.row2_label} {card.row2_pct:.0f}%  "
                      f"unchanged, skipped", flush=True)
            else:
                payload = renderer.render(card)
                n = transport.push(payload)
                last_keys[idx]    = key
                last_push_ts[idx] = now
                print(f"{_ts()} [{card.title}] "
                      f"{card.row1_label} {card.row1_pct:.0f}%  "
                      f"{card.row2_label} {card.row2_pct:.0f}%  "
                      f"pushed {n}B ({cfg.mode})", flush=True)

        except KeyboardInterrupt:
            print("bye", flush=True)
            sys.exit(0)
        except RateLimited as e:
            sleep_for = max(e.retry_after, cfg.push_interval_sec)
            print(f"{_ts()} [warn] [{provider_list[idx].__class__.__name__}] "
                  f"429 rate limited, sleeping {sleep_for}s", flush=True)
        except Exception as e:
            print(f"{_ts()} [warn] [{provider_list[idx].__class__.__name__}] "
                  f"{type(e).__name__}: {e}", flush=True)

        provider_idx = (provider_idx + 1) % len(provider_list)
        time.sleep(sleep_for)


def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")
