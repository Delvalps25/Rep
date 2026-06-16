import argparse
import sys
import os
from pathlib import Path
from uais_core.hardware import probe_hardware
from uais_core.config import log, UAIS_VERSION

def _parser():
    parser = argparse.ArgumentParser(description=f"UAIS v{UAIS_VERSION}")
    parser.add_argument("--workspace", "-w", default="workspace", help="Path to UAIS workspace")
    parser.add_argument("--role", choices=["iot", "desktop", "pro", "cluster"], help="Override system role")

    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("probe", help="Hardware and role probe")
    sub.add_parser("install", help="Install dependencies")
    sub.add_parser("scaffold", help="Scaffold workspace")

    chat = sub.add_parser("chat", help="Interactive chat")
    chat.add_argument("--think", action="store_true", help="Enable reasoning")

    sub.add_parser("up", help="Start FastAPI server")
    sub.add_parser("doctor", help="System health check")

    return parser

def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)

    ws = Path(args.workspace)
    ws.mkdir(parents=True, exist_ok=True)

    hw = probe_hardware()

    if args.role:
        os.environ["UAIS_ROLE"] = args.role

    cmd = args.cmd
    if not cmd:
        print(f"UAIS v{UAIS_VERSION} - Workspace: {ws}")
        return

    if cmd == "probe":
        print(f"Hardware Tier: {hw.tier_label}")
    elif cmd == "doctor":
        print("Running doctor...")
    else:
        print(f"Command '{cmd}' not implemented in this version of the CLI.")

if __name__ == "__main__":
    main()
