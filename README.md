# TexForge Backend

LaTeX to PDF compilation service for TexForge. Accepts LaTeX source, compiles it in a sandboxed environment, and returns a signed PDF URL.

## Live Demo

- **Backend API**: https://texforge-backend-0ap1.onrender.com
- **Frontend App**: https://texforge-frontend-lsmd.onrender.com
- **Health Check**: https://texforge-backend-0ap1.onrender.com/health

## What It Does

- **POST /compile**: Compiles LaTeX to PDF
  - Accepts `project_id` (fetches tex from DB) or inline `tex` content
  - Runs `latexmk` in a sandboxed temp directory with `-no-shell-escape`
  - Enforces 15s timeout and blocks dangerous patterns (`\write18`, etc.)
  - Uploads PDF to Supabase Storage and returns signed URL
  - Stores compile logs in database

- **GET /health**: Health check endpoint

## Quick Start

### Local Development (without Docker)

1. Install TeX toolchain:
   ```bash
   # Ubuntu/Debian
   sudo apt-get install texlive-latex-base texlive-latex-extra texlive-fonts-recommended latexmk

   # macOS
   brew install --cask mactex-no-gui
   ```

2. Install dependencies with uv:
   ```bash
   uv sync
   ```

3. Set up environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your Supabase credentials
   ```

4. Run the server:
   ```bash
   uv run uvicorn app.main:app --reload
   ```

### Docker

```bash
# Build and run
docker compose up --build

# Or build manually
docker build -t texforge-backend .
docker run -p 8000:8000 --env-file .env texforge-backend
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SUPABASE_URL` | Yes | - | Your Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Yes | - | Supabase service role key |
| `MAX_CONCURRENT_COMPILES` | No | 2 | Max parallel compiles |

## Running Tests

```bash
# Install dev dependencies
uv sync --extra dev

# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_security.py
```

## Supabase Setup

Run these SQL scripts in Supabase SQL Editor:

1. **Create tables**: `supabase/schema.sql`
2. **Create storage bucket**: `supabase/storage.sql`

Or create manually in Supabase Dashboard:

### Tables

**projects**
- `id` (UUID, PK)
- `owner_id` (UUID, FK to auth.users)
- `name` (TEXT)
- `tex` (TEXT)
- `updated_at`, `created_at` (TIMESTAMPTZ)

**compiles**
- `id` (UUID, PK)
- `project_id` (UUID, FK to projects)
- `status` (TEXT: 'success' | 'error')
- `log` (TEXT)
- `pdf_path` (TEXT)
- `compiled_at` (TIMESTAMPTZ)

**shares**
- `token` (TEXT, PK)
- `project_id` (UUID, FK to projects)
- `created_at`, `revoked_at` (TIMESTAMPTZ)

### Storage

Create a private bucket named `project-pdfs`. The backend uploads PDFs to:
```
project-pdfs/{project_id}/latest.pdf
```

## API Usage

### Compile with inline TeX

```bash
curl -X POST http://localhost:8000/compile \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "550e8400-e29b-41d4-a716-446655440000",
    "tex": "\\documentclass{article}\\begin{document}Hello\\end{document}"
  }'
```

### Compile from database

```bash
curl -X POST http://localhost:8000/compile \
  -H "Content-Type: application/json" \
  -d '{"project_id": "550e8400-e29b-41d4-a716-446655440000"}'
```

### Success Response

```json
{
  "status": "success",
  "pdf_url": "https://storage.supabase.co/.../latest.pdf?token=...",
  "compiled_at": "2024-01-15T10:30:00Z"
}
```

### Error Response

```json
{
  "status": "error",
  "error_type": "latex_compile_error",
  "log": "! Undefined control sequence...",
  "compiled_at": "2024-01-15T10:30:00Z"
}
```

## Security

- **Sandbox**: Compiles run with `-no-shell-escape` in isolated temp directories
- **Timeout**: 15 second hard limit per compile
- **Size limit**: 1MB max TeX content
- **Blocked patterns**: `\write18`, `\input{http`, `\include{http`, pipe input
- **Concurrency**: Semaphore limits parallel compiles (default: 2)

## Architecture

See [TRD.md](TRD.md) for full technical requirements.
