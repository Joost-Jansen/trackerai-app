"""Web security building blocks for every trackerai backend: client IP behind trusted proxies, rate limits, security
headers, a CSRF origin check, log redaction and upload guards. Password rules and TOTP belong to the shared account
(packages/accounts).

Framework-generic on purpose (the standard library plus Starlette): nothing here imports the app around it; each app
wires it up.
"""
