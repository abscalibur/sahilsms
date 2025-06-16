from pydantic import BaseModel
from typing import Optional

class UserCreate(BaseModel):
    name: str
    password: str
    balance: float = 0.0
    price_per_sms: float = 0.0

class UserLogin(BaseModel):
    name: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class SMSTemplateCreate(BaseModel):
    template_name: str
    template_text: str

class SMSTemplateOut(BaseModel):
    id: int
    template_name: str
    template_text: str
    created_by: Optional[str] = None
    class Config:
        from_attributes = True

class PhoneNumberCreate(BaseModel):
    number: str

class AdminUserOut(BaseModel):
    id: int
    user_id: int

    class Config:
        from_attributes = True

class SMSAccountCredsCreate(BaseModel):
    api_key: str
    api_pwd: str
    appid: str

class SMSAccountCredsOut(BaseModel):
    id: int
    api_key: str
    api_pwd: str
    appid: str
    still_works: bool
    class Config:
        from_attributes = True

class UserBalanceAdd(BaseModel):
    user_name: str
    amount: float

class PhoneNumberOut(BaseModel):
    id: int
    number: str
    is_sent: bool
    created_by: Optional[str] = None
    class Config:
        from_attributes = True

class BalanceUpdateRequest(BaseModel):
    user_id: int
    amount: float

class PriceUpdateRequest(BaseModel):
    user_id: int
    price_per_sms: float