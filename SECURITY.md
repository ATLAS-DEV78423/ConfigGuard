# SECURITY.md

Rice is safety-critical: it touches user configs, runs `sudo apt`, and
restores files. Threat model and mitigations (normative; enforced by tests in
`tests/security/`):

| Threat                  | Mitigation                                                        |
|-------------------------|-------------------------------------------------------------------|
| Malicious config file   | Never execute config contents as code                             |
| Path traversal          | Canonicalize (`realpath`) + validate against protected scope      |
| Symlink attack          | Record targets; refuse to follow symlinks escaping protected scope |
| Privilege escalation    | Only privileged op = the APT invocation via `CommandRunner.privileged` |
| Corrupted snapshot      | SHA-256 every backup file before any restore                       |
| Interrupted transaction | Persistent transaction journal; recovery on next run               |
| Malicious package       | Delegate all trust/signature checks to APT; never bypass           |
| Compromised update      | No `--force-conf*`, no dpkg policy overrides, no lock bypassing    |

## Hard rules

- Writes only inside `~/.config/rice/`, `~/.local/share/rice/`, and
  user-approved protected paths.
- Atomic writes everywhere (temp -> fsync -> rename).
- Logs never contain config file contents or secrets (hashes/metadata only).
- Sudo passwords are never stored, logged, or transmitted; sudo runs in the
  foreground and may prompt normally.
- Concurrent transactions blocked by `transaction.lock` (flock).
