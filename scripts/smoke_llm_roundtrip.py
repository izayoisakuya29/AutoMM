"""手动运行的真实模型往返 smoke。"""

from __future__ import annotations

import argparse
import json
import subprocess
import time

import jsonschema

from automm.common import ROOT, read_json, resolve_project_path
from automm.llm import get_provider
from automm.llm.profiles import load_profile, load_runtime_config

_MINIMAL_PROMPT = (
    "你是 AutoMM 往返测试。只输出一个 JSON 对象，不要解释或 Markdown：\n"
    '{"schema_version":1,"action_id":"act-smoke","status":"success","problem_id":"smoke",'
    '"question_id":"prob01","assumption_version":null,"formulation_version":null,'
    '"artifacts_created":[],"artifacts_updated":[],"findings":[],"warnings":[],'
    '"blocking_reasons":[],"recommended_next_stage":null,"commands":[]}'
)


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoMM LLM harness 往返 smoke")
    parser.add_argument("--profile", required=True, help="agent_runtime.yaml 中的 profile 名")
    args = parser.parse_args()

    config = load_runtime_config()
    profile = load_profile(args.profile, config)
    profile["output_schema"] = config["output_schema"]
    provider = get_provider(profile)
    provider.probe()

    run_dir = ROOT / "runtime" / "smoke" / args.profile
    run_dir.mkdir(parents=True, exist_ok=True)
    output_path = run_dir / "response.json"
    invocation = provider.prepare(_MINIMAL_PROMPT, output_path)

    timeout = profile.get("timeout_seconds") or 600
    kwargs = {
        "cwd": ROOT,
        "env": invocation.env,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
    }
    if invocation.stdin is not None:
        kwargs["input"] = invocation.stdin
    else:
        kwargs["stdin"] = subprocess.DEVNULL

    started = time.perf_counter()
    result = subprocess.run(invocation.command, **kwargs)
    elapsed = time.perf_counter() - started

    try:
        response = provider.extract_response(invocation, result.stdout, result.stderr, result.returncode)
        schema = read_json(resolve_project_path(config["output_schema"], must_exist=True))
        jsonschema.validate(response, schema)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "profile": args.profile,
                    "harness": profile["harness"],
                    "model": profile.get("model"),
                    "returncode": result.returncode,
                    "elapsed_seconds": round(elapsed, 2),
                    "error": str(exc),
                    "stderr_tail": (result.stderr or "")[-2000:],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "profile": args.profile,
                "harness": profile["harness"],
                "model": profile.get("model"),
                "returncode": result.returncode,
                "elapsed_seconds": round(elapsed, 2),
                "response": response,
                "stderr_tail": (result.stderr or "")[-500:],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
