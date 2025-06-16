from asyncio import timeout
from typing import Optional,Annotated
import csv

from fastapi import FastAPI, Depends, HTTPException,status,UploadFile, File ,Security,Request,Form, Body
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from io import StringIO

from starlette.responses import RedirectResponse, HTMLResponse
from starlette.status import HTTP_302_FOUND

from SMS_Handler.handler import AsyncOnBukaClient
from core import models, database,auth
from contextlib import asynccontextmanager
from core.schemas import *
from typing import List
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

import asyncio
import random
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.models import PhoneNumber, User, SMSTemplate,SMS_Account_creds
from core.database import AsyncSessionLocal

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)





async def get_session() -> AsyncSession:
    async with database.AsyncSessionLocal() as session:
        yield session
# utils
async def is_user_admin(user_id: int, session: AsyncSession):
    res = await session.execute(select(models.AdminUser).where(models.AdminUser.user_id == user_id))
    return res.scalar_one_or_none() is not None

async def require_admin(
    current_user: str = Depends(auth.get_current_user),
    session: AsyncSession =Depends(get_session)
):
    user_result = await session.execute(select(models.User).where(models.User.name == current_user))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    admin_result = await session.execute(select(models.AdminUser).where(models.AdminUser.user_id == user.id))
    admin = admin_result.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user

