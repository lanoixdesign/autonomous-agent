---
name: code-review
description: Review a diff or a set of files for bugs, security problems and readability, and report findings by severity.
---
# Code review

1. Get the change: `shell` with `git diff` (or `git diff main...HEAD`), or read the files the user named.
2. Read surrounding code with `read_file` / `search_files` before judging a line out of context.
3. Look for, in this order:
   - correctness: wrong logic, unhandled errors, off-by-one, race conditions, broken edge cases;
   - security: injection (shell, SQL, path), secrets in code or logs, unsafe deserialization, missing auth checks;
   - tests: is the new behaviour tested? would the tests fail if the code were wrong?
   - readability: naming, dead code, duplication, comments that lie.
4. Do not modify files unless the user asked for fixes.
5. Report as a list grouped by severity (blocking / should fix / nit), each item with
   `path:line`, the problem, and a concrete suggestion. End with an overall verdict.
