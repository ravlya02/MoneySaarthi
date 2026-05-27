from pydantic import BaseModel, EmailStr, Field


class SessionPayload(BaseModel):
    access_token: str
    refresh_token: str


class RegisterPayload(BaseModel):
    full_name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)


class LoginPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
