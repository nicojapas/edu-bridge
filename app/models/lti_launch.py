"""
LTI Launch Context Model

Stores launch information so we can reference it later for grade submission.
"""

from datetime import datetime
from sqlalchemy import String, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LtiLaunch(Base):
    __tablename__ = "lti_launches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_sub: Mapped[str] = mapped_column(String(255), index=True)
    context_id: Mapped[str] = mapped_column(String(255), index=True)
    resource_link_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deployment_id: Mapped[str] = mapped_column(String(255))

    # AGS endpoints (nullable - not all launches have AGS)
    lineitem_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    lineitems_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    ags_scopes: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array

    # User info for display
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    roles: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
