# Monthly dependency and security review

Dependabot may open review proposals once per month. It never changes the
running Windows installation and must not be configured to auto-merge.

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
