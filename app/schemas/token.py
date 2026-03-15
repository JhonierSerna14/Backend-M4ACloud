"""
Esquemas Pydantic para validación de tokens JWT.
Define los modelos para tokens de acceso y refresh.
"""
from pydantic import BaseModel
from datetime import datetime
class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str

class TokenPayload(BaseModel):
    sub: str
    exp: datetime
    type: str  # "access" o "refresh"

class RefreshToken(BaseModel):
    refresh_token: str