# D11 Demo Deployment (GoogieHost + Python backend)

This document applies only to the `demo/googiehost` branch. It must never be used to change the production deployment.

## Isolation guarantees

- Production `main` is not modified by this demo setup.
- The demo must use a newly created, empty PostgreSQL database.
- Never copy the production `DATABASE_URL`, `D11_DATABASE_URL`, admin token, or other production secrets into the demo.
- The demo collector workflow in this branch uses only the GitHub Actions secret `D11_DEMO_DATABASE_URL`. If that secret is absent, the workflow fails before running.
- Do not merge this branch into `main` as part of demo deployment.
- Do not run database migrations or imports against production from this branch.

## Repository and branch

- Repository: `jollyjattjunktion-beep/d11`
- Demo branch: `demo/googiehost`
- Application entry point: `app.main:app`
- Dependencies: `requirements.txt`
- Health endpoint: `/health`

## Python backend deployment (Koyeb candidate)

Create a separate Koyeb Web Service from GitHub:

- Repository: `jollyjattjunktion-beep/d11`
- Branch: `demo/googiehost`
- Build command: `pip install -r requirements.txt`
- Run command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/health`
- Use the free web instance only for a low-traffic demo, subject to its current resource and account-verification requirements.

Set these environment variables in the backend dashboard (never commit them):

- `APP_ENV=demo`
- `DATABASE_URL=<new demo-only Neon PostgreSQL connection string>`
- `ADMIN_TOKEN=<new long random demo-only secret>`

The repository normalizes `postgresql://` URLs to the installed psycopg v3 driver. Keep the provider's SSL requirement in the connection URL.

Do not set `D11_DATABASE_URL` on the demo service. Do not configure the production database as a fallback.

## Demo database

Create a separate Neon Free PostgreSQL project/database. Do not branch or clone production data into it. The app currently calls `Base.metadata.create_all(bind=engine)` during import, so its first start creates the application's tables in whichever database is supplied as `DATABASE_URL`. Verify the database host and database name before first start.

Neon's free plan has monthly compute, storage, and network limits; it scales to zero when idle. Treat this as demo capacity, not production-grade availability.

## GoogieHost public subdomain

1. Register a new GoogieHost free-hosting account and choose a free subdomain.
2. In DirectAdmin, open DNS Management for that subdomain.
3. After the backend is deployed, add the CNAME record Koyeb gives you when you add the exact GoogieHost subdomain as a custom domain in Koyeb.
4. Wait for DNS validation and automatic TLS certificate activation.
5. If the free backend tier/account does not permit custom domains, use the generated Koyeb `.koyeb.app` URL as the application URL and make the GoogieHost subdomain a simple redirect/landing page. Do not proxy or embed the backend unless the host explicitly supports it.

Never guess a CNAME target. Copy the exact target shown in the Koyeb dashboard.

## GitHub auto-deployment

Connect Koyeb to the repository and select only `demo/googiehost`. Enable deployment on pushes to that branch. This gives the demo its own GitHub-driven deployment path. Do not point the service at `main`.

For the optional demo collector workflow, add a repository Actions secret named `D11_DEMO_DATABASE_URL` containing only the new demo database URL. Never reuse `D11_DATABASE_URL`.

## Public exposure / security review required before launch

The current code has token-protected `/api/v1/admin/*` routes, but also contains write routes outside that namespace (including match/player/squad creation, history import, and team generation). Review and protect those routes before making the API public. The `/admin` and `/admin/stadiums` HTML pages are served publicly; the admin UI asks for an `X-Admin-Token` for its protected API calls. Use a unique demo token and do not reuse a production token.

Do not expose the demo until:
- the service reports healthy at `/health`;
- its database hostname is verified as the demo database;
- no production credentials are configured;
- public write endpoints have an explicit access policy;
- the existing pytest workflow passes on this branch.

## Rollback

Pause/delete only the demo Koyeb service and remove only the demo DNS record. Leave the production service, production database, production GitHub secrets, and `main` branch unchanged.
