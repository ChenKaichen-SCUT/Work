# Project workflow

- User instruction dated 2026-10-28: after every completed work round that changes project files, commit and push the results to the existing GitHub repository (`origin`, currently `main`). This is standing authorization; do not ask again for routine commits and pushes.
- Include the code, theory, reports, raw results, figures, and reproducibility material needed to continue the research. Preserve frozen experiment snapshots and their source/hash provenance.
- Before pushing, inspect the current remote branch and retain its history. Do not force-push or overwrite unrelated work. Report the verified commit and any actual push failure.
- Do not commit credentials, local environments, caches, or unrelated personal files. Apply the existing ignore rules.
- Read `MIGRATION_HANDOFF.zh.txt` and the latest report linked from `README.md` to recover project context. Historical reports may say "local/unpushed" because that was their status when frozen; the Git history records subsequent publication.
- This instruction does not create scheduled work or authorize new research tasks. When a turn produces no file changes, no empty commit is needed.
