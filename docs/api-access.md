# API and LAN access

The API requires `X-Mica-API-Token` on every HTTP path and WebSocket handshake.
The token must contain at least 32 bytes; generate at least 32 random URL-safe
characters. Missing/short server configuration fails closed with 503; missing,
wrong or duplicate token headers return 401. Unauthorized WebSockets close with
code 1008 before acceptance. Approval cookies, emergency Bearer tokens and query
parameters do not grant API access.

Request bodies are bounded at the transport: 16 MB by default
(`MICA_MAX_REQUEST_BYTES`), and 64 MB for the approval-gated backup restore
upload. Structured payloads such as `params` additionally stay under 256 KB.

The only public API health response is `GET /health` and contains no private
data. Three exact provider ingress operations retain their own mandatory
authentication: Telegram POST webhook and WhatsApp GET challenge/POST webhook.
Their configured secret/signature and connector-enabled checks still apply.
Other connector paths require the API token as well as their own checks.

## Windows setup

Store the token under the Windows Credential Manager entry `MICA_API_TOKEN`,
and include `"MICA_API_TOKEN": "MICA_API_TOKEN"` in
`desktop/config/credential-names.json` using the tracked example. The Compose
launcher reads that entry and passes it only to its child environment. The
desktop HTTPS client reads the same entry (or an explicitly supplied environment
value), and uses it for text, memory, backup and voice. Do not put the token in
tracked files or provider profile fields.

On Linux, supply `MICA_API_TOKEN` through the deployment's secret environment;
the desktop Credential Manager entry must hold the same token. Rotating the
token requires recreating the API/Caddy containers and restarting the desktop
client. Existing approval sessions remain a separate, stricter boundary.

## Browser/PWA setup

Set `MICA_LAN_USER` (default `mica`) and `MICA_LAN_PASSWORD_HASH` in backend
deployment configuration. Generate the bcrypt hash with the interactive
`caddy hash-password` command. Put the hash in single quotes in `.env` to preserve
its dollar signs. Caddy accepts a hash, never a plaintext password.
[Caddy authentication documentation](https://caddyserver.com/docs/caddyfile/directives/basic_auth).

The HTTPS browser login protects both the PWA and API routes. After successful
login, Caddy supplies the API-token header to the backend; the secret is never
embedded in HTML, JavaScript or browser storage. Native desktop API/voice
requests use the token header and do not need the browser password. Provider
webhooks reach only their exact API ingress paths for signature verification.

The emergency PWA uses `X-Mica-Emergency-Authorization` for its short-lived
emergency Bearer token so browser Basic authentication remains available in
`Authorization`. Direct clients may still use the original `Authorization`
emergency header alongside `X-Mica-API-Token`.

API access does not approve actions, authorize memory changes or lift Not-Aus.
Those operations continue to require their existing intent, session and policy
checks. Loopback binding and HTTPS/CA verification remain required.

## Verification evidence and limits

Tests enumerate every sensitive HTTP route and verify anonymous rejection,
wrong/missing/duplicate credentials, fail-closed configuration, WebSocket
rejection, authenticated reads, continued approval requirements and provider
authentication. Existing tests now supply an explicit test token.

The local Caddy 2.11.4 configuration was validated and exercised over HTTPS with
a temporary trusted CA and fake upstream/token/password: anonymous and wrong
token requests returned 401; native-token requests succeeded; browser login
injected the token and reached the PWA; provider ingress reached its own guard.
No system CA was installed. The Docker daemon was unavailable, so the configured
`caddy:2.8-alpine` container and target-host deployment remain unverified.
