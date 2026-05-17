import asyncio
import time
from datetime import datetime
from celery_app import celery_app
from database import SessionLocal
from models import PurgeJob, JobStatus
import graph

BATCH_SIZE = 10
SLEEP_BETWEEN_BATCHES = 1.0

def _update_job(db, job_id: str, **kwargs):
    job = db.query(PurgeJob).filter(PurgeJob.id == job_id).first()
    if job:
        for k, v in kwargs.items():
            setattr(job, k, v)
        db.commit()
    return job

@celery_app.task(bind=True, name="purge_engine.purge_loop")
def purge_loop(self, job_id: str, user_email: str, date_from: str, date_to: str):
    db = SessionLocal()

    try:
        _update_job(db, job_id,
            status=JobStatus.RUNNING,
            started_at=datetime.utcnow(),
            celery_task_id=self.request.id
        )

        initial_count = asyncio.run(
            graph.count_messages(user_email, date_from, date_to)
        )
        _update_job(db, job_id,
            total_found=initial_count,
            total_remaining=initial_count
        )

        total_deleted = 0

        while True:
            db.expire_all()
            job = db.query(PurgeJob).filter(PurgeJob.id == job_id).first()
            if not job or job.status in [JobStatus.STOPPED, JobStatus.FAILED]:
                break

            message_ids = asyncio.run(
                graph.search_messages(user_email, date_from, date_to, top=BATCH_SIZE)
            )

            if not message_ids:
                _update_job(db, job_id,
                    status=JobStatus.COMPLETE,
                    total_deleted=total_deleted,
                    total_remaining=0,
                    completed_at=datetime.utcnow()
                )
                break

            for msg_id in message_ids:
                success = asyncio.run(graph.delete_message(user_email, msg_id))
                if success:
                    total_deleted += 1
                time.sleep(0.1)

            remaining = max(0, initial_count - total_deleted)
            _update_job(db, job_id,
                total_deleted=total_deleted,
                total_remaining=remaining
            )

            time.sleep(SLEEP_BETWEEN_BATCHES)

    except Exception as e:
        _update_job(db, job_id,
            status=JobStatus.FAILED,
            error_message=str(e),
            completed_at=datetime.utcnow()
        )
        raise

    finally:
        db.close()
