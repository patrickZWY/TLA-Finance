# Remote vLLM Backend Over SSH

Use this when the extractor should run on a rented GPU host (the current
setup is a Vast.ai instance serving `qwen3-32b` through vLLM) instead of a
local Ollama model. The helper script is `scripts/run_vast_backend.sh`.

Keep the rented vLLM server private and connect to it through SSH. FastAPI
uses local port `8000`, so the model tunnel must use a different local port.
If an old tunnel is still using `-L 8000:...`, stop it with `Ctrl-C` and start
this in terminal 1:

```sh
export VAST_INSTANCE_ID=<INSTANCE_ID>
ssh -i ~/.ssh/vast_ai_ed25519 \
  -N \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L 127.0.0.1:18000:127.0.0.1:18000 \
  "$(vastai ssh-url "${VAST_INSTANCE_ID}")"
```

The bind address is explicitly `127.0.0.1`, so the model API is not exposed to
other devices on the local network. Leave that terminal open.

In terminal 2, from the repo root, load the server token without printing or
saving it, then launch TLA-Finance with the Vast-specific defaults:

```sh
export VAST_INSTANCE_ID=<INSTANCE_ID>
export VLLM_API_KEY="$(
  ssh -i ~/.ssh/vast_ai_ed25519 \
    "$(vastai ssh-url "${VAST_INSTANCE_ID}")" \
    'printf %s "$OPEN_BUTTON_TOKEN"'
)"
bash scripts/run_vast_backend.sh
```

The helper verifies `/v1/models` before starting the app, selects the served
model name `qwen3-32b`, disables Qwen3 thinking for reliable JSON extraction,
and bounds remote requests to 120 seconds with one retry. It never writes the
token to the repository. Open `http://127.0.0.1:8000` and submit one of the
workbench examples. Opening the bare model URL `/v1` is not a health check;
`/v1/models` is the discovery endpoint.

When finished, stop FastAPI and the SSH tunnel with `Ctrl-C`, then stop or
destroy the Vast instance so hourly billing does not continue. Treat the
marketplace host as suitable only for synthetic/non-sensitive demo inputs
unless you intentionally move to a stronger trust boundary.

The matching `.env` values, if you prefer them over the script defaults, are
listed under the remote vLLM block in [`.env.example`](../.env.example).
