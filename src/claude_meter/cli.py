"""claude-meter command-line interface."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from claude_meter import __version__, config, loop, service
from claude_meter.auth import AuthError, get_access_token
from claude_meter.usage import fetch_usage

_KNOWN_SERVICES = ["claude", "copilot"]


def _cmd_run(_args) -> int:
    cfg = config.load()
    loop.run(cfg)
    return 0


def _cmd_configure(args) -> int:
    cfg = config.load()
    if args.device_host:
        cfg.device_host = args.device_host
    if args.mode:
        cfg.mode = args.mode
    if args.transport:
        cfg.transport = args.transport
    if args.push_interval is not None:
        cfg.push_interval_sec = args.push_interval
    if args.force_push is not None:
        cfg.force_push_sec = args.force_push
    if args.image_dwell is not None:
        cfg.image_dwell_sec = args.image_dwell
    if args.theme_switch:
        cfg.theme_switch = args.theme_switch
    if args.services:
        svcs = [s.strip() for s in args.services.split(",") if s.strip()]
        unknown = [s for s in svcs if s not in _KNOWN_SERVICES]
        if unknown:
            print(f"unknown service(s): {unknown}. Known: {_KNOWN_SERVICES}",
                  file=sys.stderr)
            return 2
        cfg.services = svcs
    if args.github_token:
        cfg.github_token = args.github_token
    if args.copilot_org:
        orgs, tokens = [], {}
        for part in args.copilot_org.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                org, tok = part.split(":", 1)
                orgs.append(org)
                tokens[org] = tok
            else:
                orgs.append(part)
        cfg.copilot_orgs = orgs
        if tokens:
            cfg.copilot_org_tokens.update(tokens)
    p = config.save(cfg)
    print(f"wrote {p}")
    print(json.dumps(asdict(cfg), indent=2))
    return 0


def _cmd_show(_args) -> int:
    cfg = config.load()
    print(f"# {config.config_path()}")
    print(json.dumps(asdict(cfg), indent=2))
    return 0


def _cmd_check(_args) -> int:
    """Verify auth + API + device reachability without looping."""
    try:
        _, org = get_access_token()
        print(f"auth:   ok (org={org})")
    except AuthError as e:
        print(f"auth:   FAIL — {e}", file=sys.stderr)
        return 2

    try:
        data = fetch_usage()
        five = (data.get("five_hour") or {}).get("utilization")
        week = (data.get("seven_day") or {}).get("utilization")
        print(f"usage:  ok (5h={five}%, 7d={week}%)")
    except Exception as e:
        print(f"usage:  FAIL — {e}", file=sys.stderr)
        return 2

    cfg = config.load()
    print(f"config: {config.config_path()}")
    print(f"        device={cfg.device_host} mode={cfg.mode} "
          f"interval={cfg.push_interval_sec}s")
    return 0


def _cmd_install_service(_args) -> int:
    path = service.install()
    print(f"installed {path}")
    return 0


def _cmd_uninstall_service(_args) -> int:
    path = service.uninstall()
    if path is None:
        print("no service installed")
    else:
        print(f"removed {path}")
    return 0


def _cmd_status(_args) -> int:
    print(service.status())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claude-meter",
        description="Push Claude Code usage to a tiny screen.",
    )
    p.add_argument("--version", action="version", version=f"claude-meter {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("run",   help="Run the push loop in the foreground").set_defaults(
        func=_cmd_run)
    sub.add_parser("check", help="Verify auth + API + config").set_defaults(
        func=_cmd_check)
    sub.add_parser("show",  help="Print the current config").set_defaults(
        func=_cmd_show)

    pc = sub.add_parser("configure", help="Update config values")
    pc.add_argument("--device-host",   help="IP or hostname of the clock, e.g. 192.168.1.50")
    pc.add_argument("--mode",          choices=["gif80", "photo240"])
    pc.add_argument("--transport",     choices=["geekmagic", "geekmagic-ultra"])
    pc.add_argument("--push-interval", type=int, dest="push_interval",
                    help="seconds between pushes (default 60)")
    pc.add_argument("--force-push",    type=int, dest="force_push",
                    help="seconds between re-pushes of unchanged values (default 600)")
    pc.add_argument("--image-dwell",   type=int, dest="image_dwell",
                    help="geekmagic-ultra: seconds to show usage image before "
                         "restoring weather theme (0 = stay on image, default 30)")
    pc.add_argument("--theme-switch",  choices=["client", "firmware"],
                    dest="theme_switch",
                    help="geekmagic-ultra: who switches the screen to the usage "
                         "card. 'client' (default) flips to Photo Album and back; "
                         "'firmware' only uploads the image and leaves switching "
                         "to the device's own theme auto-rotation (enable it in "
                         "the device web UI)")
    pc.add_argument("--services",
                    help=f"comma-separated list of services to cycle through "
                         f"(default: claude). Known: {', '.join(_KNOWN_SERVICES)}")
    pc.add_argument("--github-token", dest="github_token",
                    help="GitHub PAT required for the 'copilot' service "
                         "(scope: manage_billing:copilot or read:user)")
    pc.add_argument("--copilot-org",  dest="copilot_org",
                    help="comma-separated GitHub org names for Copilot org-plan "
                         "metrics (seat utilization + acceptance rate). Each org "
                         "becomes its own cycling slot. Append :token to supply "
                         "a per-org PAT (e.g. org-a:ghp_xxx,org-b:ghp_yyy); "
                         "orgs without a token fall back to --github-token. "
                         "Omit entirely for individual subscription status.")
    pc.set_defaults(func=_cmd_configure)

    sub.add_parser("install-service",
                   help="Install as launchd/systemd user service").set_defaults(
        func=_cmd_install_service)
    sub.add_parser("uninstall-service",
                   help="Remove the installed service").set_defaults(
        func=_cmd_uninstall_service)
    sub.add_parser("service-status",
                   help="Show status of the installed service").set_defaults(
        func=_cmd_status)

    return p


def main() -> None:
    args = build_parser().parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
