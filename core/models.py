from sqlalchemy import Column, Integer, String, Float, ForeignKey, event, UniqueConstraint, Boolean, Numeric
from sqlalchemy.orm import relationship
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)  # Name is now unique
    balance = Column(Numeric(12,4), default=0.0)
    price_per_sms = Column(Numeric(12,4), default=0.0)
    is_sending = Column(Boolean, default=True)
    password_hashed = Column(String, nullable=False)

    sms_templates = relationship("SMSTemplate", back_populates="creator")
    phone_numbers = relationship("PhoneNumber", back_populates="user")

class SMSTemplate(Base):
    __tablename__ = "sms_templates"

    id = Column(Integer, primary_key=True, index=True)
    template_name = Column(String, nullable=False)
    template_text = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"))

    creator = relationship("User", back_populates="sms_templates")

class PhoneNumber(Base):
    __tablename__ = "phone_numbers"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String, nullable=False, index=True)
    is_sent = Column(Boolean, default=False)
    user_id = Column(Integer, ForeignKey("users.id"))

    user = relationship("User", back_populates="phone_numbers")

def normalize_phone_number(mapper, connect, target):
    raw = target.number.strip()
    # Remove leading +
    if raw.startswith('+'):
        raw = raw[1:]
    # If not starting with 91 (India) or 1 (US), add 1 (US)
    if not (raw.startswith('91') or raw.startswith('1')):
        raw = '1' + raw
    target.number = raw

# Register the event for insert
event.listen(PhoneNumber, "before_insert", normalize_phone_number)
event.listen(PhoneNumber, "before_update", normalize_phone_number)

class AdminUser(Base):
    __tablename__ = "admin_users"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    user = relationship("User")

    # Optional: prevent same user being admin twice
    __table_args__ = (UniqueConstraint('user_id', name='uix_user_admin'),)

class SMS_Account_creds(Base):
    __tablename__ = "sms_account_creds"
    id = Column(Integer, primary_key=True, index=True)
    api_key = Column(String, nullable=False)
    api_pwd = Column(String, nullable=False)
    appid = Column(String, nullable=False)
    still_works = Column(Boolean, default=True)



