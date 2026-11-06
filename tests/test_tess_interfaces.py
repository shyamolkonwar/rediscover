import argparse

import pytest


def test_tess_command_registered():
    from rediscover.cli import parser
    args = parser().parse_args(["tess", "plan", "--count", "2"])
    assert args.tess_command == "plan"
    assert args.count == 2


def test_code_requires_explicit_cli_opt_in(tmp_path):
    from rediscover.tess_cli import handle
    args = argparse.Namespace(home=str(tmp_path), tess_command="research", campaign_id="a" * 32,
                              allow_code=False, model="example", experiments=2)
    with pytest.raises(ValueError, match="allow-code"):
        handle(args)
