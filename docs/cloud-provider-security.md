# Optional cloud LLM providers: security contract

MICA remains local by default. `MICA_LLM_PROVIDER` is `ollama` when it is
missing or invalid. A cloud request is permitted only when the operator
explicitly selects `openai_api` or `gemini` and provides the matching key.
There is no automatic cloud fallback.

With `MICA_TTS_ENGINE=auto`, voice output follows an already explicit LLM
choice: Gemini uses Gemini TTS, `openai_api` uses OpenAI Speech, and local LLMs
use local Kokoro. This pairing never selects a cloud provider on its own.

## Credentials

- OpenAI reads `OPENAI_API_KEY`; Gemini reads `GEMINI_API_KEY` or
  `GOOGLE_API_KEY`.
- Never put a real key in tracked JSON, `.env` examples, logs, audit events,
  exceptions returned by an API, screenshots or support messages.
- On the supported Windows path, store provider keys in Windows Credential
  Manager, add only the selected key name to
  `config/credential-names.json`, and start through
  `python -m mica_core.windows_launcher`. The launcher exposes it only to the
  MICA process environment. For example, the optional mapping is
  `{"OPENAI_API_KEY": "MICA_OPENAI_API_KEY"}` or
  `{"GEMINI_API_KEY": "MICA_GEMINI_API_KEY"}`. A plain
  environment variable is acceptable for a short manual test, but must not be
  persisted in the repository.
- Provider URLs, headers, response bodies and exception messages must be
  sanitized before logging. The audit boundary additionally removes embedded
  Bearer tokens, common API-key parameters, OpenAI-style keys and
  Google-style keys.

## Privacy boundary

Selecting a cloud provider sends only the current user message and MICA's fixed
persona by default. Local Brain snippets, profile fields, promoted prompts,
skills and runbooks stay on the PC.

For a voice turn, the generated reply text is subsequently sent to the same
selected provider's speech endpoint. Gemini uses the configured Gemini API key
and the `Sulafat` preset; OpenAI uses `POST /v1/audio/speech` with
`gpt-4o-mini-tts`, `coral`, and WAV output. Both calls may incur provider costs
and require network access. `MICA_TTS_ENGINE=kokoro` remains the explicit
local-only override.

Sending that private local context additionally requires
`MICA_CLOUD_ALLOW_PRIVATE_CONTEXT=1`. The existing relevance rules still apply
after this second opt-in: relationship context is limited to `personal`, and
only the selected retrieval snippets are added. Audit records, credentials and
unneeded tool results are never sent. Users who require a fully local
interaction must keep `MICA_LLM_PROVIDER=ollama`.

## Failure behaviour

- A missing key fails before any network request.
- Connect and total timeouts are finite; timeout, HTTP and malformed-response
  failures return a short provider-safe error without request/response bodies.
- Cloud failures do not silently retry through another provider and never
  switch the configured provider.
- API and audit responses may report the provider name, status, duration and
  coarse error class, but never the key, authorization header, full upstream
  URL query or raw provider body.

## Release checks

Before enabling a cloud provider, run the provider unit tests and the audit
redaction test. Use fake keys and mocked HTTP only; real keys are not required
for CI. A live smoke test is optional, must be initiated explicitly, and must
use a disposable prompt without personal profile or Markdown content.
