"""Benchmark the actual local Uvicorn/FastAPI HTTP inference path."""

import argparse
import asyncio
from collections import Counter
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

import httpx

from .api import PredictionResponse
from .data import load_dataset


def percentiles(values):
    """Nearest-rank percentiles; no interpolation or discarded slow requests."""
    if not values:
        return None
    ordered = sorted(values)
    return {f"p{p}_ms": ordered[math.ceil(p / 100 * len(ordered)) - 1] for p in (50, 95, 99)}


async def measure(client, payloads, model_version, requests, concurrency, warmup):
    if requests < 1 or concurrency < 1 or concurrency > requests or warmup < 1:
        raise ValueError("Require requests >= concurrency >= 1 and warmup >= 1")

    async def send(index):
        start = time.perf_counter_ns()
        try:
            response = await client.post("/v1/anomaly/predict", json=payloads[index % len(payloads)])
            elapsed = (time.perf_counter_ns() - start) / 1e6
            response.raise_for_status()
            result = PredictionResponse.model_validate(response.json())
            if result.model_version != model_version or result.request_id != response.headers.get("X-Request-ID"):
                raise ValueError("Response provenance mismatch")
            return {"elapsed_ms": elapsed, "error": None}
        except Exception as error:
            return {"elapsed_ms": (time.perf_counter_ns() - start) / 1e6,
                    "error": type(error).__name__}

    for index in range(warmup):
        if (await send(index))["error"]:
            raise RuntimeError("Warm-up request failed")

    async def worker(worker_id):
        return [await send(index) for index in range(worker_id, requests, concurrency)]

    started = time.perf_counter()
    groups = await asyncio.gather(*(worker(i) for i in range(concurrency)))
    elapsed = time.perf_counter() - started
    samples = [sample for group in groups for sample in group]
    successes = [s["elapsed_ms"] for s in samples if s["error"] is None]
    return {"requests": requests, "concurrency": concurrency, "warmup_requests": warmup,
            "successful_requests": len(successes), "failed_requests": requests - len(successes),
            "errors": dict(Counter(s["error"] for s in samples if s["error"])),
            "latency": percentiles(successes), "all_attempt_latency": percentiles([s["elapsed_ms"] for s in samples]),
            "duration_seconds": elapsed, "requests_per_second": requests / elapsed,
            "samples": samples}


def benchmark(dataset_path, detector_path, requests=1000, concurrency=4, warmup=50, port=8002):
    dataset = load_dataset(dataset_path)
    # A reproducible mix of all validation windows; labels are never sent to the API.
    payloads = [{"start_timestamp": w.start_timestamp, "flow_rates_gpm": list(w.flow_rates_gpm)}
                for w in dataset.validation]
    ml_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(ml_root), AQUAMIND_DETECTOR_PATH=str(detector_path.resolve()))
    url = f"http://127.0.0.1:{port}"
    command = [sys.executable, "-m", "uvicorn", "aquamind_ml.api:app", "--host", "127.0.0.1",
               "--port", str(port), "--workers", "1", "--no-access-log"]
    with tempfile.TemporaryFile() as logs:
        server = subprocess.Popen(command, env=env, stdout=logs, stderr=logs)
        try:
            deadline = time.monotonic() + 30
            with httpx.Client(base_url=url, timeout=1, trust_env=False) as probe:
                while True:
                    if server.poll() is not None:
                        raise RuntimeError("Benchmark server exited before readiness; check model and port")
                    try:
                        response = probe.get("/ready")
                        response.raise_for_status()
                        version = response.json()["model_version"]
                        break
                    except (httpx.HTTPError, KeyError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Benchmark server did not become ready") from None
                        time.sleep(0.1)
            # Verify that our process owns a live server, not a pre-existing listener.
            if server.poll() is not None:
                raise RuntimeError("Benchmark server failed to bind")

            async def run():
                async with httpx.AsyncClient(base_url=url, timeout=10, trust_env=False,
                        limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)) as client:
                    return await measure(client, payloads, version, requests, concurrency, warmup)

            report = asyncio.run(run())
            if server.poll() is not None:
                raise RuntimeError("Benchmark server exited during measurement; results discarded")
            report.update({
                "schema_version": 1, "model_version": version, "dataset_sha256": dataset.sha256,
                "path": "POST /v1/anomaly/predict", "transport": "HTTP/1.1 over loopback TCP",
                "timing": "client POST call through full response body; includes JSON encoding, TCP, validation, queueing, inference and response serialization",
                "warmup": "sequential requests before measurement; excludes server startup/model loading",
                "load": "closed-loop concurrent workers with a shared keep-alive pool; no retries",
                "percentile_method": "nearest rank on successful requests; all-attempt percentiles also recorded",
                "environment": {"platform": platform.platform(), "machine": platform.machine(),
                                "python": platform.python_version(), "logical_cpus": os.cpu_count(),
                                "packages": {name: importlib.metadata.version(name) for name in ("torch", "fastapi", "uvicorn", "httpx")},
                                "server_workers": 1, "torch_threads": 1, "inference_serialized": True},
                "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                  for name in ("api.py", "benchmark.py")},
                "limitations": ["Local warm-server measurement, not deployed internet latency",
                                 "Load generator and server share one machine", "Cold start excluded"],
            })
            return report
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")
    report = benchmark(args.dataset, args.detector, args.requests, args.concurrency, args.warmup, args.port)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: report[k] for k in ("successful_requests", "failed_requests", "latency")}, indent=2))
    if report["failed_requests"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
