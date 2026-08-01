# DevContextIQ Known Issues

## Critical
* Frontend/backend deployment drift can point the UI at the wrong service or API base.
* Repository import previously accepted non-GitHub URLs and unsafe branch-derived paths.
* Embedding startup still depends on local model availability or outbound Hugging Face access.

---

## High
* Live Supabase, auth, and clone workflows are not covered by `test_e2e_phase8.py`.
* Production-readiness claims in historical handover docs were stronger than the actual validation evidence.

---

## Medium
* Ranking algorithm still basic (Scheduled for future phase)

---

## Low
* Improve onboarding summary (Scheduled for future phase)

---

## Resolved
* Fixed JWT forwarding (Phase 1)
* Added webhook replay protection (Phase 1)
* Fixed vector dimension mismatch (Phase 1)
* Handled windows console Unicode logging (Phase 1)
