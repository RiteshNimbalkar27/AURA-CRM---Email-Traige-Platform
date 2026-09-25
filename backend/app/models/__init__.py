"""
AURA Models Package
Import all models here so SQLAlchemy Base registers them for migrations.
"""
from app.models.user import User
from app.models.crm import Account, Contact
from app.models.email import Thread, Message
from app.models.intelligence import Classification
from app.models.knowledge import KBDocument, KBChunk, RAGRetrieval
from app.models.agent import AgentRun, Draft, Ticket, Escalation, LegalFlag
from app.models.web import MarketIntelCache
from app.models.audit import AuditLog

__all__ = [
    "User",
    "Account",
    "Contact",
    "Thread",
    "Message",
    "Classification",
    "KBDocument",
    "KBChunk",
    "RAGRetrieval",
    "AgentRun",
    "Draft",
    "Ticket",
    "Escalation",
    "LegalFlag",
    "MarketIntelCache",
    "AuditLog",
]
