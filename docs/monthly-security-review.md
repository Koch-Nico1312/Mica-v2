# Monthly dependency and security review

Review dependency updates locally once per month. Applying updates to the
running Windows installation remains a separate decision.

For each proposal:

1. Confirm the upstream release and security advisory from the primary source.
2. Regenerate `requirements-phase0.lock` from `requirements-phase0.in` for
   Windows and inspect the complete dependency diff.
3. Run the complete automated suite plus the Phase-0 action matrix in staging.
4. Re-run Windows preflight, mTLS/firewall checks, emergency stop, backup
   restore and the physical voice smoke tests for audio-related changes.
5. Record the reviewed versions, evidence links, reviewer and decision in the
   changelog. Reject or defer any proposal whose provenance or compatibility
   cannot be established.

Production installation remains a separate, explicit owner-approved action.

## Automated checks

Run the complete Windows test suite, Ruff's execution-defect rules and a strict
pip-audit of the installed desktop/backend dependency graph locally. Test XML,
coverage XML and audit JSON are retained as local evidence. Missing audit metadata or known
vulnerabilities fail the audit; there is no blanket ignore list.

For the same local checks, install `requirements.txt`, `backend/requirements.txt`
and `requirements-dev.txt` in a fresh development environment, then run
`python -m ruff check .`, `python -m pytest
--cov=desktop --cov=backend --cov=mica_shared --cov-report=term
--cov-report=xml` and `python -m pip_audit --strict`. `pytest.ini` defines
collection, strict markers and a 120-second timeout per test. The historical
timing script under `legacy/benchmarks/` is not a test gate.

These checks establish code/dependency evidence. Hardware, mTLS, firewall,
container and real provider acceptance still require their staging checks.
