# Cloudflare One Invite-Only Demo

This is a temporary Mac-hosted demo path. Cloudflare Access is the public
authentication layer; FastAPI, Ollama, Java, and TLA+ tools stay on the Mac.

## Local Runtime

Install dependencies and make sure these processes/tools are available:

- Ollama is running and has `qwen3:4b` pulled.
- Java is installed.
- `TLAPLUS_JAR` points to `tla2tools.jar`, or `TLA_HOME` points to a directory
  containing `tla2tools.jar`.
- Your Mac stays awake and online during the demo.

## Next-Time Runbook

From the repo root, start or refresh the Python environment if needed:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

In one terminal, make sure the local model server is available:

```sh
ollama pull qwen3:4b
ollama serve
```

In a second terminal, start FastAPI on localhost:

```sh
cd /Users/zhengwangyuan/repos/TLA-Finance
source .venv/bin/activate
export PUBLIC_DEMO_HOSTNAME=demo.zhengwangyuan-patrick.com
export CLOUDFLARE_HOSTNAME=live-demo.zhengwangyuan-patrick.com
export TLAPLUS_JAR=/path/to/tla2tools.jar
bash scripts/run_cloudflare_demo.sh
```

In a third terminal, connect Cloudflare to the local FastAPI server:

```sh
cloudflared tunnel run --url http://localhost:8000 tla-finance-demo
```

Then open:

```text
Local:      http://127.0.0.1:8000
Cloudflare: https://demo.zhengwangyuan-patrick.com
```

The public demo hostname should route to the Worker in the personal-site repo.
The Worker proxies to the live tunnel hostname when the local app is running and
returns a clear offline message when it is not.

If the public page shows `Invalid host header`, FastAPI received a `Host`
header that is not in the app allowlist. Add the public site hostname and the
live tunnel hostname before starting the app:

```sh
export PUBLIC_DEMO_HOSTNAME=demo.zhengwangyuan-patrick.com
export CLOUDFLARE_HOSTNAME=live-demo.zhengwangyuan-patrick.com
```

Start FastAPI bound only to loopback:

```sh
export PUBLIC_DEMO_HOSTNAME=demo.zhengwangyuan-patrick.com
export CLOUDFLARE_HOSTNAME=live-demo.zhengwangyuan-patrick.com
export TLAPLUS_JAR=/path/to/tla2tools.jar
bash scripts/run_cloudflare_demo.sh
```

The script defaults to:

```sh
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=qwen3:4b
OPENAI_REASONING_EFFORT=none
SAFETY_RUN_TLC=1
OBSERVE_PAYLOADS=0
SAFETY_ARTIFACT_RETENTION_HOURS=24
SAFETY_TLA_TIMEOUT_SECONDS=60
```

If you do not use `CLOUDFLARE_HOSTNAME`, set these explicitly:

```sh
export ALLOWED_ORIGINS=https://demo.zhengwangyuan-patrick.com,https://live-demo.zhengwangyuan-patrick.com
export ALLOWED_HOSTS=demo.zhengwangyuan-patrick.com,live-demo.zhengwangyuan-patrick.com,127.0.0.1,localhost
```

## Cloudflare Tunnel

Use a named tunnel, not a random quick tunnel.

The current named tunnel is `tla-finance-demo`. It should be routed to the
live-only hostname, not the public fallback hostname:

```yaml
ingress:
  - hostname: live-demo.zhengwangyuan-patrick.com
    service: http://localhost:8000
  - service: http_status:404
```

Run it locally:

```sh
cloudflared tunnel run --url http://localhost:8000 tla-finance-demo
```

In Cloudflare Zero Trust, remove any tunnel public hostname entry for
`demo.zhengwangyuan-patrick.com`. The `demo` hostname belongs to the Worker in
the personal-site repo. The tunnel hostname is:

```text
live-demo.zhengwangyuan-patrick.com
```

You can also install `cloudflared` as a macOS service if the demo needs to stay
up across terminal sessions.

## Cloudflare Access

Create a self-hosted Access application for the live tunnel hostname:

- Application domain: `live-demo.zhengwangyuan-patrick.com`
- Policy action: Allow
- Include: only the invited tester email addresses
- Session duration: 24 hours
- Identity provider: One-time PIN/email or your chosen IdP

Enable Access protection for the tunnel route. An unauthenticated browser should
land on Cloudflare Access before the FastAPI app is reachable.

## App-Side Controls

The app also enforces local guardrails because invited users can still overload
the Mac:

- `/api/semantic-check`: 10 requests/minute/client
- `/api/chat`: 5 requests/minute/client
- `/api/demo/bad-suggestion`: 20 requests/minute/client
- CORS is restricted by `ALLOWED_ORIGINS`.
- Host headers are restricted by `ALLOWED_HOSTS`.
- Artifacts stay server-side under `artifacts/safety-runs/` and old run
  directories are cleaned up on API startup.

## Acceptance Checks

- Unauthenticated request to the live tunnel hostname redirects to Cloudflare Access.
- Invited email can authenticate and load the UI.
- Non-invited email is denied.
- Authenticated `/api/health` returns `{"status":"ok"}` through the tunnel.
- Authenticated `/api/semantic-check` works with TLC enabled.
- Rate limits return `429` through the tunnel.
- Stopping FastAPI makes the hostname fail cleanly; restarting FastAPI recovers
  without Cloudflare changes.
- Stopping Ollama produces a structured extraction failure instead of a crash.
- Unsetting `TLAPLUS_JAR`/`TLA_HOME` reports TLA tools as `not_configured`.

## Health Checks

With FastAPI and `cloudflared` running:

```sh
curl -i http://127.0.0.1:8000/api/health
curl -I https://live-demo.zhengwangyuan-patrick.com
curl -I https://demo.zhengwangyuan-patrick.com
```

If local health is `200` but the live tunnel hostname returns a Cloudflare
`530`, the `cloudflared tunnel run ...` process is not connected. If the public
demo hostname returns `503`, the public Worker cannot reach the live tunnel
hostname. If `scripts/run_cloudflare_demo.sh` fails to bind port `8000`, a
stale FastAPI process is still running; see [fixes.md](fixes.md).

For the TLC-backed public demo, export `TLA_HOME` (or `TLAPLUS_JAR`) and
`SAFETY_RUN_TLC=1` before running the script; set `SAFETY_RUN_TLC=0` for a
faster extractor-and-policy-only demo.
