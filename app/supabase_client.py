import logging
from typing import Optional

from supabase import create_client, Client

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: Optional[Client] = None


def get_supabase_client() -> Client:
    global _client
    if _client is None:
        settings = get_settings()
        _client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _client


async def get_project_tex(project_id: str) -> Optional[str]:
    """Fetch tex content for a project from the database."""
    try:
        client = get_supabase_client()
        response = client.table("projects").select("tex").eq("id", project_id).single().execute()
        if response.data:
            return response.data.get("tex")
        return None
    except Exception as e:
        logger.error(f"Failed to fetch project {project_id}: {e}")
        return None


async def save_compile_result(
    project_id: str,
    status: str,
    log: Optional[str],
    pdf_path: Optional[str],
) -> bool:
    """Save compile result to the compiles table."""
    try:
        client = get_supabase_client()
        client.table("compiles").insert({
            "project_id": project_id,
            "status": status,
            "log": log,
            "pdf_path": pdf_path,
        }).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to save compile result for project {project_id}: {e}")
        return False


async def upload_pdf(pdf_bytes: bytes, path: str) -> bool:
    """Upload PDF to Supabase Storage bucket."""
    try:
        client = get_supabase_client()
        client.storage.from_("project-pdfs").upload(
            path,
            pdf_bytes,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )
        return True
    except Exception as e:
        logger.error(f"Failed to upload PDF to {path}: {e}")
        return False


async def create_signed_url(path: str, expires_in: int = 3600) -> str:
    """Create a signed URL for a PDF in storage."""
    try:
        client = get_supabase_client()
        response = client.storage.from_("project-pdfs").create_signed_url(path, expires_in)
        return response.get("signedURL", "")
    except Exception as e:
        logger.error(f"Failed to create signed URL for {path}: {e}")
        return ""
