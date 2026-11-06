# Using Rediscover

## Without AI

1. Install the release with `uv tool install` or into a Python virtual environment (see README).
2. Run `rediscover run GW150914-v3 --catalog`.
3. Open the HTML path printed in the JSON output. The HTML embeds its plots and works offline.
4. Keep the run directory to preserve source hashes, arrays, tool evidence and configuration.

The computation uses a bounded bank of nonspinning binary-black-hole templates. Do not use it to infer arbitrary neutron-star systems, high spins, cosmology, or discovery significance.

## With your own MCP host

Use `rediscover-mcp` as a stdio server after installing the package. No Azure key is needed: your host supplies the language model. Ask:

> Use Rediscover to analyze GW150914-v3. Check data quality for both detectors, calculate the matched-filter results, explain detector-frame versus source-frame masses, and produce an evidence report. Do not claim a new discovery or significance.

Tools:

- `get_guide`: workflow, caveats and supported data.
- `list_events`: one explicitly paginated catalog page.
- `fetch_strain`: official 32-second H1/L1 pair; immutable run ID.
- `check_data_quality`: numerical and official quality flags.
- `analyze_detector`: PSD, matched filtering and finite-bank parameter search.
- `get_results`: latest evidence-backed detector and timing results.
- `get_catalog`: fetch published inference separately, after numerical analysis.
- `make_report`: raw strain, whitening/bandpass visualization, Q-transform and report.
- `verify_artifacts`: checksum integrity check.

Whitening and bandpass are configured numerical stages, not model-generated transformations. They are recorded in the analysis configuration. Report visualization uses its own explicitly labelled settings.

## Azure or another Responses-compatible provider

Explicitly configure `REDISCOVER_API_BASE`, `REDISCOVER_API_KEY`, and choose a deployment with `--model`. The base ends in `/openai/v1` for Azure or `/v1` for OpenAI. Use your environment manager, never paste keys into issues or reports.

```sh
rediscover fetch GW150914-v3
rediscover agent RUN_ID --model YOUR_DEPLOYMENT
rediscover report RUN_ID
```

A successful model call alone is not success. The final measurement fields must agree with numerical tool evidence, including evidence IDs and all detectors. The built-in harness uses the same application methods as MCP but is a bounded Responses function-tool client, not an MCP transport client. The MCP interface is separately tested over stdio.

Default agent budget: eight provider calls, twelve numerical tool calls, and 4096 output tokens per provider call. Output caps include reasoning tokens. Input tokens also cost money; these are call/output limits, not a dollar spending guarantee. Requests are not automatically retried.

## Benchmarks

```sh
rediscover bench
rediscover bench --model YOUR_DEPLOYMENT
rediscover bench --events GW150914-v3 --no-hidden
```

The default suite includes three named events, two synthetic injections into actual detector strain, and a no-added-signal control. The injection windows are off the known GW150914 chirp; the rest of that real data segment still contains the original event and is disclosed in the truth record. All injection parameters are revealed after evaluation.

Thresholds are demonstration criteria: peak SNR at least 8, injection peak time within 30 milliseconds, and injection detector-frame chirp mass within 20 percent. Named-event timing respects catalog rounding: the tolerance is the larger of 30 milliseconds and half the returned time resolution plus 10.1 milliseconds. See the results document for the disclosed pre-release rubric correction. These are not discovery thresholds or credible intervals. Failed tasks remain in the report and return exit code 2. This tiny suite is not a leaderboard or population-level model comparison.

## Failures and privacy

A GWOSC download failure is an error, not simulated data. Corrupt cached files fail checksum validation. Missing H1/L1 short files produce an explicit unsupported-event error. Use a different supported event instead of silently substituting data.

Data and reports remain under `~/.rediscover` by default. Set `REDISCOVER_HOME`, or pass `--home PATH` before the subcommand. The local CLI does not call an LLM unless `agent` or `bench --model` is explicitly requested.
