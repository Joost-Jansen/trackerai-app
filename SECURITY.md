# Security

## Reporting a vulnerability

Please report vulnerabilities privately, not in a public issue. Use GitHub's private vulnerability reporting: open the
[Security tab](https://github.com/Joost-Jansen/trackerai-app/security) and choose **Report a vulnerability**. Describe
what you found, how to reproduce it and what an attacker could do with it.

You can expect a first reply within a week. Once a fix is out, I am happy to credit you in the advisory.

## Scope

- The code in this repository: health-tracker, wealth-tracker, trackerai and the shared packages.
- The instance at [trackerai.nl](https://trackerai.nl) and its subdomains.

Out of scope: third-party services the apps talk to (Garmin, Wahoo, Enable Banking, Yahoo Finance, Anthropic) and
installations someone else runs from this code.

## What is already in place

Secret scanning with push protection, GitGuardian on pull requests, and shared security conventions for both backends
(`packages/websec`: rate limits, security headers, CSRF origin check, log redaction, upload checks). See
[docs/CI.md](docs/CI.md) for the checks every pull request passes.
