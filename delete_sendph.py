# a script which uses the model file scan all tables in the database
# and print the table names and their columns
# then ask me whether I want to copy the table data into csv files
# or load the csv files into the database
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import text
import pandas as pd
from core.models import PhoneNumber

DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

Base = declarative_base()

# Delete all phone numbers where is_sent=True
with SessionLocal() as session:
    session.query(PhoneNumber).filter(PhoneNumber.is_sent == True).delete(synchronize_session=False)
    session.commit()
