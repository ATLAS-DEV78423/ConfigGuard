# Getting started

## 1. Initialize

```bash
$ rice init
Detected configurations:
  hyprland   /home/you/.config/hypr
  waybar     /home/you/.config/waybar
Protect all detected configs? [Y/n]:
Additional paths to protect (comma-separated, blank=none):
Saved /home/you/.config/rice/config.toml
```

Non-interactive: accept everything detected. (Global flags like
`--non-interactive` go immediately after `rice`, before the command.)

```bash
rice --non-interactive init
```

## 2. Check status

```bash
$ rice status
System: ubuntu 24.04
Desktop: hyprland (Wayland)
Protected apps: 2 (2 roots)
Last snapshot: none
```

## 3. Take a manual snapshot

```bash
$ rice snapshot
Snapshot 2026-08-21T12-04-33Z: 5 files
```

Pin one you really care about:

```bash
rice snapshot --pin
```

## 4. Run a protected update

```bash
$ rice update
```

Rice snapshots your configs, runs `sudo apt update && sudo apt upgrade -y`,
compares configs afterwards, restores anything the update clobbered, and
prompts you when it cannot safely auto-decide:

```
[!] Conflict in ~/.config/hypr/hyprland.conf (changed)
    --- snapshot
    +++ current
[1] keep mine  [2] use new  [3] diff  [4] abort
```

## 5. If something looks wrong later

```bash
rice diff          # compare latest snapshot vs current configs
rice restore       # restore the latest snapshot
rice doctor --fix  # detect + recover an interrupted transaction
```
