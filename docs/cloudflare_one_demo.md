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

Start FastAPI bound only to loopback:

```sh
export CLOUDFLARE_HOSTNAME=automata-demo.example.com
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
export ALLOWED_ORIGINS=https://automata-demo.example.com
export ALLOWED_HOSTS=automata-demo.example.com,127.0.0.1,localhost
```

## Cloudflare Tunnel

Use a named tunnel, not a random quick tunnel.

Create or configure a tunnel that maps:

```yaml
ingress:
  - hostname: automata-demo.example.com
    service: http://localhost:8000
  - service: http_status:404
```

Run it locally:

```sh
cloudflared tunnel run <tunnel-name>
```

You can also install `cloudflared` as a macOS service if the demo needs to stay
up across terminal sessions.

## Cloudflare Access

Create a self-hosted Access application for the same public hostname:

- Application domain: `automata-demo.example.com`
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

- Unauthenticated request to the public hostname redirects to Cloudflare Access.
- Invited email can authenticate and load the UI.
- Non-invited email is denied.
- Authenticated `/api/health` returns `{"status":"ok"}` through the tunnel.
- Authenticated `/api/semantic-check` works with TLC enabled.
- Rate limits return `429` through the tunnel.
- Stopping FastAPI makes the hostname fail cleanly; restarting FastAPI recovers
  without Cloudflare changes.
- Stopping Ollama produces a structured extraction failure instead of a crash.
- Unsetting `TLAPLUS_JAR`/`TLA_HOME` reports TLA tools as `not_configured`.
