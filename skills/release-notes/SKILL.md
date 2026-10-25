---
name: release-notes
description: Draft release notes / a changelog entry from the git history between two tags or since the last tag.
---
# Release notes

1. Find the range: `shell` `git describe --tags --abbrev=0` for the last tag (or use the range the user gave).
2. List commits: `git log --pretty=format:'%h %s' <last-tag>..HEAD` (add `--no-merges`).
3. Group them: Added, Changed, Fixed, Removed, Security, Internal (tests/CI/chore).
   Rewrite each line for a user, not for a developer; merge duplicates; drop noise.
4. Call out breaking changes at the top with migration steps.
5. Write the draft to `CHANGELOG.md` (or `RELEASE_NOTES.md`) with `edit_file` / `write_file`
   only if the user asked; otherwise print it.
6. Never publish a GitHub release yourself unless the user explicitly asked: `github_write`
   is a `send` action and will ask for confirmation.
