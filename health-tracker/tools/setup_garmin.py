"""One-time Garmin login; stores the session tokens as the GARMINTOKENS repo secret.

Run it yourself in a terminal (it asks for your password and MFA code):

    .venv/bin/python tools/setup_garmin.py

Your password is only sent to Garmin; it is not stored. Re-run when the sync reports a Garmin login error.
"""

import os
import getpass
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from garminconnect import Garmin  # noqa: E402

PROJECT = os.environ.get("RAILWAY_PROJECT_ID", "")  # your Railway project id


def set_railway(name: str, value: str) -> None:
    subprocess.run(["railway", "link", "-p", PROJECT, "-e", "production", "-s", "sync"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["railway", "variable", "set", name, "--stdin", "-s", "sync", "-e", "production", "--skip-deploys"],
                   input=value, text=True, check=True, stdout=subprocess.DEVNULL)
    print(f"{name} gezet op Railway-service sync")


def main() -> None:
    email = input("Garmin e-mail: ").strip()
    password = getpass.getpass("Garmin wachtwoord (niet zichtbaar): ")
    api = Garmin(email, password, prompt_mfa=lambda: input("MFA-code: ").strip())
    api.login()
    # The sync tries its encrypted database copy first and falls back to this fresh login if that copy is stale.
    set_railway("GARMINTOKENS", api.client.dumps())


if __name__ == "__main__":
    main()
