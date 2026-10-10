from pydantic import BaseModel


class TrackerBetaRequest(BaseModel):
    feature: str  # a key of auth_store.BETA_FEATURES, validated in the router (422)
    enabled: bool
