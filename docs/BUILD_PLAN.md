# Rediscover implementation plan

## Approved product
An open-source, CPU-only physics workbench and MCP server for reproducing gravitational-wave analyses using public GWOSC strain. Initial release: GW150914 in H1 and L1, additional supported GWOSC events, deterministic analysis, human-readable figures/reports, and bounded agent benchmarks including hidden injections into real detector noise.

The package name is `rediscover-physics` (the existing PyPI `rediscover` project is unrelated); commands are `rediscover` and `rediscover-mcp`. Repository: shyamolkonwar/rediscover. Do not claim a new discovery, independent significance, publication-quality parameter inference, or guaranteed wall-clock installation times.

## Execution boundary
Source editing and Git operations are separate from compute. All dependency installation, execution, tests, builds and model calls for this release run on an isolated authorized Linux VM. Limit numerical threads to 2 and preserve unrelated processes. Never publish private endpoints or credentials.

## Architecture
Python package, numpy/scipy/PyCBC/gwpy/h5py/httpx, stdio MCP. Read-only official data downloads and a bounded pre-written numerical tool set: no arbitrary shell, eval or generated code execution. All artifact paths confined to a workbench root. Immutable run IDs, JSON tool evidence, input SHA-256, numerical results and deterministic Markdown/HTML reports. Model prose is not the authoritative report.

Modules:
- data.py: GWOSC v2 event lookup, strain-file selection, allowlisted bounded download, checksum cache, HDF5/DQ parsing.
- physics.py: data quality, PSD, whitening/bandpass, matched-filter bank, coarse detector-frame mass estimate, injection helpers.
- workspace.py: run IDs, JSON/array persistence, tamper-evident artifact manifests.
- service.py: application methods shared by CLI/MCP/agent; no client-supplied filesystem paths.
- report.py: raw/conditioned/time-frequency/SNR plots and source-linked HTML/Markdown reports.
- mcp_server.py: actual stdio MCP capabilities over the shared service.
- agent.py: bounded Azure/OpenAI-compatible chat tool loop, structured final response requiring evidence IDs; token/call budgets.
- benchmark.py: opaque fixtures, grading separated from tool access, negative control and seeded hidden injections into real off-source strain; no claim of secure blinding against an adversarial operator.
- cli.py: doctor, events, run, report, verify, agent, bench and mcp entrypoints.

## Scientific constraints
Search is an event-centred educational reproduction, not a blind astrophysical discovery. Never conflate detector-frame and source-frame masses. Finite nonspinning bank estimates carry no posterior credible intervals. Raw peak SNR is not a false-alarm probability; two detector peaks do not establish discovery significance. Conditioning and PSD choices must be recorded. Reject nonfinite/discontinuous/insufficient data and contaminated quality intervals; discard filter edges. Preserve all quality warnings. A no-signal benchmark must be allowed to return no candidate. Injection truth stays out of agent-visible task metadata until grading.

## Implementation sequence and acceptance
1. Write and remotely run data/cache tests (RED), implement checked download and HDF5 ingestion (GREEN).
2. Develop physics numerical tests and integration on real GW150914 data remotely; independent core module owner.
3. Write workspace/service tests first, implement immutable evidence and bounded paths.
4. Add reports, CLI and real MCP subprocess tests; verify installed-wheel user workflow on VM.
5. Add model loop and deterministic benchmark graders; run available Azure models with explicit low call budgets; publish actual results without fabricating metrics.
6. Full remote quality gate: unit/integration tests, lint, dependency audit, package build and clean-wheel smoke; static secret review locally.
7. GitHub public repository, tagged release, built wheel/source archive, scientific methodology and limitations, contributor/security/license docs. Read back remote commit and release assets. PyPI and MCP registry publication are separate gates requiring usable account authorization; if unavailable, provide tested GitHub-release/pip installation and state the exact blocked registry steps.

## Release evidence
- Successful official H1/L1 downloads and checksums.
- Real numerical results and source-linked plots, not fixture screenshots.
- Tests covering bounds, tampering, malformed data, numerical controls and MCP wire calls.
- Real Azure agent tool calls plus benchmark reports including negative controls.
- Installation from built artifact and verified GitHub release identity.
