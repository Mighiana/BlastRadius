from __future__ import annotations

import json
import resource
import sys
from pathlib import Path

from lark.exceptions import UnexpectedInput
from pydantic import ValidationError

from blastradius.server.analysis import ResourceLimitError, analyze_input
from blastradius.server.failures import FailureCode
from blastradius.server.schemas import WorkerInput


def main() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (int(sys.argv[3]), int(sys.argv[3]) + 1))
    workdir = Path(sys.argv[1])
    try:
        payload = WorkerInput.model_validate_json((workdir / "input.json").read_bytes())
        result = analyze_input(payload.analysis, workdir, int(sys.argv[2]), payload.policy_snapshot)
        response: dict = {"result": result}
    except ResourceLimitError:
        response = {"error": FailureCode.RESOURCE_LIMIT_EXCEEDED}
    except (
        ValueError,
        ValidationError,
        UnexpectedInput,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
    ):
        response = {"error": FailureCode.INVALID_ANALYSIS_INPUT}
    except MemoryError:
        response = {"error": FailureCode.RESOURCE_LIMIT_EXCEEDED}
    except Exception:
        response = {"error": FailureCode.ANALYSIS_FAILED}
    (workdir / "output.json").write_text(json.dumps(response), encoding="utf-8")


if __name__ == "__main__":
    main()
