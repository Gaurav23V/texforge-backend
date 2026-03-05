-- TexForge Database Schema
-- Run this in Supabase SQL Editor to set up required tables and storage

-- Projects table: stores LaTeX projects
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    tex TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ DEFAULT now(),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Compiles table: stores compile history and results
CREATE TABLE IF NOT EXISTS compiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    log TEXT,
    pdf_path TEXT,
    compiled_at TIMESTAMPTZ DEFAULT now()
);

-- Compile artifacts table: maps deterministic compile keys to storage objects.
CREATE TABLE IF NOT EXISTS compile_artifacts (
    compile_key TEXT PRIMARY KEY,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    pdf_path TEXT NOT NULL,
    engine TEXT NOT NULL,
    flags TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Shares table: stores view-only share tokens
CREATE TABLE IF NOT EXISTS shares (
    token TEXT PRIMARY KEY,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now(),
    revoked_at TIMESTAMPTZ
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_projects_owner_id ON projects(owner_id);
CREATE INDEX IF NOT EXISTS idx_compiles_project_id ON compiles(project_id);
CREATE INDEX IF NOT EXISTS idx_compile_artifacts_project_id ON compile_artifacts(project_id);
CREATE INDEX IF NOT EXISTS idx_shares_project_id ON shares(project_id);

-- Update trigger for projects.updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS projects_updated_at ON projects;
CREATE TRIGGER projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS compile_artifacts_updated_at ON compile_artifacts;
CREATE TRIGGER compile_artifacts_updated_at
    BEFORE UPDATE ON compile_artifacts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- RLS Policies for projects (frontend uses user JWT)
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own projects"
    ON projects FOR SELECT
    USING (auth.uid() = owner_id);

CREATE POLICY "Users can create own projects"
    ON projects FOR INSERT
    WITH CHECK (auth.uid() = owner_id);

CREATE POLICY "Users can update own projects"
    ON projects FOR UPDATE
    USING (auth.uid() = owner_id);

CREATE POLICY "Users can delete own projects"
    ON projects FOR DELETE
    USING (auth.uid() = owner_id);

-- Service role bypass for backend (uses service key)
CREATE POLICY "Service role full access to projects"
    ON projects FOR ALL
    USING (auth.jwt() ->> 'role' = 'service_role');

-- RLS Policies for compiles
ALTER TABLE compiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view compiles for own projects"
    ON compiles FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM projects
            WHERE projects.id = compiles.project_id
            AND projects.owner_id = auth.uid()
        )
    );

CREATE POLICY "Service role full access to compiles"
    ON compiles FOR ALL
    USING (auth.jwt() ->> 'role' = 'service_role');

-- RLS Policies for shares
ALTER TABLE shares ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Anyone can view non-revoked shares"
    ON shares FOR SELECT
    USING (revoked_at IS NULL);

CREATE POLICY "Users can create shares for own projects"
    ON shares FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM projects
            WHERE projects.id = shares.project_id
            AND projects.owner_id = auth.uid()
        )
    );

CREATE POLICY "Users can revoke shares for own projects"
    ON shares FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM projects
            WHERE projects.id = shares.project_id
            AND projects.owner_id = auth.uid()
        )
    );

CREATE POLICY "Service role full access to shares"
    ON shares FOR ALL
    USING (auth.jwt() ->> 'role' = 'service_role');

-- RLS Policies for compile_artifacts
ALTER TABLE compile_artifacts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access to compile artifacts"
    ON compile_artifacts FOR ALL
    USING (auth.jwt() ->> 'role' = 'service_role');
