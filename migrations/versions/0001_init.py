
"""initial schema

Revision ID: 0001_init
Revises: 
Create Date: 2025-09-23

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_init'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # enums
    role_enum = sa.Enum('admin','chef','secouriste','viewer', name='role_enum')
    event_status = sa.Enum('draft','preparing','validated', name='event_status')
    item_state = sa.Enum('pending','checked', name='item_state')
    role_enum.create(op.get_bind(), checkfirst=True)
    event_status.create(op.get_bind(), checkfirst=True)
    item_state.create(op.get_bind(), checkfirst=True)

    # user
    op.create_table('user',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=120), nullable=True),
        sa.Column('role', role_enum, nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    op.create_index('ix_user_email', 'user', ['email'], unique=False)

    # inventory_node
    op.create_table('inventory_node',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('is_leaf', sa.Boolean(), nullable=False),
        sa.Column('expected_qty', sa.Integer(), nullable=True),
        sa.Column('icon', sa.String(length=64), nullable=True),
        sa.Column('path', sa.String(length=1024), nullable=True),
        sa.Column('position', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['parent_id'], ['inventory_node.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_inventory_node_path', 'inventory_node', ['path'], unique=False)

    # event
    op.create_table('event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=True),
        sa.Column('location', sa.String(length=255), nullable=True),
        sa.Column('status', event_status, nullable=False),
        sa.Column('share_token', sa.String(length=64), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('share_token')
    )

    # event_item
    op.create_table('event_item',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('node_id', sa.Integer(), nullable=False),
        sa.Column('include', sa.Boolean(), nullable=False),
        sa.Column('required_qty', sa.Integer(), nullable=True),
        sa.Column('state', item_state, nullable=False),
        sa.Column('checked_by', sa.Integer(), nullable=True),
        sa.Column('checked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['checked_by'], ['user.id'], ),
        sa.ForeignKeyConstraint(['event_id'], ['event.id'], ),
        sa.ForeignKeyConstraint(['node_id'], ['inventory_node.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id', 'node_id', name='uq_event_node')
    )
    op.create_index('ix_event_item_event_id', 'event_item', ['event_id'], unique=False)
    op.create_index('ix_event_item_node_id', 'event_item', ['node_id'], unique=False)

    # presence
    op.create_table('presence',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        sa.Column('device_info', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['event_id'], ['event.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_presence_event_id', 'presence', ['event_id'], unique=False)
    op.create_index('ix_presence_user_id', 'presence', ['user_id'], unique=False)
    op.create_index('ix_presence_last_seen_at', 'presence', ['last_seen_at'], unique=False)

    # activity_log
    op.create_table('activity_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('event_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('target_node_id', sa.Integer(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['event_id'], ['event.id'], ),
        sa.ForeignKeyConstraint(['target_node_id'], ['inventory_node.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_activity_log_created_at', 'activity_log', ['created_at'], unique=False)

def downgrade() -> None:
    op.drop_index('ix_activity_log_created_at', table_name='activity_log')
    op.drop_table('activity_log')

    op.drop_index('ix_presence_last_seen_at', table_name='presence')
    op.drop_index('ix_presence_user_id', table_name='presence')
    op.drop_index('ix_presence_event_id', table_name='presence')
    op.drop_table('presence')

    op.drop_index('ix_event_item_node_id', table_name='event_item')
    op.drop_index('ix_event_item_event_id', table_name='event_item')
    op.drop_table('event_item')

    op.drop_table('event')

    op.drop_index('ix_inventory_node_path', table_name='inventory_node')
    op.drop_table('inventory_node')

    op.drop_index('ix_user_email', table_name='user')
    op.drop_table('user')

    sa.Enum(name='item_state').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='event_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='role_enum').drop(op.get_bind(), checkfirst=True)
