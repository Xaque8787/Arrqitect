/*
  # Arrqitect Core Schema

  Creates the five core tables: app_templates, installed_apps, runtime_dependencies, jobs, job_steps.
  Enums: app_state, job_type, job_status, step_status.
  RLS enabled on all tables with policies for authenticated users.
*/

-- Enums (safe: only created if they don't exist)
DO $$ BEGIN
  CREATE TYPE app_state AS ENUM ('installing', 'running', 'stopped', 'error', 'removing');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE job_type AS ENUM ('install', 'update', 'remove', 'reconcile', 'preview');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE job_status AS ENUM ('pending', 'running', 'success', 'failed', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE step_status AS ENUM ('pending', 'running', 'success', 'failed', 'skipped');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- app_templates
CREATE TABLE IF NOT EXISTS app_templates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text UNIQUE NOT NULL,
  name text NOT NULL,
  description text NOT NULL DEFAULT '',
  icon_url text NOT NULL DEFAULT '',
  compose_template text NOT NULL DEFAULT '',
  config_schema jsonb NOT NULL DEFAULT '[]',
  hook_definitions jsonb NOT NULL DEFAULT '{}',
  provides jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE app_templates ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Authenticated users can read app_templates"
  ON app_templates FOR SELECT TO authenticated
  USING (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can insert app_templates"
  ON app_templates FOR INSERT TO authenticated
  WITH CHECK (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can update app_templates"
  ON app_templates FOR UPDATE TO authenticated
  USING (auth.uid() IS NOT NULL)
  WITH CHECK (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can delete app_templates"
  ON app_templates FOR DELETE TO authenticated
  USING (auth.uid() IS NOT NULL);

-- installed_apps
CREATE TABLE IF NOT EXISTS installed_apps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  template_id uuid NOT NULL REFERENCES app_templates(id),
  slug text NOT NULL,
  name text NOT NULL,
  config jsonb NOT NULL DEFAULT '{}',
  state app_state NOT NULL DEFAULT 'stopped',
  compose_path text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE installed_apps ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Authenticated users can read installed_apps"
  ON installed_apps FOR SELECT TO authenticated
  USING (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can insert installed_apps"
  ON installed_apps FOR INSERT TO authenticated
  WITH CHECK (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can update installed_apps"
  ON installed_apps FOR UPDATE TO authenticated
  USING (auth.uid() IS NOT NULL)
  WITH CHECK (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can delete installed_apps"
  ON installed_apps FOR DELETE TO authenticated
  USING (auth.uid() IS NOT NULL);

-- runtime_dependencies
CREATE TABLE IF NOT EXISTS runtime_dependencies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  consumer_id uuid NOT NULL REFERENCES installed_apps(id) ON DELETE CASCADE,
  provider_id uuid NOT NULL REFERENCES installed_apps(id) ON DELETE CASCADE,
  dependency_type text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (consumer_id, provider_id, dependency_type)
);

ALTER TABLE runtime_dependencies ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Authenticated users can read runtime_dependencies"
  ON runtime_dependencies FOR SELECT TO authenticated
  USING (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can insert runtime_dependencies"
  ON runtime_dependencies FOR INSERT TO authenticated
  WITH CHECK (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can update runtime_dependencies"
  ON runtime_dependencies FOR UPDATE TO authenticated
  USING (auth.uid() IS NOT NULL)
  WITH CHECK (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can delete runtime_dependencies"
  ON runtime_dependencies FOR DELETE TO authenticated
  USING (auth.uid() IS NOT NULL);

-- jobs
CREATE TABLE IF NOT EXISTS jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  installed_app_id uuid REFERENCES installed_apps(id) ON DELETE SET NULL,
  type job_type NOT NULL,
  status job_status NOT NULL DEFAULT 'pending',
  dry_run boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Authenticated users can read jobs"
  ON jobs FOR SELECT TO authenticated
  USING (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can insert jobs"
  ON jobs FOR INSERT TO authenticated
  WITH CHECK (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can update jobs"
  ON jobs FOR UPDATE TO authenticated
  USING (auth.uid() IS NOT NULL)
  WITH CHECK (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can delete jobs"
  ON jobs FOR DELETE TO authenticated
  USING (auth.uid() IS NOT NULL);

-- job_steps
CREATE TABLE IF NOT EXISTS job_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  step text NOT NULL DEFAULT '',
  status step_status NOT NULL DEFAULT 'pending',
  log text NOT NULL DEFAULT '',
  started_at timestamptz,
  finished_at timestamptz
);

ALTER TABLE job_steps ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Authenticated users can read job_steps"
  ON job_steps FOR SELECT TO authenticated
  USING (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can insert job_steps"
  ON job_steps FOR INSERT TO authenticated
  WITH CHECK (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can update job_steps"
  ON job_steps FOR UPDATE TO authenticated
  USING (auth.uid() IS NOT NULL)
  WITH CHECK (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can delete job_steps"
  ON job_steps FOR DELETE TO authenticated
  USING (auth.uid() IS NOT NULL);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_installed_apps_template_id ON installed_apps(template_id);
CREATE INDEX IF NOT EXISTS idx_installed_apps_slug ON installed_apps(slug);
CREATE INDEX IF NOT EXISTS idx_runtime_deps_consumer ON runtime_dependencies(consumer_id);
CREATE INDEX IF NOT EXISTS idx_runtime_deps_provider ON runtime_dependencies(provider_id);
CREATE INDEX IF NOT EXISTS idx_jobs_installed_app ON jobs(installed_app_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_job_steps_job_id ON job_steps(job_id);
