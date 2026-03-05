def artifact_pdf_path(project_id: str, compile_key: str) -> str:
    return f"{project_id}/artifacts/{compile_key}.pdf"


def latest_pdf_path(project_id: str) -> str:
    return f"{project_id}/latest.pdf"