async def deduct_balance(user_id: int, amount: float, session):
    user_result = await session.execute(select(models.User).where(models.User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")
    if user.balance < amount:
        raise ValueError("Insufficient balance")
    user.balance = float(user.balance) - amount
    await session.commit()
    return user.balance

async def set_sms_account_status(sms_account_id: int, works: bool, session):
    result = await session.execute(select(models.SMS_Account_creds).where(models.SMS_Account_creds.id == sms_account_id))
    sms_account = result.scalar_one_or_none()
    if not sms_account:
        raise ValueError("SMS Account not found")
    sms_account.still_works = works
    await session.commit()
    return sms_account.still_works

async def set_sms_account_status_route(
    cred_id: int,
    works: bool = True,
    admin_user: models.User = Depends(require_admin),
    session: AsyncSession = Depends(get_session)
):
    try:
        new_status = await set_sms_account_status(cred_id, works, session)
        return {"cred_id": cred_id, "still_works": new_status}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

async def is_acceptable_cost(user_id: int, cost: float, session) -> bool:
    """
    Returns True if user's balance is greater than cost, else False.
    """
    user_result = await session.execute(select(models.User).where(models.User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")
    return float(user.balance) >= cost

# scheduled task
async def send_sms_batch_task():
    async with AsyncSessionLocal() as session:
        # get all users
        users=await session.execute(select(User))
        users = users.scalars().all()

        if not len(users):
            return  # No unsent numbers

        for userx in users:
            user_id = userx.id
            logger.info("user selected"+str(user_id))
            # 2. Get all unsent phone numbers for this user
            phones_result = await session.execute(
                select(PhoneNumber).where(
                    PhoneNumber.user_id == user_id, PhoneNumber.is_sent == False
                )
            )
            user_phones = phones_result.scalars().all()
            logger.info ("found phones"+ str(len(user_phones))+ " for user "+ str(user_id))
            if user_phones:
                # 3. Get all SMS templates by this user
                templates_result = await session.execute(
                    select(SMSTemplate).where(SMSTemplate.user_id == user_id)
                )
                templates = templates_result.scalars().all()
                if templates:


                    # 4. Get user object and balance
                    user_result = await session.execute(select(User).where(User.id == user_id))
                    user = user_result.scalar_one_or_none()
                    if user and  user.price_per_sms > 0:
                        # 5. Determine max sendable based on balance
                        max_can_send = int(user.balance // user.price_per_sms)
                        if max_can_send <= 0:
                            continue

                        phone_numbers = [p.number for p in user_phones[:max_can_send]]
                        batches = [phone_numbers[i:i + 50] for i in range(0, len(phone_numbers), 50)]

                        for batch in batches:
                            template = random.choice(templates)
                            total_price = len(batch) * user.price_per_sms
                            if total_price <= user.balance:
                                # --- Fetch all valid SMS creds for use ---
                                creds_result = await session.execute(
                                    select(SMS_Account_creds).where(SMS_Account_creds.still_works == True)
                                )
                                creds_list = creds_result.scalars().all()
                                if not creds_list:
                                    print("No valid SMS account creds available.")
                                    return

                                creds = random.choice(creds_list)
                                # Initialize a fresh OnBuka client with these creds
                                onbuka_client = AsyncOnBukaClient(
                                    api_key=creds.api_key,
                                    api_pwd=creds.api_pwd,
                                    appid=creds.appid
                                )

                                async def callback(response, batch=batch, creds_id=creds.id):
                                    # If status code (or response code) is not 200, disable creds
                                    is_ok = False
                                    logger.info ("got a response"+str(response) )
                                    if response:
                                        is_ok = True

                                    if is_ok:
                                        async with AsyncSessionLocal() as callback_session:
                                            numbers_to_update = await callback_session.execute(
                                                select(PhoneNumber).where(
                                                    PhoneNumber.number.in_(batch),
                                                    PhoneNumber.user_id == user_id
                                                )
                                            )
                                            for p in numbers_to_update.scalars():
                                                p.is_sent = True
                                            user_cb_result = await callback_session.execute(select(User).where(User.id == user_id))
                                            user_cb = user_cb_result.scalar_one_or_none()
                                            if user_cb:
                                                user_cb.balance=float(user_cb.balance) - (len(batch) * float(user_cb.price_per_sms))
                                            await callback_session.commit()
                                    else:
                                        # Set SMS_Account_creds.still_works to False!
                                        async with AsyncSessionLocal() as callback_session:
                                            cred_obj_result = await callback_session.execute(
                                                select(SMS_Account_creds).where(SMS_Account_creds.id == creds_id)
                                            )
                                            cred_obj = cred_obj_result.scalar_one_or_none()
                                            if cred_obj:
                                                cred_obj.still_works = False
                                                await callback_session.commit()
                                        print(f"SMS API key {creds_id} marked as not working.")

                                # --- Send SMS ---
                                result = await onbuka_client.send_sms(
                                    message=template.template_text,
                                    phone_numbers=batch,
                                    callback=callback
                                )
                                logger.info(result)
                                # Optionally, can check for result right here if not using callback
                                await asyncio.sleep(1)

# lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables
    async with database.engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    scheduler = AsyncIOScheduler()
    logger.info("Starting SMS batch task scheduler,logger working")
    scheduler.add_job(send_sms_batch_task, 'interval', seconds=60)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)
    # (You can also put shutdown code here if needed)

app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key="your-secret-key")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Jinja2 templates setup
templates = Jinja2Templates(directory="templates")

@app.post("/register", response_model=dict)
async def register(user: UserCreate, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(models.User).where(models.User.name == user.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = auth.hash_password(user.password)
    db_user = models.User(
        name=user.name.strip(),
        balance=user.balance,
        price_per_sms=user.price_per_sms,
        password_hashed=hashed_password,
    )
    session.add(db_user)
    await session.commit()
    await session.refresh(db_user)
    return {"id": db_user.id, "name": db_user.name}

# Login route
@app.post("/login", response_model=TokenResponse)
async def login(login: UserLogin, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(models.User).where(models.User.name == login.name))
    db_user = result.scalar_one_or_none()
    if not db_user or not auth.verify_password(login.password, db_user.password_hashed):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = auth.create_access_token({"sub": db_user.name})
    return {"access_token": token, "token_type": "bearer"}

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        # Show login page with error message
        return RedirectResponse("/ui/login", status_code=HTTP_302_FOUND)
    # For other errors, use default handler or your other handlers
    return HTMLResponse(content=str(exc.detail), status_code=exc.status_code)

@app.post("/templates_create", response_model=SMSTemplateOut)
async def create_template(
    request:Request,template: SMSTemplateCreate,
    session: AsyncSession = Depends(get_session),
):

    current_user=await allyouknow(request,session)
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    db_template = models.SMSTemplate(
        template_name=template.template_name,
        template_text=template.template_text,
        user_id=current_user.id,
    )
    session.add(db_template)
    await session.commit()
    await session.refresh(db_template)
    return SMSTemplateOut(
        id=db_template.id,
        template_name=db_template.template_name,
        template_text=db_template.template_text,
        created_by=current_user.name,
    )

@app.get("/templates_list", response_model=List[SMSTemplateOut])
async def templates_list(
    current_user: str = Depends(auth.get_current_user),
    session: AsyncSession = Depends(get_session),
):
    user_result = await session.execute(select(models.User).where(models.User.name == current_user))
    user_obj = user_result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    admin_result = await session.execute(select(models.AdminUser).where(models.AdminUser.user_id == user_obj.id))
    is_admin = admin_result.scalar_one_or_none() is not None

    if is_admin:
        templates_result = await session.execute(select(models.SMSTemplate))
    else:
        templates_result = await session.execute(
            select(models.SMSTemplate).where(models.SMSTemplate.user_id == user_obj.id)
        )
    templates = templates_result.scalars().all()
    results = []
    for t in templates:
        creator_name = None
        if is_admin:
            creator_result = await session.execute(select(models.User).where(models.User.id == t.user_id))
            creator = creator_result.scalar_one_or_none()
            creator_name = creator.name if creator else ""
        results.append(SMSTemplateOut(
            id=t.id,
            template_name=t.template_name,
            template_text=t.template_text,
            created_by=creator_name if is_admin else None
        ))
    return results

@app.delete("/templates_delete/{template_id}", response_model=dict)
async def delete_template(
    request:Request,template_id: int,
    session: AsyncSession = Depends(get_session),
):

    user_obj = await allyouknow(request, session)
    if not user_obj:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    template_result = await session.execute(
        select(models.SMSTemplate).where(models.SMSTemplate.id == template_id)
    )
    template = template_result.scalar_one_or_none()
    if not template or template.user_id != user_obj.id and not await is_user_admin(user_obj.id, session):
        raise HTTPException(status_code=404, detail="Template not found or not owned by user")

    await session.delete(template)
    await session.commit()
    return {"detail": "Template deleted"}

@app.post("/phone_add")
async def add_phone_number(
    request:Request,phone: PhoneNumberCreate,
    session: AsyncSession = Depends(get_session),
):

    user_obj =await allyouknow(request,session)
    if not user_obj:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    db_number = models.PhoneNumber(number=phone.number, user_id=user_obj.id)
    session.add(db_number)
    await session.commit()
    await session.refresh(db_number)
    return {"id": db_number.id, "number": db_number.number, "is_sent": db_number.is_sent}

@app.post("/phone_add_token")
async def add_phone_number_token(
    phone: PhoneNumberCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    token = request.session.get("token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    current_user = await auth.get_current_user(token)
    user_result = await session.execute(select(models.User).where(models.User.name == current_user))
    user_obj = user_result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    db_number = models.PhoneNumber(number=phone.number, user_id=user_obj.id)
    session.add(db_number)
    await session.commit()
    await session.refresh(db_number)
    return {"id": db_number.id, "number": db_number.number, "is_sent": db_number.is_sent}

@app.post("/phone_bulk_upload")
async def phone_bulk_upload(
        request: Request,file: UploadFile = File(...),
        session: AsyncSession = Depends(get_session),
):
    # Get user

    user_obj = await allyouknow(request, session)
    if not user_obj:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    content = await file.read()
    s = content.decode("utf-8")
    csv_reader = csv.DictReader(StringIO(s)) if 'number' in s else csv.reader(StringIO(s))

    added_numbers = []
    errors = []
    # Try to handle both dict and simple row style CSVs
    for idx, row in enumerate(csv_reader):
        try:
            # Get number
            if isinstance(row, dict):
                number = row.get("number")
            else:
                number = row[0]
            if not number:
                raise ValueError("No number found")
            db_number = models.PhoneNumber(number=number, user_id=user_obj.id)
            session.add(db_number)
            added_numbers.append(number)
        except Exception as e:
            errors.append(f"Row {idx + 1}: {e}")

    await session.commit()
    return {
        "added": added_numbers,
        "errors": errors
    }


class MakeAdminRequest(BaseModel):
    user_name: str

@app.post("/make_admin")
async def make_admin(
        request: Request,
        data: MakeAdminRequest,
        session: AsyncSession = Depends(get_session),
):
    # (Optional) Check if current_user is already admin
    admin_user = await allyouknow(request, session)
    admin_user_id = admin_user.id if admin_user else None

    # (Optional) Only allow existing admins to promote new admins:
    is_admin = await session.execute(select(models.AdminUser).where(models.AdminUser.user_id == admin_user_id))
    if is_admin.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Only admins can add admins")

    # Promote user_name to admin
    result = await session.execute(select(models.User).where(models.User.name == data.user_name))
    user_obj = result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if already admin
    exists = await session.execute(select(models.AdminUser).where(models.AdminUser.user_id == user_obj.id))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User already admin")

    admin = models.AdminUser(user_id=user_obj.id)
    session.add(admin)
    await session.commit()
    await session.refresh(admin)
    return {"detail": f"{data.user_name} promoted to admin"}

@app.post("/sms_account_creds/add", response_model=SMSAccountCredsOut)
async def add_sms_account_creds(
    request:Request,creds: SMSAccountCredsCreate,
    session: AsyncSession = Depends(get_session)
):
    # Ensure still_works is set to True by default if not present
    user_caller= await allyouknow(request, session)
    is_admin=await is_user_admin(user_caller.id, session)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    cred_obj = models.SMS_Account_creds(
        api_key=creds.api_key,
        api_pwd=creds.api_pwd,
        appid=creds.appid,
        still_works=getattr(creds, "still_works", True)
    )
    session.add(cred_obj)
    try:
        await session.commit()
        await session.refresh(cred_obj)
    except Exception as e:
        logger.error(f"Failed to add SMS credential: {e}")
        raise HTTPException(status_code=400, detail="Failed to add SMS credential")
    return cred_obj

@app.delete("/sms_account_creds/delete/{cred_id}")
async def delete_sms_account_creds(
    request:Request,cred_id: int,
    session: AsyncSession = Depends(get_session)
):
    user_caller = await allyouknow(request, session)
    is_admin = await is_user_admin(user_caller.id, session)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    result = await session.execute(select(models.SMS_Account_creds).where(models.SMS_Account_creds.id == cred_id))
    cred_obj = result.scalar_one_or_none()
    if not cred_obj:
        raise HTTPException(status_code=404, detail="Account not found")
    await session.delete(cred_obj)
    await session.commit()
    return {"detail": "Deleted"}

@app.post("/sms_account_creds/update_status")
async def update_sms_account_status(
    request:Request,data: dict = Body(...),
    session: AsyncSession = Depends(get_session)
):
    user_caller = await allyouknow(request, session)
    is_admin = await is_user_admin(user_caller.id, session)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    cred_id = data.get("cred_id")
    works = data.get("works")
    if cred_id is None or works is None:
        raise HTTPException(status_code=400, detail="cred_id and works required")
    try:
        new_status = await set_sms_account_status(cred_id, works, session)
        return {"cred_id": cred_id, "still_works": new_status}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/user/add_balance")
async def add_balance(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    data = await request.json()
    user_name = data.get("user_name")
    amount = data.get("amount")
    if not user_name or amount is None:
        raise HTTPException(status_code=400, detail="user_name and amount required")
    callinguser = await allyouknow(request, session)
    is_admin = await is_user_admin(callinguser.id, session)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    result = await session.execute(select(models.User).where(models.User.name == user_name))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.balance=float(user.balance) + float(amount)  # amount can be negative
    await session.commit()
    return {"user": user.name, "balance": user.balance}

@app.get("/phone_list", response_model=List[PhoneNumberOut])
async def phone_list(
    current_user: str = Depends(auth.get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Get user and check admin
    user_result = await session.execute(select(models.User).where(models.User.name == current_user))
    user_obj = user_result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    admin_result = await session.execute(select(models.AdminUser).where(models.AdminUser.user_id == user_obj.id))
    is_admin = admin_result.scalar_one_or_none() is not None

    # Get phones
    if is_admin:
        phones_result = await session.execute(select(models.PhoneNumber))
    else:
        phones_result = await session.execute(
            select(models.PhoneNumber).where(models.PhoneNumber.user_id == user_obj.id)
        )
    phones = phones_result.scalars().all()
    results = []
    for p in phones:
        creator_name = None
        if is_admin:
            creator_result = await session.execute(select(models.User).where(models.User.id == p.user_id))
            creator = creator_result.scalar_one_or_none()
            creator_name = creator.name if creator else ""
        results.append(PhoneNumberOut(
            id=p.id,
            number=p.number,
            is_sent=p.is_sent,
            created_by=creator_name if is_admin else None
        ))
    return results

@app.delete("/phone_delete/{id}")
async def delete_phone_number(
    request:Request,id: int,
    session: AsyncSession = Depends(get_session),
):
    user_obj=await allyouknow(request,session)
    if not user_obj:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    phone_result = await session.execute(select(models.PhoneNumber).where(models.PhoneNumber.id == id))
    phone = phone_result.scalar_one_or_none()
    if not phone or phone.user_id != user_obj.id and not await is_user_admin(user_obj.id, session):
        raise HTTPException(status_code=404, detail="Phone number not found or not owned by user")

    await session.delete(phone)
    await session.commit()
    return {"detail": "Deleted"}

@app.get("/sms_account_creds/list", response_model=List[SMSAccountCredsOut])
async def list_sms_account_creds(
    current_user: str = Depends(auth.get_current_user),
    session: AsyncSession = Depends(get_session)
):
    user_result = await session.execute(select(models.User).where(models.User.name == current_user))
    user_obj = user_result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    admin_result = await session.execute(select(models.AdminUser).where(models.AdminUser.user_id == user_obj.id))
    is_admin = admin_result.scalar_one_or_none() is not None

    # Admins: see all, non-admin: only own (if you store user_id on creds)
    if is_admin:
        creds_result = await session.execute(select(models.SMS_Account_creds))
    else:
        creds_result = await session.execute(
            select(models.SMS_Account_creds).where(models.SMS_Account_creds.user_id == user_obj.id)
        )
    creds = creds_result.scalars().all()
    return creds

@app.get("/is_admin")
async def is_admin(
    current_user: str = Depends(auth.get_current_user),
    session: AsyncSession = Depends(get_session)
):
    user_result = await session.execute(select(models.User).where(models.User.name == current_user))
    user_obj = user_result.scalar_one_or_none()
    if not user_obj:
        return {"is_admin": False}
    admin_result = await session.execute(select(models.AdminUser).where(models.AdminUser.user_id == user_obj.id))
    is_admin = admin_result.scalar_one_or_none() is not None
    return {"is_admin": is_admin}

@app.get("/user_info")
async def user_info(
    current_user: str = Depends(auth.get_current_user),
    session: AsyncSession = Depends(get_session)
):
    user_result = await session.execute(select(models.User).where(models.User.name == current_user))
    user_obj = user_result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    admin_result = await session.execute(select(models.AdminUser).where(models.AdminUser.user_id == user_obj.id))
    is_admin = admin_result.scalar_one_or_none() is not None

    resp = {
        "name": user_obj.name,
        "balance": user_obj.balance
    }
    if is_admin:
        resp["price_per_sms"] = user_obj.price_per_sms
    return resp


@app.get("/admin/users")
async def admin_list_users(
    current_user: str = Depends(auth.get_current_user),
    session: AsyncSession = Depends(get_session)
):
    # check if admin
    user_result = await session.execute(select(models.User).where(models.User.name == current_user))
    user_obj = user_result.scalar_one_or_none()
    admin_result = await session.execute(select(models.AdminUser).where(models.AdminUser.user_id == user_obj.id))
    if not admin_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Admin only")
    users_result = await session.execute(select(models.User))
    users = users_result.scalars().all()
    return [
        {
            "id": u.id,
            "name": u.name,
            "balance": u.balance,
            "price_per_sms": u.price_per_sms
        } for u in users
    ]

@app.post("/admin/add_balance")
async def admin_add_balance(
    data: BalanceUpdateRequest,
    current_user: str = Depends(auth.get_current_user),
    session: AsyncSession = Depends(get_session)
):
    user_result = await session.execute(select(models.User).where(models.User.name == current_user))
    user_obj = user_result.scalar_one_or_none()
    admin_result = await session.execute(select(models.AdminUser).where(models.AdminUser.user_id == user_obj.id))
    if not admin_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Admin only")
    target_result = await session.execute(select(models.User).where(models.User.id == data.user_id))
    target_user = target_result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    target_user.balance=float(target_user.balance) + float(data.amount)
    await session.commit()
    return {"user": target_user.name, "balance": target_user.balance}

@app.post("/admin/set_price_per_sms")
async def admin_set_price(
    request:Request,data: PriceUpdateRequest,
    session: AsyncSession = Depends(get_session)
):

    user_obj = await allyouknow(request, session)
    admin_result = await is_user_admin(user_obj.id, session)
    if not admin_result:
        raise HTTPException(status_code=403, detail="Admin only")
    target_result = await session.execute(select(models.User).where(models.User.id == data.user_id))
    target_user = target_result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    target_user.price_per_sms = data.price_per_sms
    await session.commit()
    return {"user": target_user.name, "price_per_sms": target_user.price_per_sms}


async def allyouknow(request:Request,session):
    token = request.session.get('token',None)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = await auth.userftoken(token)
    user_result = await session.execute(select(models.User).where(models.User.name == user))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user

async def get_is_admin(user, session):
    if not user:
        return False
    res = await session.execute(select(models.AdminUser).where(models.AdminUser.user_id == user.id))
    return res.scalar_one_or_none() is not None

@app.get("/ui/login")
async def login_get(request: Request):
    return templates.TemplateResponse("ui/login.html", {"request": request, "error": None})

@app.post("/ui/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...) ,session: AsyncSession = Depends(get_session)):
    res=await login(UserLogin(name=username,password=password),session=session)
    request.session.clear()
    request.session.setdefault("token",res["access_token"])
    return await maintemp(request,session=session)

@app.get("/ui/phonenumbers")
async def ui_phonenumbers(request: Request, session: AsyncSession = Depends(get_session)):
    user = await allyouknow(request, session)
    is_admin = await get_is_admin(user, session)
    # Get phone numbers for user or all if admin
    if is_admin:
        phones_result = await session.execute(select(models.PhoneNumber))
        phones = phones_result.scalars().all()
    else:
        phones_result = await session.execute(
            select(models.PhoneNumber).where(models.PhoneNumber.user_id == user.id)
        )
        phones = phones_result.scalars().all()
    # Prepare data as list of dicts
    data = []
    for p in phones:
        # Get creator name if admin
        creator_name = None
        if is_admin:
            creator_result = await session.execute(select(models.User).where(models.User.id == p.user_id))
            creator = creator_result.scalar_one_or_none()
            creator_name = creator.name if creator else ""
        data.append({
            "id": p.id,
            "number": p.number,
            "is_sent": "Yes" if p.is_sent else "No",
            "created_by": creator_name if is_admin else None
        })
    return templates.TemplateResponse("ui/phonenumbers.html", {"request": request, "user": user, "is_admin": is_admin, "data": data})

@app.get("/ui/templates")
async def ui_templates(request: Request, session: AsyncSession = Depends(get_session)):
    user = await allyouknow(request, session)
    is_admin = await get_is_admin(user, session)
    # Fetch templates for user or all if admin
    if is_admin:
        templates_result = await session.execute(select(models.SMSTemplate))
        template_objs = templates_result.scalars().all()
    else:
        templates_result = await session.execute(
            select(models.SMSTemplate).where(models.SMSTemplate.user_id == user.id)
        )
        template_objs = templates_result.scalars().all()
    # Prepare data as list of dicts
    data = []
    for t in template_objs:
        creator_name = None
        if is_admin:
            creator_result = await session.execute(select(models.User).where(models.User.id == t.user_id))
            creator = creator_result.scalar_one_or_none()
            creator_name = creator.name if creator else ""
        data.append({
            "id": t.id,
            "template_name": t.template_name,
            "template_text": t.template_text,
            "created_by": creator_name if is_admin else None
        })
    return templates.TemplateResponse(
        "ui/templates.html",
        {"request": request, "user": user, "is_admin": is_admin, "data": data}
    )

@app.get("/ui/creds")
async def ui_creds(request: Request,session: AsyncSession = Depends(get_session)):
    user = await allyouknow(request, session)
    is_admin = await get_is_admin(user, session)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    # Fetch all SMS creds
    creds_result = await session.execute(select(models.SMS_Account_creds))
    creds = creds_result.scalars().all()
    # Prepare data for table
    data = []
    for c in creds:
        data.append({
            "id": c.id,
            "api_key": c.api_key,
            "api_pwd": c.api_pwd,
            "appid": c.appid,
            "still_works": "Yes" if c.still_works else "No"
        })
    return templates.TemplateResponse("ui/creds.html", {"request": request,"user":user, "is_admin": is_admin, "data": data})

@app.get("/ui/admin")
async def ui_admin(request: Request, session: AsyncSession = Depends(get_session)):
    user = await allyouknow(request, session)
    is_admin = await get_is_admin(user, session)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    # Fetch all users and their admin status
    users_result = await session.execute(select(models.User))
    users = users_result.scalars().all()
    admin_ids_result = await session.execute(select(models.AdminUser.user_id))
    admin_ids = set([row[0] for row in admin_ids_result.all()])
    data = []
    for u in users:
        data.append({
            "id": u.id,
            "name": u.name,
            "balance": u.balance,
            "price_per_sms": u.price_per_sms,
            "is_admin": u.id in admin_ids
        })
    return templates.TemplateResponse("ui/admin.html", {"request": request, "user": user, "is_admin": is_admin, "data": data})

@app.delete("/admin/delete_user")
async def admin_delete_user(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    data = await request.json()
    user_obj = await allyouknow(request, session)
    admin_result = await session.execute(select(models.AdminUser).where(models.AdminUser.user_id == user_obj.id))
    if not admin_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Admin only")
    user_id = data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID required")
    target_result = await session.execute(select(models.User).where(models.User.id == user_id))
    target_user = target_result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    await session.delete(target_user)
    await session.commit()
    return {"detail": "User deleted"}

@app.get('/')
async def maintemp(request: Request,session: AsyncSession = Depends(get_session)):
    user= await allyouknow(request, session)
    is_admin = await get_is_admin(user, session)
    return templates.TemplateResponse("ui/home.html", {"request": request,"user":user, "is_admin": is_admin})
