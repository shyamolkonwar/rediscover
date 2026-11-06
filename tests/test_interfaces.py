import importlib.util


def test_interfaces_exist():
    for module in ["report", "mcp_server", "agent", "benchmark", "cli"]:
        assert importlib.util.find_spec("rediscover." + module) is not None, module


def test_agent_rejects_unbacked_measurements():
    from rediscover.agent import validate_final
    result = {"run_id": "a", "detectors": {"H1": {"evidence_id": "e-test", "result": {
        "snr": 12.0, "chirp_mass": 30.0, "peak_gps": 100.0}}}, "combined": {}}
    good = {"measurements": [{"detector": "H1", "evidence_id": "e-test", "snr": 12.0,
                             "chirp_mass": 30.0, "peak_gps": 100.0}], "candidate": True}
    assert validate_final(good, result)["valid"]
    good["measurements"][0]["snr"] = 99
    assert not validate_final(good, result)["valid"]
    assert not validate_final({"measurements": [], "candidate": False}, result)["valid"]


def test_grader_checks_negative_control_and_mass():
    from rediscover.benchmark import grade
    truth = {"signal": True, "chirp_mass": 30.0, "peak_gps": 8.0}
    result = {"snr": 15.0, "chirp_mass": 30.5, "peak_gps": 8.005}
    assert grade(result, truth)["passed"]
    assert not grade(result, {"signal": False})["passed"]
    assert grade({"snr": 3.0}, {"signal": False})["passed"]


def test_mcp_stdio(tmp_path):
    import asyncio
    import os
    import sys

    from mcp.client import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def exercise():
        params = StdioServerParameters(command=sys.executable,
            args=["-m", "rediscover.mcp_server"],
            env={**os.environ, "REDISCOVER_HOME": str(tmp_path)})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {"fetch_strain", "analyze_detector", "make_report", "get_guide"}.issubset(
                    {t.name for t in tools.tools})
                result = await session.call_tool("get_guide", {})
                assert not result.is_error
                bad = await session.call_tool("get_results", {"run_id": "../etc"})
                assert bad.is_error
    asyncio.run(exercise())
