from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Campus(Base, TimestampMixin):
    __tablename__ = "campuses"

    campus_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    active_configuration_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
