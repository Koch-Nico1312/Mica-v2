# Archived runtime and demonstrations

This directory is excluded from normal pytest discovery, lint checks and Python
service images. The supported desktop entry point is `desktop/local_main.py`;
the backend starts through `backend.services.api.app:create_app --factory`.

`gemini_live/` preserves the previous Gemini Live entry point, bundled plugins,
phone dashboard (including its old HTTP/AES implementation), and core modules
that have no active runtime consumers: error checking, response formatting,
self-source editing, automatic dependency installation, old STT/TTS engines,
offline commands, speaker recognition, whisper mode and autonomous server repair.
These files are historical source, not supported launchers or deployed services.
Do not run them against production credentials/data. Paths and dependencies have
not been certified for standalone operation from the archive.

Historical tests are preserved in `tests/`. Mixed test files keep their active
feature tests in the normal suite; only assertions for archived modules were
removed from normal collection. `benchmarks/feature_timings.py` has no assertions
and remains a manual historical demonstration.

Active native actions and their dependencies remain under `desktop/`, including
automation, organization, learning, smart home, intercom, 3D integration,
autonomous task planning, server monitoring and the project/code-agent helpers.
The generic plugin-loader implementation remains an explicit integration helper;
the native advanced-agent action does not discover the archived bundled plugins
when inspecting a project or initializing its integration.
