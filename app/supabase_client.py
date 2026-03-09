import asyncio
import logging
from typing import Optional

from supabase import create_client, Client

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: Optional[Client] = None
_compile_artifacts_table_available: Optional[bool] = None


def get_supabase_client() -> Client:
    global _client
    if _client is None:
        settings = get_settings()
        _client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _client


async def get_project_tex(project_id: str) -> Optional[str]:
    """Fetch tex content for a project from the database."""
    try:
        response = await asyncio.to_thread(_get_project_tex_sync, project_id)
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
        await asyncio.to_thread(
            _save_compile_result_sync,
            project_id,
            status,
            log,
            pdf_path,
        )
        return True
    except Exception as e:
        logger.error(f"Failed to save compile result for project {project_id}: {e}")
        return False


async def upload_pdf(pdf_bytes: bytes, path: str) -> bool:
    """Upload PDF to Supabase Storage bucket."""
    try:
        await asyncio.to_thread(_upload_pdf_sync, pdf_bytes, path)
        return True
    except Exception as e:
        logger.error(f"Failed to upload PDF to {path}: {e}")
        return False


async def create_signed_url(path: str, expires_in: int = 3600) -> str:
    """Create a signed URL for a PDF in storage."""
    try:
        response = await asyncio.to_thread(_create_signed_url_sync, path, expires_in)
        return response.get("signedURL", "")
    except Exception as e:
        logger.error(f"Failed to create signed URL for {path}: {e}")
        return ""


async def get_share_project(token: str) -> Optional[dict]:
    """Fetch a non-revoked share token and its project name."""
    try:
        share_response = await asyncio.to_thread(_get_share_project_sync, token)
        share_data = share_response.data if share_response else None
        if not isinstance(share_data, dict):
            return None

        project_id = share_data.get("project_id")
        if not project_id:
            return None

        project_response = await asyncio.to_thread(_get_project_name_sync, project_id)
        project_data = project_response.data if project_response else None
        if not isinstance(project_data, dict):
            return None

        project_name = project_data.get("name")
        if not isinstance(project_name, str) or not project_name.strip():
            project_name = "Untitled project"

        return {
            "project_id": project_id,
            "project_name": project_name,
        }
    except Exception as e:
        logger.warning(f"Failed to fetch share token {token}: {e}")
        return None


async def get_compile_artifact(compile_key: str) -> Optional[dict]:
    global _compile_artifacts_table_available
    if _compile_artifacts_table_available is False:
        return None
    try:
        response = await asyncio.to_thread(_get_compile_artifact_sync, compile_key)
        _compile_artifacts_table_available = True
        return response.data if response and response.data else None
    except Exception as e:
        if _is_missing_compile_artifacts_table_error(e):
            _compile_artifacts_table_available = False
            logger.info("compile_artifacts table not found; disabling persistent artifact cache lookup")
            return None
        logger.warning(f"Failed to fetch compile artifact {compile_key}: {e}")
        return None


async def upsert_compile_artifact(
    compile_key: str,
    project_id: str,
    pdf_path: str,
    engine: str,
    flags: str,
) -> bool:
    global _compile_artifacts_table_available
    if _compile_artifacts_table_available is False:
        return True
    try:
        await asyncio.to_thread(
            _upsert_compile_artifact_sync,
            compile_key,
            project_id,
            pdf_path,
            engine,
            flags,
        )
        _compile_artifacts_table_available = True
        return True
    except Exception as e:
        if _is_missing_compile_artifacts_table_error(e):
            _compile_artifacts_table_available = False
            logger.info("compile_artifacts table not found; disabling persistent artifact cache writes")
            return True
        logger.warning(f"Failed to upsert compile artifact {compile_key}: {e}")
        return False


async def get_latest_successful_compile(project_id: str) -> Optional[dict]:
    """Fetch latest successful compile row for project."""
    try:
        response = await asyncio.to_thread(_get_latest_successful_compile_sync, project_id)
        data = response.data or []
        if not data:
            return None
        first = data[0]
        return first if isinstance(first, dict) else None
    except Exception as e:
        logger.warning(f"Failed to fetch latest successful compile for {project_id}: {e}")
        return None


def _get_project_tex_sync(project_id: str):
    client = get_supabase_client()
    return client.table("projects").select("tex").eq("id", project_id).single().execute()


def _save_compile_result_sync(project_id: str, status: str, log: Optional[str], pdf_path: Optional[str]):
    client = get_supabase_client()
    client.table("compiles").insert(
        {
            "project_id": project_id,
            "status": status,
            "log": log,
            "pdf_path": pdf_path,
        }
    ).execute()


def _upload_pdf_sync(pdf_bytes: bytes, path: str):
    client = get_supabase_client()
    client.storage.from_("project-pdfs").upload(
        path,
        pdf_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )


def _create_signed_url_sync(path: str, expires_in: int):
    client = get_supabase_client()
    return client.storage.from_("project-pdfs").create_signed_url(path, expires_in)


def _get_share_project_sync(token: str):
    client = get_supabase_client()
    return (
        client.table("shares")
        .select("project_id")
        .eq("token", token)
        .is_("revoked_at", "null")
        .single()
        .execute()
    )


def _get_project_name_sync(project_id: str):
    client = get_supabase_client()
    return client.table("projects").select("name").eq("id", project_id).single().execute()


def _get_compile_artifact_sync(compile_key: str):
    client = get_supabase_client()
    return (
        client.table("compile_artifacts")
        .select("*")
        .eq("compile_key", compile_key)
        .single()
        .execute()
    )


def _upsert_compile_artifact_sync(
    compile_key: str,
    project_id: str,
    pdf_path: str,
    engine: str,
    flags: str,
):
    client = get_supabase_client()
    client.table("compile_artifacts").upsert(
        {
            "compile_key": compile_key,
            "project_id": project_id,
            "pdf_path": pdf_path,
            "engine": engine,
            "flags": flags,
        }
    ).execute()


def _get_latest_successful_compile_sync(project_id: str):
    client = get_supabase_client()
    return (
        client.table("compiles")
        .select("pdf_path, compiled_at")
        .eq("project_id", project_id)
        .eq("status", "success")
        .order("compiled_at", desc=True)
        .limit(1)
        .execute()
    )


def _is_missing_compile_artifacts_table_error(exc: Exception) -> bool:
    return "PGRST205" in str(exc) or "compile_artifacts" in str(exc)
