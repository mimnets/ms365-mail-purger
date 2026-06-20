import asyncio
import subprocess
import time
import os
import tempfile
import traceback
from datetime import datetime
from celery_app import celery_app
from database import SessionLocal
from models import PurgeJob, JobStatus, Organization
from cert_utils import decrypt_value, get_fernet

BATCH_SIZE = 10
SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "scripts", "purge.ps1")


def _update_job(db, job_id: str, **kwargs):
    job = db.query(PurgeJob).filter(PurgeJob.id == job_id).first()
    if job:
        for k, v in kwargs.items():
            setattr(job, k, v)
        db.commit()
    return job


def _write_stop_flag(job_id: str):
    """Write a flag file that the pwsh process checks between chunks."""
    flag_path = f"/tmp/stop_{job_id}.flag"
    with open(flag_path, "w") as f:
        f.write("stop")
    return flag_path


def _remove_stop_flag(job_id: str):
    flag_path = f"/tmp/stop_{job_id}.flag"
    if os.path.exists(flag_path):
        os.unlink(flag_path)


@celery_app.task(bind=True, name="purge_engine.purge_loop")
def purge_loop(self, job_id: str, org_id: str, user_email: str, date_from: str, date_to: str):
    """
    Purge job using Connect-IPPSSession via pwsh subprocess.
    Reads machine-readable output from the PowerShell script
    and updates the database progressively.
    """
    db = SessionLocal()
    temp_cert_path = None

    try:
        _update_job(db, job_id,
            status=JobStatus.RUNNING,
            started_at=datetime.utcnow(),
            celery_task_id=self.request.id
        )

        # ── Load org & decrypt credentials ──────────────────────────────────
        org = db.query(Organization).filter(Organization.id == org_id).first()
        if not org:
            raise ValueError(f"Organization {org_id} not found")

        fernet = get_fernet()

        if not org.certificate_pfx or not org.certificate_password:
            raise ValueError(f"Organization '{org.name}' has no certificate configured. Generate one in Settings first.")

        cert_pfx_bytes_b64 = decrypt_value(org.certificate_pfx, fernet)
        cert_pass_plain = decrypt_value(org.certificate_password, fernet)

        # Write cert to temp file (pwsh can read PFX files directly)
        cert_data = cert_pfx_bytes_b64.encode()  # base64 encoded bytes from encryption
        # Actually decrypt_value returns the plaintext which is the base64-encoded cert bytes
        # Let me fix this: certificate_pfx stores the raw PFX bytes base64-encoded then fernet-encrypted
        # So after decrypt_value, we get back the base64 string of the PFX
        # We need to decode base64 to get raw PFX bytes
        import base64
        try:
            raw_pfx = base64.b64decode(cert_pfx_bytes_b64)
        except Exception:
            # Maybe it's already raw bytes in string form
            raw_pfx = cert_pfx_bytes_b64.encode('latin-1')

        fd, temp_cert_path = tempfile.mkstemp(suffix=".pfx")
        os.write(fd, raw_pfx)
        os.close(fd)

        # ── Build pwsh args ─────────────────────────────────────────────────
        args = [
            "pwsh", "-NoLogo", "-NoProfile", "-File", SCRIPT_PATH,
            "-AppId", org.app_client_id,
            "-CertPath", temp_cert_path,
            "-CertPass", cert_pass_plain,
            "-Organization", org.tenant_domain,
            "-TenantId", org.tenant_id,
            "-Email", user_email,
            "-DateFrom", date_from,
            "-DateTo", date_to,
            "-JobId", job_id,
        ]

        # ── Execute pwsh and parse output ───────────────────────────────────
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        total_found = 0
        total_deleted = 0
        last_error = None

        for line in iter(process.stdout.readline, ""):
            line = line.strip()
            if not line:
                continue

            parts = line.split("|")
            action = parts[0]

            if action == "STATUS":
                # Info messages, not progress
                pass

            elif action == "CHUNK":
                # e.g. CHUNK|2024-01-01|2024-01-07
                pass

            elif action == "FOUND":
                if len(parts) > 1:
                    chunk_found = int(parts[1])
                    total_found += chunk_found
                    _update_job(db, job_id,
                        total_found=total_found,
                        total_remaining=total_found - total_deleted
                    )

            elif action == "DELETED":
                if len(parts) > 1:
                    total_deleted = int(parts[1])
                    remaining = max(0, total_found - total_deleted)
                    _update_job(db, job_id,
                        total_deleted=total_deleted,
                        total_remaining=remaining
                    )

            elif action == "ERROR":
                if len(parts) > 1:
                    last_error = parts[1]
                    _update_job(db, job_id, error_message=last_error)

            elif action == "DONE":
                if len(parts) > 2:
                    total_deleted = int(parts[1])
                    total_found = int(parts[2])

            elif action == "FATAL":
                last_error = parts[1] if len(parts) > 1 else "Unknown fatal error"
                _update_job(db, job_id, error_message=last_error)

            # Check if user requested stop
            db.expire_all()
            job = db.query(PurgeJob).filter(PurgeJob.id == job_id).first()
            if job and job.status == JobStatus.STOPPED:
                _write_stop_flag(job_id)
                process.terminate()
                break

        process.wait(timeout=60)

        # ── Determine final status ──────────────────────────────────────────
        db.expire_all()
        job = db.query(PurgeJob).filter(PurgeJob.id == job_id).first()

        if job and job.status != JobStatus.STOPPED:
            if process.returncode == 0:
                _update_job(db, job_id,
                    status=JobStatus.COMPLETE,
                    total_deleted=total_deleted,
                    total_remaining=max(0, total_found - total_deleted),
                    completed_at=datetime.utcnow()
                )
            else:
                stderr_out = process.stderr.read()[:1000]
                err_msg = last_error or f"pwsh exited with code {process.returncode}"
                if stderr_out:
                    err_msg += f" | {stderr_out}"
                _update_job(db, job_id,
                    status=JobStatus.FAILED,
                    error_message=err_msg,
                    completed_at=datetime.utcnow()
                )

    except Exception as e:
        _update_job(db, job_id,
            status=JobStatus.FAILED,
            error_message=f"{e}\n{traceback.format_exc()}",
            completed_at=datetime.utcnow()
        )
        raise

    finally:
        _remove_stop_flag(job_id)
        if temp_cert_path and os.path.exists(temp_cert_path):
            try:
                os.unlink(temp_cert_path)
            except Exception:
                pass
        db.close()
