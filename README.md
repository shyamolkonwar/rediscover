# Rediscover

**Search real space data. Test a hypothesis. Keep the evidence—even when it fails.**

An open-source physics workbench with a CLI, MCP tools and optional Azure-backed research agents.

- **TESS research campaigns:** search telescope light curves, freeze candidate hypotheses, test independent observations, examine alternative explanations and check catalogs.
- **LIGO reproduction:** recover known gravitational-wave signals from public detector data with numerical evidence and offline reports.

**Scientific status:** the TESS workflow is experimental. It is not a validated planet classifier and has not established a new planet. Its first real campaign and its known-control failure are published rather than hidden.

[Actual TESS results](examples/tess/RESULTS.md) · [TESS guide](docs/TESS_USAGE.md) · [Transit method](docs/TRANSIT_METHOD.md) · [LIGO results](examples/verified/RESULTS.md) · [Security](SECURITY.md)

## What the TESS upgrade actually did

On an Azure CPU VM, a research model proposed a bounded search before the data were inspected. The system then:

1. Froze a metadata-selected cohort of **12 stars**, with Sector 1 for discovery and Sector 4 reserved for validation.
2. Searched both predeclared detrending variants.
3. Froze **six follow-up ephemerides** that met the SNR/repetition rule.
4. Had the model propose, write and execute **two exploratory tests** inside restricted Docker containers, using discovery data only.
5. Evaluated the frozen ephemerides against independent Sector 4 observations, without re-searching or retuning them.
6. Recorded the rejection reasons and catalog responses in offline dossiers.

**No candidate survived the full screening rules. No new planet was established.**

A separate known pi Mensae c control recovered approximately **6.267 days**, with a strong dip at the predicted times in both sectors. However, the conservative odd/even and variability/secondary screens also flagged that known planet. This is a real false-rejection/sensitivity limitation of the screening rules—not a passing control. We did not relax the thresholds or reuse its validation data to force a pass.

The system therefore demonstrates a real search–experiment–validation workflow, **not validated completeness, reliability, autonomous discovery, or scientific novelty**. Read [the results](examples/tess/RESULTS.md) before interpreting a candidate.

## Install this development upgrade

Python 3.12 on Linux is the verified platform. The scientific dependencies are substantial. The existing v0.1.0 release is LIGO-only; this TESS upgrade is on its review branch:

```sh
uv tool install --python 3.12 \
  'git+https://github.com/shyamolkonwar/rediscover.git@feat/tess-discovery-campaigns'
rediscover doctor
```

The distribution is `rediscover-physics`. The unrelated PyPI package `rediscover` is **not** this project. This project is distributed through GitHub, not PyPI.

## Run a TESS campaign without an AI account

```sh
# Plan and freeze a metadata-selected cohort before searching flux:
rediscover tess plan --count 12 --discovery-sector 1 --validation-sector 4

# Use the returned campaign ID:
rediscover tess search CAMPAIGN_ID
rediscover tess freeze CAMPAIGN_ID
rediscover tess validate CAMPAIGN_ID
rediscover tess review CAMPAIGN_ID
rediscover tess report CAMPAIGN_ID
```

Or perform the staged numerical workflow with one command:

```sh
rediscover tess discover --count 12
```

The HTML report is self-contained. The full campaign directory retains original arrays, source checksums, settings, hypotheses, measurements, catalog snapshots, model proposals and execution records.

A zero-candidate outcome is valid. Download failures, insufficient observations and incomplete novelty checks are not silently converted into successes.

## Let an agent design and run exploratory tests

Set `REDISCOVER_API_BASE` and `REDISCOVER_API_KEY` using your environment manager. The Azure base ends in `/openai/v1`; never commit or paste credentials into an issue.

Build the optional research container on the Linux execution machine:

```sh
git clone --branch feat/tess-discovery-campaigns https://github.com/shyamolkonwar/rediscover.git
cd rediscover
docker build -t rediscover-research:0.2.0 -f docker/research.Dockerfile .

rediscover tess discover --count 12 --model YOUR_DEPLOYMENT --allow-code
```

