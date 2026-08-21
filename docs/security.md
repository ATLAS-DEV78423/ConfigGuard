# Security model

Full threat table: [SECURITY.md](../SECURITY.md). The short version:

## Privileges

Rice runs as your user. Exactly one operation is privileged: the APT update,
invoked as

```
sudo env DEBIAN_FRONTEND=noninteractive apt update
sudo env DEBIAN_FRONTEND=noninteractive apt upgrade -y
```

No `--force-conf*`, no dist-upgrade, no lock bypassing, no credential
handling — sudo prompts in your terminal; rice never sees passwords.

## Filesystem

- Writes only inside `~/.config/rice/`, `~/.local/share/rice/`, and your
  protected paths.
- Every write is atomic: temp file -> fsync -> rename.
- Every path is canonicalized and scope-checked before use.
- Symlinks whose targets escape the protected scope are refused, not followed.
- Restores verify SHA-256 of every backup file BEFORE touching live configs.

## Config contents are data, never code

Rice parses nothing it cannot afford to mis-parse: configs are hashed,
copied, and diffed — never executed or evaluated.

## Privacy

Logs contain metadata only (paths, sizes, hash prefixes). No telemetry in V1;
if telemetry ever ships it will be opt-in and documented here.
