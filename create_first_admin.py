import asyncio
from core import models, database, auth

async def create_first_admin_user(
    username: str,
    password: str,
    balance: float = 0.0,
    price_per_sms: float = 1.0
):
    async with database.AsyncSessionLocal() as session:
        # Check if any users exist
        result = await session.execute(models.User.__table__.select())
        if result.first():
            print("Users already exist. Aborting.")
            return

        # Create user
        hashed_password = auth.hash_password(password)
        user = models.User(
            name=username,
            balance=balance,
            price_per_sms=price_per_sms,
            password_hashed=hashed_password,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        # Make admin
        admin = models.AdminUser(user_id=user.id)
        session.add(admin)
        await session.commit()
        print(f"User '{username}' created and made admin.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python create_first_admin.py <username> <password> [balance] [price_per_sms]")
        sys.exit(1)
    username = sys.argv[1]
    password = sys.argv[2]
    balance = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    price_per_sms = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    asyncio.run(create_first_admin_user(username, password, balance, price_per_sms))
