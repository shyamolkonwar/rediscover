# Contributing

Useful contributions are numerical correctness, independently checked results, accessibility of reports, reliable installation and clearer limitations. No generated discoveries or unsupported performance claims.

## Development

Python 3.12 or 3.13, Linux recommended (the release verification platform). macOS and Windows are not yet validated; WSL2 is the suggested Windows path.

```sh
git clone https://github.com/shyamolkonwar/rediscover.git
cd rediscover
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests
```

Tests are offline except explicit integration scripts in `scripts/`. Synthetic fixtures are clearly separated from real GWOSC examples. Never replace a failed external request with fixture data in the application.

Open an issue describing the incorrect behavior and a minimal reproduction. Numerical changes need an analytic or injection test and a real-data comparison, with bounds fixed before interpreting results. Explain why expected values or tolerances changed.

Submit a focused pull request. Do not commit strain caches, credentials, local runs or private model endpoints. Official data is downloaded by the user; respect its license and attribution.
