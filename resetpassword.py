import asyncio
from core import models, database, auth
from sqlalchemy.future import select


async def resetpassword(
    id: str,
    password: str
):
    async with database.AsyncSessionLocal() as session:

        # Create user
        hashed_password = auth.hash_password(password)
        user_obj = await session.execute(select(models.User).where(models.User.id == id))
        user = user_obj.scalar_one_or_none()
        if not user:
            print("no user found")
            return
        print("user found '"+user.name+"'")

        user.password_hashed= hashed_password
        await session.commit()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 1:
        print("Usage: python create_first_admin.py <id> <password>")
        sys.exit(1)
    username = sys.argv[1]
    password = sys.argv[2]
    asyncio.run(resetpassword(username, password))
