"""Set the dashboard login on Railway: username, bcrypt hash of your password and a fresh signing key.

Run it yourself in a terminal (it asks for the password twice, nothing is shown or stored locally):

    .venv/bin/python tools/set_dashboard_password.py

Values go to Railway via stdin of the Railway CLI, so they never appear in shell history or process lists.
Setting a new signing key logs out every open session.
"""

import os
import getpass
import secrets
import subprocess

import bcrypt

PROJECT = os.environ.get("RAILWAY_PROJECT_ID", "")  # your Railway project id
SERVICE = "web"
ENVIRONMENT = "production"


def railway_set(name: str, value: str, deploy: bool) -> None:
    cmd = ["railway", "variable", "set", name, "--stdin", "-s", SERVICE, "-e", ENVIRONMENT]
    if not deploy:
        cmd.append("--skip-deploys")
    subprocess.run(cmd, input=value, text=True, check=True, stdout=subprocess.DEVNULL)
    print(f"{name} gezet")


def main() -> None:
    subprocess.run(["railway", "link", "-p", PROJECT, "-e", ENVIRONMENT, "-s", SERVICE], check=True, stdout=subprocess.DEVNULL)
    user = input("Gebruikersnaam [joost]: ").strip() or "joost"
    password = getpass.getpass("Nieuw wachtwoord (min. 12 tekens, niet zichtbaar): ")
    if len(password) < 12:
        raise SystemExit("Te kort: kies minimaal 12 tekens.")
    if getpass.getpass("Nog een keer: ") != password:
        raise SystemExit("De twee wachtwoorden verschillen.")
    railway_set("TRAINING_USER", user, deploy=False)
    railway_set("TRAINING_PASSWORD_HASH", bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode(), deploy=False)
    railway_set("TRAINING_JWT_SECRET", secrets.token_hex(32), deploy=True)
    print("Klaar. Railway herstart de site met de nieuwe login.")


if __name__ == "__main__":
    main()
