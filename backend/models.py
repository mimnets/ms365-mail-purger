from sqlalchemy import Column, String, Integer, DateTime, Enum
from sqlalchemy.sql import func
from database import Base
import enum

class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    STOPPED = "STOPPED"

class PurgeJob(Base):
    __tablename__ = "purge_jobs"

    id = Column(String, primary_key=True)
    user_email = Column(String, nullable=False, index=True)
    date_from = Column(String, nullable=False)
    date_to = Column(String, nullable=False)
    status = Column(String, default=JobStatus.QUEUED)
    total_found = Column(Integer, default=0)
    total_deleted = Column(Integer, default=0)
    total_remaining = Column(Integer, default=0)
    batch_size = Column(Integer, default=10)
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(String, nullable=True)
    celery_task_id = Column(String, nullable=True)
