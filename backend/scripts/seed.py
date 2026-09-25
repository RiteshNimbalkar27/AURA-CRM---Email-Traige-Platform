#!/usr/bin/env python3
"""
AURA Database Seeder
Seeds users, accounts, and contacts for demo/development.
Idempotent: safe to run multiple times.

Usage (from backend/ directory with venv active):
    python scripts/seed.py
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.security import get_password_hash
from app.models.user import User
from app.models.crm import Account, Contact

settings = get_settings()

# Seed data
USERS = [
    {
        "email": "operator@nexus.example",
        "password": "operator_password_2024",
        "role": "operator",
    },
    {
        "email": "supervisor@nexus.example",
        "password": "supervisor_password_2024",
        "role": "supervisor",
    },
]

ACCOUNTS = [
    {"name": "AcmeCorp", "industry": "Enterprise Software", "plan": "enterprise", "billing_status": "active"},
    {"name": "TechStartup Inc.", "industry": "Technology", "plan": "professional", "billing_status": "active"},
    {"name": "RetailCorp", "industry": "Retail", "plan": "enterprise", "billing_status": "active"},
    {"name": "GlobalTech", "industry": "Technology", "plan": "professional", "billing_status": "active"},
]

CONTACTS = [
    {"email": "sarah.mitchell@acmecorp.example", "account_name": "AcmeCorp", "operational_status": "active"},
    {"email": "tom.bradley@techstartup.example", "account_name": "TechStartup Inc.", "operational_status": "active"},
    {"email": "jennifer.walsh@retailcorp.example", "account_name": "RetailCorp", "operational_status": "at_risk"},
    {"email": "david.chen@globaltech.example", "account_name": "GlobalTech", "operational_status": "active"},
]


async def seed_users(session: AsyncSession) -> None:
    print("\n[SEED] Seeding users...")
    for user_data in USERS:
        result = await session.execute(select(User).where(User.email == user_data["email"]))
        existing = result.scalar_one_or_none()
        if existing:
            print(f"  SKIP: {user_data['email']} already exists")
            continue
        user = User(
            email=user_data["email"],
            hashed_password=get_password_hash(user_data["password"]),
            role=user_data["role"],
            is_active=True,
        )
        session.add(user)
        print(f"  CREATE: {user_data['email']} ({user_data['role']})")
    await session.commit()


async def seed_accounts(session: AsyncSession) -> dict[str, Account]:
    print("\n[SEED] Seeding accounts...")
    account_map: dict[str, Account] = {}
    for acc_data in ACCOUNTS:
        result = await session.execute(select(Account).where(Account.name == acc_data["name"]))
        existing = result.scalar_one_or_none()
        if existing:
            print(f"  SKIP: {acc_data['name']} already exists")
            account_map[acc_data["name"]] = existing
            continue
        account = Account(**acc_data)
        session.add(account)
        await session.flush()  # get ID
        account_map[acc_data["name"]] = account
        print(f"  CREATE: {acc_data['name']}")
    await session.commit()
    return account_map


async def seed_contacts(session: AsyncSession, account_map: dict[str, Account]) -> None:
    print("\n[SEED] Seeding contacts...")
    for contact_data in CONTACTS:
        result = await session.execute(select(Contact).where(Contact.email == contact_data["email"]))
        existing = result.scalar_one_or_none()
        if existing:
            print(f"  SKIP: {contact_data['email']} already exists")
            continue
        account = account_map.get(contact_data["account_name"])
        contact = Contact(
            email=contact_data["email"],
            account_id=account.id if account else None,
            operational_status=contact_data["operational_status"],
        )
        session.add(contact)
        print(f"  CREATE: {contact_data['email']}")
    await session.commit()


async def main() -> None:
    print("=" * 50)
    print("AURA Database Seeder")
    print("=" * 50)
    print(f"Database: {settings.database_url.split('@')[-1] if '@' in settings.database_url else settings.database_url}")

    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        await seed_users(session)
        account_map = await seed_accounts(session)
        await seed_contacts(session, account_map)

    await engine.dispose()
    print("\n[SEED] Done! Database seeded successfully.")
    print("\nLogin credentials:")
    print("  Operator:   operator@nexus.example / operator_password_2024")
    print("  Supervisor: supervisor@nexus.example / supervisor_password_2024")


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
