# Installation

## Requirements

- Ubuntu 24.04 LTS / 26.04 LTS, or Debian 13 (trixie)+
- Python 3.11+
- APT-based system (V1)
- `sudo` rights for the update step only

## From PyPI

```bash
pip install rice-cli
```

## From source

```bash
git clone https://github.com/ATLAS-DEV78423/ConfigGuard.git
cd ConfigGuard
pip install .
```

## Development install

```bash
pip install -e .[dev]
pytest -q        # Linux only
```

## Verify

```bash
rice version     # prints rice x.y.z
```

## Shell completion (optional)

```bash
rice completion bash >> ~/.bashrc   # or zsh / fish variants
```

See [getting-started.md](getting-started.md) next.
