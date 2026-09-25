"""Initial AURA schema — all entities

Revision ID: 001
Revises: 
Create Date: 2026-09-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from alembic import op

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable required extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')

    # --- users ---
    op.create_table(
        'users',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('role', sa.String(50), nullable=False),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_users_email', 'users', ['email'])

    # --- accounts ---
    op.create_table(
        'accounts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('industry', sa.String(100), nullable=True),
        sa.Column('plan', sa.String(50), nullable=True),
        sa.Column('billing_status', sa.String(50), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # --- contacts ---
    op.create_table(
        'contacts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('account_id', UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=True),
        sa.Column('operational_status', sa.String(50), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_contacts_email', 'contacts', ['email'])

    # --- threads ---
    op.create_table(
        'threads',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('external_thread_id', sa.String(500), nullable=True, unique=True),
        sa.Column('external_reply_reference_ids', JSONB, nullable=True),
        sa.Column('subject', sa.String(500), nullable=True),
        sa.Column('queue', sa.String(50), nullable=False, server_default='support_operations'),
        sa.Column('status', sa.String(50), nullable=False, server_default='open'),
        sa.Column('contact_id', UUID(as_uuid=True), sa.ForeignKey('contacts.id'), nullable=True),
        sa.Column('account_id', UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_threads_external_thread_id', 'threads', ['external_thread_id'])
    op.create_index('ix_threads_contact_retrieval', 'threads', ['contact_id', 'last_message_at'])

    # --- messages ---
    op.create_table(
        'messages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('external_message_id', sa.String(500), nullable=False, unique=True),
        sa.Column('thread_id', UUID(as_uuid=True), sa.ForeignKey('threads.id'), nullable=True),
        sa.Column('contact_id', UUID(as_uuid=True), sa.ForeignKey('contacts.id'), nullable=True),
        sa.Column('sender_email', sa.String(255), nullable=False),
        sa.Column('subject', sa.String(500), nullable=True),
        sa.Column('body_sanitized', sa.Text, nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('job_id', UUID(as_uuid=True), nullable=True),
        sa.Column('job_status', sa.String(50), nullable=False, server_default='pending'),
    )
    op.create_index('ix_messages_external_message_id', 'messages', ['external_message_id'], unique=True)
    op.create_index('ix_messages_thread_id', 'messages', ['thread_id'])
    op.create_index('ix_messages_received_at', 'messages', ['received_at'])

    # --- classifications ---
    op.create_table(
        'classifications',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('message_id', UUID(as_uuid=True), sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('contact_id', UUID(as_uuid=True), sa.ForeignKey('contacts.id'), nullable=True),
        sa.Column('thread_id', UUID(as_uuid=True), sa.ForeignKey('threads.id'), nullable=True),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('urgency', sa.String(20), nullable=False),
        sa.Column('sentiment_score', sa.Float, nullable=False),
        sa.Column('confidence', sa.Float, nullable=False),
        sa.Column('human_review_required', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('entities', JSONB, nullable=True),
        sa.Column('rationale', sa.Text, nullable=True),
        sa.Column('proposed_action', sa.Text, nullable=True),
        sa.Column('model_name', sa.String(100), nullable=False, server_default='gemini-1.5-flash'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_classifications_message_id', 'classifications', ['message_id'])
    op.create_index('ix_classifications_contact_id', 'classifications', ['contact_id'])
    # Composite index for sentiment trend queries
    op.create_index('ix_classifications_contact_sentiment', 'classifications', ['contact_id', 'created_at'])

    # --- kb_documents ---
    op.create_table(
        'kb_documents',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False, unique=True),
        sa.Column('version', sa.String(50), nullable=False, server_default='1.0.0'),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # --- kb_chunks ---
    op.create_table(
        'kb_chunks',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('document_id', UUID(as_uuid=True), sa.ForeignKey('kb_documents.id'), nullable=False),
        sa.Column('chunk_index', sa.Integer, nullable=False),
        sa.Column('token_start', sa.Integer, nullable=False),
        sa.Column('token_end', sa.Integer, nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('embedding', sa.Text, nullable=False),  # stored as vector type via raw SQL below
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    # Use raw SQL for vector column (pgvector type not in standard SA types)
    op.execute('ALTER TABLE kb_chunks ALTER COLUMN embedding TYPE vector(384) USING embedding::vector(384)')
    op.create_index('ix_kb_chunks_document_id', 'kb_chunks', ['document_id'])
    # pgvector ivfflat cosine similarity index
    op.execute('CREATE INDEX ix_kb_chunks_embedding_cosine ON kb_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10)')

    # --- agent_runs (needed before rag_retrievals FK) ---
    op.create_table(
        'agent_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('message_id', UUID(as_uuid=True), sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('classification_id', UUID(as_uuid=True), sa.ForeignKey('classifications.id'), nullable=True),
        sa.Column('mode', sa.String(20), nullable=False, server_default='live'),
        sa.Column('tool_calls_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('trace', JSONB, nullable=True),
        sa.Column('outcome', sa.String(50), nullable=False, server_default='completed'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_agent_runs_message_id', 'agent_runs', ['message_id'])

    # --- rag_retrievals ---
    op.create_table(
        'rag_retrievals',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('agent_run_id', UUID(as_uuid=True), sa.ForeignKey('agent_runs.id'), nullable=True),
        sa.Column('classification_id', UUID(as_uuid=True), sa.ForeignKey('classifications.id'), nullable=True),
        sa.Column('chunk_id', UUID(as_uuid=True), sa.ForeignKey('kb_chunks.id'), nullable=False),
        sa.Column('rank', sa.Integer, nullable=False),
        sa.Column('score', sa.Float, nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # --- drafts ---
    op.create_table(
        'drafts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('agent_run_id', UUID(as_uuid=True), sa.ForeignKey('agent_runs.id'), nullable=True),
        sa.Column('message_id', UUID(as_uuid=True), sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('body', sa.Text, nullable=False),
        sa.Column('tone', sa.String(50), nullable=False, server_default='empathetic'),
        sa.Column('citations', JSONB, nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending_approval'),
        sa.Column('approved_by', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # --- tickets ---
    op.create_table(
        'tickets',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('source_message_id', UUID(as_uuid=True), sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('agent_run_id', UUID(as_uuid=True), sa.ForeignKey('agent_runs.id'), nullable=True),
        sa.Column('assignee_queue', sa.String(50), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('body', sa.Text, nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # --- escalations ---
    op.create_table(
        'escalations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('source_message_id', UUID(as_uuid=True), sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('agent_run_id', UUID(as_uuid=True), sa.ForeignKey('agent_runs.id'), nullable=True),
        sa.Column('queue', sa.String(50), nullable=False),
        sa.Column('priority', sa.String(20), nullable=False),
        sa.Column('brief', sa.Text, nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='open'),
        sa.Column('resolved_by', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_notes', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # --- legal_flags ---
    op.create_table(
        'legal_flags',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('source_message_id', UUID(as_uuid=True), sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('agent_run_id', UUID(as_uuid=True), sa.ForeignKey('agent_runs.id'), nullable=True),
        sa.Column('issue_type', sa.String(100), nullable=False),
        sa.Column('summary', sa.Text, nullable=False),
        sa.Column('legal_status', sa.String(50), nullable=False, server_default='open'),
        sa.Column('resolved_by', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # --- market_intel_cache ---
    op.create_table(
        'market_intel_cache',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('target_url', sa.String(500), nullable=False),
        sa.Column('target_type', sa.String(50), nullable=False),
        sa.Column('response_data', JSONB, nullable=True),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('error_message', sa.Text, nullable=True),
    )
    op.create_index('ix_market_intel_cache_target_url', 'market_intel_cache', ['target_url'])

    # --- audit_log ---
    op.create_table(
        'audit_log',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('actor_id', UUID(as_uuid=True), nullable=True),
        sa.Column('actor_email', sa.String(255), nullable=False),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', UUID(as_uuid=True), nullable=False),
        sa.Column('change_metadata', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_audit_log_entity_id', 'audit_log', ['entity_id'])
    op.create_index('ix_audit_log_created_at', 'audit_log', ['created_at'])


def downgrade() -> None:
    op.drop_table('audit_log')
    op.drop_table('market_intel_cache')
    op.drop_table('legal_flags')
    op.drop_table('escalations')
    op.drop_table('tickets')
    op.drop_table('drafts')
    op.drop_table('rag_retrievals')
    op.drop_table('agent_runs')
    op.drop_table('kb_chunks')
    op.drop_table('kb_documents')
    op.drop_table('classifications')
    op.drop_table('messages')
    op.drop_table('threads')
    op.drop_table('contacts')
    op.drop_table('accounts')
    op.drop_table('users')
