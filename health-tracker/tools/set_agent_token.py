"""Create a new agent token for the training API. Run it yourself:

    .venv/bin/python tools/set_agent_token.py

Railway gets only the SHA-256 hash (TRAINING_AGENT_TOKEN_HASH). The token itself is shown once in your terminal;
put it where your agents read it (see docs/DEVELOPMENT.md, "Agents"). A new token replaces the old one.
"""

import os
import hashlib
import secrets
import subprocess

PROJECT = os.environ.get("RAILWAY_PROJECT_ID", "")  # your Railway project id


def main() -> None:
    token = "tr_" + secrets.token_urlsafe(32)
    subprocess.run(["railway", "link", "-p", PROJECT, "-e", "production", "-s", "web"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(
        ["railway", "variable", "set", "TRAINING_AGENT_TOKEN_HASH", "--stdin", "-s", "web", "-e", "production"],
        input=hashlib.sha256(token.encode()).hexdigest(),
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    print("TRAINING_AGENT_TOKEN_HASH gezet op Railway (web herstart).")
    print("Je nieuwe agent-token (wordt niet opgeslagen, kopieer hem nu):\n")
    print(token)


if __name__ == "__main__":
    main()
