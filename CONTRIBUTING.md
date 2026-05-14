## Contributing

Thanks for helping improve AP3.

### Quick start (dev)

- **Python**: 3.11+
- **Install**:

```bash
uv sync
```

- **Run unit tests**:

```bash
uv run pytest tests/unit/ -v
```

- **Run full test suite**:

```bash
uv run pytest -v
```

Note: the A2A-related unit tests require the optional `a2a` extra. If you’re running in a minimal environment, install with:

```bash
uv pip install -e ".[a2a,test]"
```

### Code quality

- **Lint**:

```bash
uv run ruff check .
```

- **Format**:

```bash
uv run ruff format .
```

### Pull requests

- **Keep PRs small** and focused.
- **Add/adjust tests** for behavior changes.
- **Do not commit secrets** (keys, tokens) or local state.
- **Describe the “why”** in the PR body.

### Reporting security issues

Please see `SECURITY.md`.

