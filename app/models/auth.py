from pydantic import BaseModel


class SessionPayload(BaseModel):
    access_token: str
    refresh_token: str
