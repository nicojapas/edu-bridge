"""
Submission Model

Stores student essay submissions with AI-generated scores and feedback.
"""

from datetime import datetime
from sqlalchemy import String, DateTime, Text, Integer, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.lti_launch import Base


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    launch_id: Mapped[int] = mapped_column(Integer, ForeignKey("lti_launches.id"), index=True)
    user_sub: Mapped[str] = mapped_column(String(255), index=True)
    essay_text: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float)
    feedback: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationship to launch
    launch: Mapped["LtiLaunch"] = relationship("LtiLaunch", backref="submissions")
