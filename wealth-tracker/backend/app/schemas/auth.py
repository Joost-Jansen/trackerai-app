from pydantic import BaseModel


class RegisterRequest(BaseModel):
    username: str
    name: str
    password: str
    invite_code: str = ""  # only consulted in invite mode; ignored when signup is open
    email: str = ""  # required: the welcome mail confirms it, and it becomes the two-step login
    locale: str | None = None  # the site's language: the welcome mail's, and the account's
    # The trackers to start with, chosen on the front door (trackerai.nl): "health", "wealth" or both. Empty: this one.
    apps: list[str] = []
    consent: bool = False  # for health-tracker's health data, when it is among them
    # Which site the signup came from: "money" (wealth-tracker) or empty (stock-tracker).
    # wealth-tracker starts from Money, so an account made there gets that flag at once.
    app: str = ""


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class MeResponse(BaseModel):
    username: str
    name: str
    is_admin: bool
    beta_features: list[str]
    # "nl" or "en" once the user chose a language in the app; None follows the device.
    locale: str | None = None
    # Two-step login (TOTP) is on for this account.
    totp_enabled: bool = False
    # Login codes by email are on; `two_step`: either (what deleting or leaving asks a code for).
    email_codes: bool = False
    two_step: bool = False
    # Signed up with an address not confirmed yet: the site asks for the code from the welcome mail first.
    email: str | None = None
    email_verify_required: bool = False
    # The shared trackerai account: whether two-step login is required (and still to be set up), whether it uses
    # wealth-tracker yet, which trackers it uses, and whether it manages accounts in every tracker.
    totp_required: bool = False
    totp_setup_required: bool = False
    in_app: bool = True
    apps: list[str] = []
    account_admin: bool = False


class LocaleRequest(BaseModel):
    locale: str
