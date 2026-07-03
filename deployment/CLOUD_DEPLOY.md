# Cloud Deploy: AWS (production-shaped)

This is the deeper, step-by-step version of Path 2 in [`deployment/README.md`](README.md): a
containerized backend on App Runner, managed Postgres, secrets out of the codebase, and a build
gated on the existing CI checks before an image ships.

## 1. Architecture recap

Static frontend on CloudFront + S3 (or Vercel, see step 3.6), a single containerized backend on
App Runner talking to RDS Postgres, S3 for creator uploads, Secrets Manager for credentials, and
TwelveLabs called out over HTTPS. The full topology, drawn out, is already in
[`deployment/README.md`](README.md#path-2-aws-production-shaped) and as a diagram source in
[`aws/clearframe_aws_deployment.excalidraw`](aws/clearframe_aws_deployment.excalidraw) (open it at
[excalidraw.com](https://excalidraw.com), File > Open). This document doesn't redraw either; it
fills in the exact commands and values behind each box.

## 2. Prerequisites

- An AWS account with billing enabled.
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
  installed and configured (`aws configure`) with credentials that can create ECR repos, IAM
  roles, App Runner services, RDS instances, and Secrets Manager secrets.
- [Docker](https://docs.docker.com/get-docker/) installed locally, to build the backend image
  before pushing it.
- An ECR repository to push that image to (created in step 3.1 below if it doesn't exist yet).
- Your AWS account ID and target region handy; every ARN and identifier below needs both.

## 3. Step-by-step

### 3.1 Build and push the backend image

First, a sanity check on what's actually being shipped. [`backend/Dockerfile`](../backend/Dockerfile):

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

This builds and serves correctly: it installs `backend/requirements.txt`, copies the rest of
`backend/` in (including `api.py`, `config/`, `fixtures/`, everything the app needs at runtime),
exposes `8000`, and starts uvicorn bound to `0.0.0.0:8000` so it's reachable from outside the
container. That port matches what `aws/apprunner-service.json` expects (`"Port": "8000"` in
`ImageConfiguration`, and the health check hits `/api/health` on the same container), so the
Dockerfile and the App Runner service definition agree with each other; nothing to fix here.

Build context matters: the Dockerfile's `COPY` instructions are relative to wherever you run
`docker build` from, so build with `backend/` as the context, not the repo root.

```bash
# From the repo root:
export AWS_ACCOUNT_ID=<your-account-id>
export AWS_REGION=<your-region>            # e.g. us-east-1
export ECR_REPO=clearframe-api

# Create the ECR repository (one time)
aws ecr create-repository --repository-name "$ECR_REPO" --region "$AWS_REGION"

# Build the image (context is backend/, matching the Dockerfile's COPY paths)
docker build -t "$ECR_REPO:latest" -f backend/Dockerfile backend

# Authenticate Docker to ECR
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

# Tag and push
docker tag "$ECR_REPO:latest" "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:latest"
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:latest"
```

### 3.2 Create the IAM role App Runner needs to pull from ECR

App Runner needs a role it can assume to pull the private image from ECR. AWS provides a managed
policy for exactly this, `AWSAppRunnerServicePolicyForECRAccess`; attach it to a dedicated role
rather than inventing custom permissions.

```bash
cat > /tmp/apprunner-trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "build.apprunner.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

aws iam create-role \
  --role-name AppRunnerECRAccessRole \
  --assume-role-policy-document file:///tmp/apprunner-trust-policy.json

aws iam attach-role-policy \
  --role-name AppRunnerECRAccessRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess
```

This is the exact role name `aws/apprunner-service.json` already references
(`AccessRoleArn: arn:aws:iam::ACCOUNT_ID:role/AppRunnerECRAccessRole`), so keep the name as-is
unless you also update that file to match a different name.

### 3.3 Provision Postgres

Two equally valid options; pick one.

**Option A: RDS Postgres**, fully AWS-managed, more setup, more control.

```bash
aws rds create-db-instance \
  --db-instance-identifier clearframe-db \
  --db-instance-class db.t4g.micro \
  --engine postgres \
  --engine-version 16 \
  --master-username clearframe \
  --master-user-password '<choose-a-strong-password>' \
  --allocated-storage 20 \
  --publicly-accessible \
  --region "$AWS_REGION"
```

`--publicly-accessible` is only needed if App Runner reaches RDS over the public endpoint; for a
tighter setup, put both in the same VPC and use an App Runner VPC connector instead, at the cost
of more networking setup than this quick path covers. After it's created (`aws rds
describe-db-instances` to poll status), the connection string shape is:

```
postgresql://clearframe:<password>@<rds-endpoint>:5432/postgres
```

**Option B: Supabase Postgres**, zero AWS provisioning, and what this project's own README and
design doc actually demonstrated running live. Create a Supabase project, then grab the connection
string from Project Settings > Database > Connection string (prefer the pooled
"Transaction"/"Session" pooler URI). Either option produces the same `DATABASE_URL` shape the
backend expects (`backend/src/db.py` just needs a Postgres URL; it doesn't care who's hosting it).
If you're optimizing for less to manage, Supabase is the simpler choice here, RDS is the choice if
you want everything inside your own AWS account and VPC.

### 3.4 Put secrets in Secrets Manager

```bash
aws secretsmanager create-secret \
  --name clearframe/tl-api-key \
  --secret-string '<your-twelvelabs-api-key>' \
  --region "$AWS_REGION"

aws secretsmanager create-secret \
  --name clearframe/database-url \
  --secret-string '<your-postgresql-connection-string>' \
  --region "$AWS_REGION"

# Only if using Supabase Storage for uploads
aws secretsmanager create-secret \
  --name clearframe/supabase-key \
  --secret-string '<your-supabase-service-role-key>' \
  --region "$AWS_REGION"
```

Each `create-secret` call returns an ARN, e.g.:

```
arn:aws:secretsmanager:us-east-1:123456789012:secret:clearframe/tl-api-key-AbCdEf
```

Note the actual ARN AWS returns; Secrets Manager appends a random suffix, so it won't exactly
match the placeholder ARNs already sitting in `aws/apprunner-service.json`. You'll paste the real
ones in the next step.

### 3.5 Fill in `aws/apprunner-service.json`

Read the file as it exists in the repo; every one of these needs a real value before
`aws apprunner create-service` will work:

| Field | Current placeholder | Replace with |
|---|---|---|
| `SourceConfiguration.AuthenticationConfiguration.AccessRoleArn` | `arn:aws:iam::ACCOUNT_ID:role/AppRunnerECRAccessRole` | Your account ID (role name matches step 3.2 as-is) |
| `SourceConfiguration.ImageRepository.ImageIdentifier` | `ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/clearframe-api:latest` | Your account ID and region (matches the image pushed in step 3.1) |
| `RuntimeEnvironmentSecrets.TL_API_KEY` | `arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:clearframe/tl-api-key` | The real ARN from step 3.4 |
| `RuntimeEnvironmentSecrets.DATABASE_URL` | `arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:clearframe/database-url` | The real ARN from step 3.4 |
| `RuntimeEnvironmentSecrets.SUPABASE_SERVICE_KEY` | `arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:clearframe/supabase-key` | The real ARN from step 3.4, or remove this key entirely if you're not using Supabase Storage |

`RuntimeEnvironmentVariables.TL_BASE_URL` is already a real value
(`https://api.twelvelabs.io/v1.3`) and needs no edit. `InstanceConfiguration` (`1 vCPU`, `2 GB`)
and `HealthCheckConfiguration` (HTTP, `/api/health`, checked every 10 seconds) are also already
filled in and match a real, callable endpoint in `backend/api.py`.

If you're not using Supabase Storage, either delete the `SUPABASE_SERVICE_KEY` line from
`RuntimeEnvironmentSecrets` or leave it pointed at an empty secret; leaving it pointed at a
nonexistent ARN will make `create-service` fail outright.

Once every placeholder is a real value, create the service:

```bash
aws apprunner create-service --cli-input-json file://deployment/aws/apprunner-service.json --region "$AWS_REGION"
```

App Runner builds nothing itself here since `SourceConfiguration` points at a prebuilt ECR image;
it pulls the image you already pushed, starts the container, and begins polling
`/api/health` per the health check configuration. `AutoDeploymentsEnabled: true` means any future
push of a new `:latest` tag to that same ECR repo triggers a redeploy automatically, no manual
`create-service` needed again.

### 3.6 Frontend

Two equally valid options; the README and this project's own live demo used the second one.

**Option A: S3 + CloudFront**, keeps the frontend inside the same AWS account as everything else.

```bash
cd frontend
npm install
npm run build   # outputs to frontend/dist

aws s3 mb s3://clearframe-frontend-<unique-suffix> --region "$AWS_REGION"
aws s3 sync dist/ s3://clearframe-frontend-<unique-suffix>/ --delete
```

Then create a CloudFront distribution pointing at that bucket (as an S3 origin, with origin access
control so the bucket itself stays private), set the default root object to `index.html`, and add
a custom error response that rewrites 403/404 back to `index.html` so client-side routing works
the same way `vercel.json`'s `rewrites` rule already does on the Vercel path. Set `VITE_API_BASE`
to the App Runner service URL (from `aws apprunner describe-service`) as a build-time environment
variable before `npm run build`, same requirement as on the Vercel path: Vite inlines it at build
time.

**Option B: Vercel**, same as the [Quick Deploy](QUICK_DEPLOY.md) path, just pointed at the App
Runner URL instead of a Render URL. There's nothing AWS-specific about the frontend; it's a static
build that only needs `VITE_API_BASE` set correctly. If you're already running the AWS backend and
don't need the frontend inside AWS specifically (for VPC/compliance reasons, say), Vercel is less
to set up and maintain than S3 + CloudFront for the same result.

## 4. CI/CD

What exists today, in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml): on every push or
PR to `main`, two jobs run. `backend` installs `backend/requirements.txt`, runs every
`tests/test_*.py` file, then runs `eval/run_eval.py` against the labeled evaluation set and
uploads the report as a build artifact. `frontend` installs frontend dependencies with `npm ci`
and runs `npm run build`. Neither job builds a Docker image, pushes to ECR, or deploys anywhere;
CI today is a test-and-eval gate only.

What deployment/README.md's diagram sketches as the production extension, not yet built, would
bolt onto that same workflow: after both existing jobs pass (tests green, eval at 16/16), add a
step that builds the backend image with `docker build -f backend/Dockerfile backend`, authenticates
to ECR the same way as step 3.1 above, tags it `:latest` (or with the commit SHA, keeping `:latest`
as a moving pointer to the most recent good build), and pushes it. Because
`AutoDeploymentsEnabled: true` is already set in `aws/apprunner-service.json`, App Runner picks up
that new `:latest` push on its own, no separate deploy step needed in the workflow itself. The
practical effect: merging to `main` after tests and eval pass would ship straight to production.
That's a real gap today, not a nuance: there is currently no branch protection or required-check
enforcement described here either, so wiring this up should include making the CI job a required
check before it's trusted as a deploy gate.

## 5. The bucket-sync lock caveat

Confirmed against the current code in `backend/api.py`: bucket sync uses a plain in-process
`threading.Lock()`.

```python
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", "30"))
_SYNC_LOCK = threading.Lock()  # one bucket sweep at a time (daemon + manual /api/sync)
```

`_sync_once()` calls `_SYNC_LOCK.acquire(blocking=False)` before scanning linked buckets, and
returns immediately (without ingesting anything) if the lock is already held. That's correct and
sufficient with exactly one backend process: it stops the background daemon and a manual
`/api/sync` call from double-ingesting the same file inside that one process. It stops working the
moment there are two or more App Runner instances, because each instance has its own Python
process and its own independent lock; two instances can both acquire their own uncontended lock at
the same moment and both sweep the same bucket, ingesting the same uploaded video twice, each
paying for its own TwelveLabs analysis of the same file.

This only bites once App Runner is configured to run more than one instance (autoscaling beyond a
single instance, or a fixed instance count greater than one). At one instance, today's code is
correct as-is.

**How you'd actually fix it**: move the lock from process memory into Postgres, since every
instance already talks to the same database. Postgres advisory locks
(`pg_advisory_lock`/`pg_try_advisory_lock`) are built for exactly this: any number of processes can
ask Postgres itself to arbitrate a named lock, and Postgres, being one shared thing all instances
already depend on, becomes the single source of truth about who's currently sweeping. The
non-blocking variant, `pg_try_advisory_lock`, is the direct analog of today's
`acquire(blocking=False)`: an instance calls it at the top of a sync sweep, and if another instance
already holds that same advisory lock key, the call returns false immediately and this instance
skips the sweep this tick, exactly the same skip-and-return-early behavior `_sync_once()` already
has, just arbitrated across processes instead of within one. The lock should be released
(`pg_advisory_unlock`) in the same `finally` block pattern already used for the in-process lock, so
a crash mid-sweep doesn't leave the advisory lock held forever; alternatively, a session-scoped
advisory lock tied to the same database connection used for the sweep releases automatically if
that connection drops, which is safer against a hard crash than relying on application code to
always reach the `finally`. This is a contained change: `_SYNC_LOCK` in `backend/api.py` is the
only place in the codebase that takes the current lock.

## 6. Cost shape

Rough order of magnitude only, not a quote. Check current AWS pricing before budgeting off this.

- **App Runner**, one instance at `1 vCPU` / `2 GB` (what `apprunner-service.json` requests),
  running continuously: roughly tens of dollars a month at the smallest App Runner tier, before
  any request-based charges. Scales with instance size and how many instances are running.
- **RDS Postgres**, smallest instance class (`db.t4g.micro` or similar), plus 20 GB storage:
  also roughly tens of dollars a month. Supabase's free or lowest paid tier is materially cheaper
  if you don't need it inside your own VPC.
- **S3 + CloudFront**, for the frontend option: typically single-digit dollars a month at low
  traffic, storage and data transfer for a small static site are cheap.
- **Secrets Manager**: a small flat per-secret monthly charge, negligible at three secrets.
- **TwelveLabs API usage**: billed separately by TwelveLabs, scales with videos indexed and
  analyzed, not an AWS cost at all.

Total shape for a small, always-on deployment: low hundreds of dollars a month, dominated by App
Runner and RDS running continuously rather than by storage or secrets. Confirm against the AWS
Pricing Calculator and current TwelveLabs pricing before committing to this path for anything
beyond evaluation.

## 7. Monitoring and observability gap

Named honestly: none of this is built yet. There are no CloudWatch alarms configured anywhere in
this repo, and the backend's only logging today is whatever gets printed to stdout (see the
`print(...)` calls in `backend/api.py`, e.g. around startup and sync failures), which App Runner
captures into CloudWatch Logs by default but nothing currently alerts on.

The first thing worth adding, before this runs unattended: a CloudWatch alarm on the App Runner
health check failing (App Runner already tracks this per `HealthCheckConfiguration` in
`apprunner-service.json`; wiring an alarm to it is a small addition, not new instrumentation), and
a second alarm on RDS CPU or connection count so a runaway query or connection leak surfaces before
the database falls over. Structured logging (request IDs, JSON log lines instead of bare `print`)
would come next, useful for debugging once there's more than one instance and stdout from two
containers interleaves in the same log group.
