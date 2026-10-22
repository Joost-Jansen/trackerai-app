"""Errors as codes (T25): the site shows them in the user's language, agents and scripts keep reading `detail`.

    raise ApiError(422, "password_too_short", min=10)

answers `{"detail": "wachtwoord van minimaal 10 tekens", "code": "password_too_short", "params": {"min": 10}}`.
`detail` is the Dutch text below (what the API always returned); the site renders `code` + `params` itself
(`web/lib/i18n`, `errors`). Add a code here and in both web catalogs in the same commit.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

MESSAGES: dict[str, str] = {
    # accounts (api/users.py)
    "not_logged_in": "niet ingelogd",
    "invalid_agent_token": "ongeldig agent-token",
    "admins_only": "alleen voor beheerders",
    "site_login_only": "alleen ingelogd op de site",
    "too_many_attempts": "te veel pogingen, probeer het over een kwartier opnieuw",
    "bad_credentials": "onjuiste gebruikersnaam of wachtwoord",
    "account_suspended": "dit account is geblokkeerd; neem contact op met de beheerder",
    "registration_closed": "registreren staat uit",
    "invalid_invite": "ongeldige of gebruikte uitnodigingscode",
    "invalid_username": "gebruikersnaam: 3-40 tekens, letters, cijfers, punt, streepje of underscore",
    "username_taken": "die gebruikersnaam bestaat al",
    "username_reserved": "die gebruikersnaam is gereserveerd",
    "example_read_only": "dit zijn voorbeeldgegevens: je kunt ze bekijken, niet wijzigen",
    "password_too_short": "wachtwoord van minimaal {min} tekens",
    "password_too_long": "wachtwoord van maximaal {max} tekens",
    "password_too_common": "dit wachtwoord staat op de lijst van veelgebruikte wachtwoorden; kies een ander",
    "password_is_username": "je wachtwoord mag niet je gebruikersnaam zijn",
    "consent_required": "geef toestemming voor het verwerken van je gezondheidsgegevens om een account te maken",
    "totp_required": "vul de code uit je authenticator-app of je e-mail in",
    "totp_invalid": "die code klopt niet (of is al gebruikt)",
    "totp_already_enabled": "inloggen in twee stappen staat al aan",
    "totp_not_set_up": "inloggen in twee stappen is nog niet ingesteld",
    "last_admin": "je bent de enige beheerder; maak eerst iemand anders beheerder",
    "account_busy": "er loopt nog een synchronisatie of import; probeer het over een paar minuten opnieuw",
    "csrf_origin": "verzoek vanaf een andere site geweigerd",
    "name_too_long": "naam van maximaal {max} tekens",
    "wrong_current_password": "huidig wachtwoord klopt niet",
    "invalid_locale": "taal is een van {options}",
    "user_not_found": "gebruiker niet gevonden",
    "cannot_demote_self": "je kunt je eigen beheerrechten niet intrekken of jezelf blokkeren",
    "cannot_delete_self": "je kunt jezelf niet verwijderen",
    "confirm_username": "typ de gebruikersnaam ter bevestiging",
    "invalid_registration_mode": "registratie is een van {options}",
    # the shared trackerai account (packages/accounts)
    "totp_setup_required": "stel eerst inloggen in twee stappen in",
    "totp_cannot_disable": "inloggen in twee stappen is verplicht voor dit account",
    "not_in_app": "dit account gebruikt health-tracker nog niet",
    "unknown_app": "onbekende app; kies uit: {options}",
    "app_not_available": "vraag de beheerder om toegang tot deze app",
    "app_leaving": "je gegevens in deze app worden nog verwijderd; probeer het over een minuut opnieuw",
    "account_not_found": "account niet gevonden",
    "email_code_sent": "we hebben een code gestuurd naar {to}. Vul die hier in",
    "email_invalid": "dat is geen e-mailadres",
    "email_taken": "dat adres hoort al bij een ander account",
    "email_unavailable": "mailen lukt nu niet; gebruik je authenticator-app of een reservecode",
    "email_codes_off": "codes per e-mail staan uit voor dit account",
    "too_many_codes": "te veel codes verstuurd. Probeer het over een kwartier opnieuw",
    "email_verify_required": "bevestig eerst je e-mailadres: vul de code uit de welkomstmail in",
    "email_already_verified": "je e-mailadres is al bevestigd",
    "accounts_key_missing": "de server heeft geen sleutel om inloggen in twee stappen veilig op te slaan (ACCOUNTS_ENCRYPTION_KEY)",
    # agent tokens (api/agent_tokens.py)
    "tokens_site_only": "alleen ingelogd op de site beheer je agent-tokens",
    "token_name_length": "naam van {min} tot {max} tekens",
    "too_many_tokens": "maximaal {max} tokens; trek er eerst een in",
    "token_not_found": "token niet gevonden",
    # Garmin (api/connections.py)
    "connections_site_only": "koppelingen beheer je ingelogd op de site",
    "no_encryption_key": "de server heeft geen sleutel om de koppeling veilig op te slaan (TOKEN_ENCRYPTION_KEY)",
    "missing_garmin_credentials": "vul e-mail en wachtwoord in",
    "garmin_rejected": "Garmin weigert de inlog: controleer e-mail en wachtwoord (of de MFA-code).",
    "garmin_rate_limited": "Garmin laat even geen nieuwe inlog toe (te veel pogingen). Probeer het over een kwartier opnieuw.",
    "garmin_failed": "Inloggen bij Garmin lukte niet. Probeer het later opnieuw.",
    "mfa_expired": "de MFA-stap is verlopen; log opnieuw in bij Garmin",
    "garmin_not_connected": "koppel eerst Garmin of Wahoo",
    "wahoo_not_configured": "de server heeft geen Wahoo-app (WAHOO_CLIENT_ID en WAHOO_CLIENT_SECRET)",
    # zones and profile (api/settings_api.py)
    "zone_percentages": "vier oplopende percentages tussen 40 en 100",
    "unknown_sport": "onbekende sport {sport}",
    "max_hr_range": "max hartslag tussen {min} en {max}",
    "profile_range": "{field} tussen {min} en {max}",
    # onboarding (api/onboarding.py)
    "unknown_field": "onbekend veld: {fields}",
    "invalid_choice": "kies uit: {options}",
    "invalid_device": "kies uit: {options}",
    "invalid_done": "done is true of false",
    "invalid_step": "een stap is een getal vanaf 0",
    "unknown_banner": "onbekende banner; kies uit: {options}",
    "unknown_page": "onbekende pagina; kies uit: {options}",
    # gear (api/gear.py)
    "gear_not_found": "materiaal niet gevonden",
    "gear_name_required": "geef het materiaal een naam en soort",
    "garmin_gear": "dit materiaal komt uit Garmin: zet het op buiten gebruik in plaats van het te verwijderen",
    # plans (api/plans.py)
    "plan_not_found": "schema niet gevonden",
    "invalid_date": "ongeldige datum: {date}",
    "invalid_plan_status": "status moet een van {options} zijn",
    "no_sessions": "geen sessies gevonden",
    "no_session_to_link": "geen sessie {sport} op {date} in het schema",
    # routes (api/routes_api.py)
    "route_not_found": "rondje niet gevonden",
    "unknown_route": "onbekend rondje",
    "no_open_question": "geen open vraag voor dit paar",
    "route_name_length": "naam van {min} tot {max} tekens",
    # documents, activities, zones
    "document_not_found": "document bestaat niet",
    "unknown_document": "onbekend document",
    "activity_not_found": "activiteit niet gevonden",
    "invalid_distance": "afstand tussen {min} en {max} km",
    "max_periods": "maximaal {max} perioden",
    # FIT upload (api/uploads.py)
    "upload_empty": "leeg bestand",
    "upload_too_large": "bestand groter dan {max_mb} MB",
    "fit_unreadable": "geen leesbare activiteit in dit FIT-bestand",
    # Apple Health import (api/apple.py)
    "not_an_export": "geen export van Apple Gezondheid (export.zip)",
    "apple_import_running": "er loopt al een import",
    "import_failed": "de import is mislukt",
    "upload_not_found": "upload niet gevonden of verlopen; begin opnieuw",
    "upload_out_of_order": "verkeerd deel; verwacht deel {expected}",
    "upload_size_mismatch": "dit deel heeft niet de verwachte grootte ({expected} bytes)",
    "upload_incomplete": "de upload is nog niet compleet ({received} van {size} bytes)",
    # feedback (api/feedback.py)
    "feedback_kind": "soort is bug of idea",
    "feedback_empty": "schrijf wat er mis is of wat je zou willen",
    "feedback_too_many": "te veel feedback vandaag, probeer het morgen opnieuw",
    "feedback_screenshot_type": "screenshot moet een png, jpeg of webp zijn",
    "feedback_not_found": "feedback niet gevonden",
    "feedback_status": "status is een van {options}",
    # the admin hub (api/tracker_admin.py)
    "unknown_beta": "onbekende bètafunctie; kies uit: {options}",
    # nutrition (api/nutrition.py)
    "nutrition_off": "Voeding staat niet aan voor dit account",
    "meal_not_found": "maaltijd niet gevonden",
    "meal_empty": "een maaltijd heeft minstens één voedingsmiddel",
    "meal_too_many_items": "maximaal {max} voedingsmiddelen per maaltijd",
    "food_not_found": "voedingsmiddel niet gevonden: {ref}",
    "invalid_grams": "hoeveelheid tussen 0 en {max} gram",
    "invalid_time": "ongeldige tijd: {time}",
    "nevo_format": "geen NEVO-online bestand: {reason}",
    "nutrition_ai_unavailable": "foto-analyse kan niet op deze server (geen ANTHROPIC_API_KEY)",
    "nutrition_ai_off": "zet foto-analyse eerst aan bij Zones en profiel",
    "photo_invalid": "geen JPEG- of PNG-foto",
    "photo_not_found": "foto niet gevonden",
    "invalid_barcode": "geen geldige barcode",
    "barcode_not_found": "Open Food Facts kent deze barcode niet",
    "barcode_lookup_failed": "Open Food Facts is nu niet bereikbaar; probeer het later opnieuw",
    "barcode_no_nutrients": "Open Food Facts kent dit product, maar zonder voedingswaarden per 100 gram",
    "nutrition_ai_limit": "maximaal {max} foto's per dag; zoek de rest of probeer het morgen",
    "template_name_required": "geef de favoriet een naam",
    "too_many_templates": "maximaal {max} favorieten",
    "template_not_found": "favoriet niet gevonden",
    "food_name_required": "geef het product een naam",
    "food_energy_required": "vul in hoeveel kcal er per 100 in zit",
    "food_value_range": "{field} tussen 0 en {max} per 100",
    "too_many_foods": "maximaal {max} eigen producten",
    # skin diary (api/skin.py)
    "invalid_day": "geen datum (JJJJ-MM-DD)",
    "invalid_range": "een periode van 1 tot {max} dagen, van voor tot",
    "invalid_scale": "{field} is een cijfer van 0 tot 10",
    "invalid_count": "{field} is een aantal van 0 tot {max}",
    "invalid_flag": "{field} is ja of nee",
    "invalid_list": "{field} is een lijst",
    "too_many": "maximaal {max} bij {field}",
    "entry_not_found": "deze dag staat niet in het dagboek",
}


def _text(code: str, params: dict) -> str:
    shown = {k: ", ".join(map(str, v)) if isinstance(v, (list, tuple)) else v for k, v in params.items()}
    return MESSAGES[code].format(**shown)


def translate(exc) -> str:
    """The Dutch `detail` of an error from the shared accounts (trackerai_accounts.AccountError), like ApiError's."""
    return _text(exc.code, exc.params) if exc.code in MESSAGES else exc.detail


class ApiError(HTTPException):
    """An HTTP error with a code the site translates. `detail` is the Dutch text for agents and scripts."""

    def __init__(self, status_code: int, code: str, detail: str | None = None, headers: dict | None = None, **params):
        super().__init__(status_code=status_code, detail=detail or _text(code, params), headers=headers)
        self.code = code
        self.params = params


async def _handle(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse({"detail": exc.detail, "code": exc.code, "params": exc.params}, status_code=exc.status_code, headers=exc.headers)


def install(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _handle)
