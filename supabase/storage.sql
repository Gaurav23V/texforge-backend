-- Storage bucket setup for project PDFs
-- Run this in Supabase SQL Editor

-- Create the storage bucket (if not using Supabase Dashboard)
INSERT INTO storage.buckets (id, name, public)
VALUES ('project-pdfs', 'project-pdfs', false)
ON CONFLICT (id) DO NOTHING;

-- Storage policies: service role can upload/manage, users can read own project PDFs

-- Policy for service role to upload PDFs (backend compiler)
CREATE POLICY "Service role can upload PDFs"
    ON storage.objects FOR INSERT
    WITH CHECK (
        bucket_id = 'project-pdfs'
        AND auth.jwt() ->> 'role' = 'service_role'
    );

CREATE POLICY "Service role can update PDFs"
    ON storage.objects FOR UPDATE
    USING (
        bucket_id = 'project-pdfs'
        AND auth.jwt() ->> 'role' = 'service_role'
    );

-- Policy for users to read PDFs of their own projects
-- Path formats:
-- - {project_id}/latest.pdf
-- - {project_id}/artifacts/{compile_key}.pdf
CREATE POLICY "Users can read own project PDFs"
    ON storage.objects FOR SELECT
    USING (
        bucket_id = 'project-pdfs'
        AND EXISTS (
            SELECT 1 FROM projects
            WHERE projects.id::text = (storage.foldername(name))[1]
            AND projects.owner_id = auth.uid()
        )
    );

-- Policy for shared project PDFs (via share token lookup)
-- This would typically be done via signed URLs from the backend
