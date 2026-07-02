# Fixes

## 2026-07-02: Local Demo Host And Port Startup Issues

### Symptoms

- Browser showed `Invalid host header` when the local demo was viewed through the website or Cloudflare tunnel.
- `bash scripts/run_cloudflare_demo.sh` failed with:

```text
[Errno 48] error while attempting to bind on address ('127.0.0.1', 8000): address already in use
```

### Causes

- FastAPI `TrustedHostMiddleware` rejected a public/proxy `Host` header that was not in `ALLOWED_HOSTS`.
- Port `8000` was already held by an old local Python/Uvicorn process.

### Fix

Start the demo with the public and tunnel hostnames configured:

```sh
export PUBLIC_DEMO_HOSTNAME=demo.zhengwangyuan-patrick.com
export CLOUDFLARE_HOSTNAME=live-demo.zhengwangyuan-patrick.com
bash scripts/run_cloudflare_demo.sh
```

If port `8000` is busy, find and stop the old listener:

```sh
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <PID>
```

Use `kill -9 <PID>` only if the process does not exit after a normal `kill`.

### Code Follow-Up

- `PUBLIC_DEMO_HOSTNAME` is now supported by shared config.
- Both public website and live tunnel hostnames are included in trusted hosts and CORS origins when configured.
- Regression coverage was added for the two-hostname demo setup.