The model proposes bounded search settings before flux inspection. After search—but **before hypothesis freeze**—it can write exploratory tests against a restricted discovery-data file. A separate deterministic verifier assigns the final status.

Generated Python runs non-root, without network or host credentials, with read-only inputs, CPU/memory/process limits, a hard execution timeout, bounded JSON output and verified container cleanup. This is Docker isolation on a trusted host, **not a perfect security boundary against malicious code or kernel exploits**. See [sandbox details](docs/RESEARCH_SANDBOX.md).

Research slots are durably reserved before paid experiment proposals. Exhausted quotas cannot trigger extra proposal/critique calls. Model interpretations remain exploratory and are not automatically accepted as scientific evidence.

## Use MCP

After installation, add the stdio server to your MCP host:

```json
{
  "mcpServers": {
    "rediscover": {
      "command": "rediscover-mcp",
      "args": [],
      "env": {"OPENBLAS_NUM_THREADS": "2", "OMP_NUM_THREADS": "2"}
    }
  }
}
```

Ask your agent:

> Plan a bounded TESS search, keep the validation sector hidden until hypotheses are frozen, test the candidates, and show both the evidence and reasons not to call them planets.

The TESS tools are `tess_plan`, `tess_search`, `tess_freeze_hypotheses`, `tess_validate`, `tess_review`, `tess_status` and `tess_report`. The optional `tess_experiment` tool is registered only when the operator sets `REDISCOVER_ENABLE_CODE_EXPERIMENTS=1`; its Docker image must already exist. Your MCP host supplies the model, so MCP use itself needs no Azure key.

## Existing LIGO workflow

```sh
rediscover run GW150914-v3 --catalog
rediscover bench                  # deterministic demonstration suite
rediscover bench --model YOUR_DEPLOYMENT  # explicit paid model test
```

The LIGO commands and MCP tools remain available. The [v0.1 evidence](examples/verified/RESULTS.md) and [method](docs/PHYSICS.md) are historical, version-specific artifacts. Peak SNR is not a false-alarm probability; mass estimates are coarse detector-frame template-bank points, not Bayesian posterior intervals.

## Scientific boundaries

- Only the best periodic peak is investigated per star; the search is not complete for all planets or aliases.
- Diagnostic depth errors assume simplified noise. Correlated noise can produce both false positives and false rejections.
- A reserved sector tests the frozen ephemeris once. A failed or interrupted holdout is not secretly re-searched.
- Default surrogate counts are preliminary and cannot clear the full campaign multiplicity cutoff. This is explicitly shown in reports. More repetitions must be configured **before** searching, not after seeing favorable results.
- Catalog matching covers specific NASA tables and period aliases. Scholarly metadata searches do not provide exhaustive literature/ExoFOP clearance.
- Aperture centroids and crowding are not full pixel-level blend validation.
- `POTENTIALLY_UNCATALOGUED_CANDIDATE` is a review queue, never a confirmed planet or guaranteed discovery.
- A trusted operator can inspect public data or create another campaign. The application enforces within-campaign separation, not global blindness against that operator.

## Develop

```sh
uv sync --frozen --extra dev
docker build -t rediscover-research:0.2.0 -f docker/research.Dockerfile .
uv run pytest -q
uv run ruff check src tests
uv build
```

Tests include synthetic transits, independent holdouts, binary/variability and noise controls, research quotas, immutable evidence, actual Docker isolation and a real MCP client/server exchange. Real-data fixtures are opt-in as described in the methods documentation.

Built on NASA TESS/MAST, the NASA Exoplanet Archive, Astropy, Astroquery, GWOSC, PyCBC, LALSuite, GWPy and MCP. Code: [MIT](LICENSE). Underlying data and dependencies retain their own attribution/license terms. No endorsement by these institutions or model providers is implied.
