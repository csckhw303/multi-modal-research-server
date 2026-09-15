-- Local-dev-only role used by PostgREST to connect and serve requests.
-- Mirrors the "service_role" convention referenced by supabase/migrations/*.sql.
CREATE ROLE service_role WITH LOGIN PASSWORD 'service_role_password' NOSUPERUSER;
