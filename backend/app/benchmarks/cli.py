from __future__ import annotations

import argparse
import asyncio
import json

from app.benchmarks.service import BenchmarkService
from app.db import async_session_factory


async def _run_benchmark(args: argparse.Namespace) -> None:
    async with async_session_factory() as session:
        service = BenchmarkService(session)
        run = await service.create_run(
            provider=args.provider,
            model=args.model,
            dataset_name=args.dataset_name,
            dataset_version=args.dataset_version,
            max_cases=args.max_cases,
            concurrency=args.concurrency,
            seed=args.seed,
            timeout_seconds=args.timeout,
            max_retries=args.max_retries,
            max_budget_usd=args.budget,
            dry_run=args.dry_run,
            confirm_live_provider=bool(args.confirm_live_provider),
        )
        await service.execute_run(run.run_id)
        print(json.dumps({"run_id": run.run_id, "status": run.status}, ensure_ascii=False, sort_keys=True))


async def _show_status(args: argparse.Namespace) -> None:
    async with async_session_factory() as session:
        service = BenchmarkService(session)
        run = await service.get_run(args.run_id)
        print(json.dumps({"run_id": run.run_id, "status": run.status, "metrics": run.metrics}, ensure_ascii=False, sort_keys=True))


async def _resume_run(args: argparse.Namespace) -> None:
    async with async_session_factory() as session:
        service = BenchmarkService(session)
        run = await service.resume_run(args.run_id)
        print(json.dumps({"run_id": run.run_id, "status": run.status, "resumed": True}, ensure_ascii=False, sort_keys=True))


async def _export_result(args: argparse.Namespace) -> None:
    async with async_session_factory() as session:
        service = BenchmarkService(session)
        run = await service.get_run(args.run_id)
        payload = await service.export_run(run.id, output_format=args.format)
        print(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="benchmark", description="Benchmark execution engine for translation comparison")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a benchmark")
    run_parser.add_argument("--dataset-name", default="technical_translation")
    run_parser.add_argument("--dataset-version", default="2026.08.15")
    run_parser.add_argument("--provider", default="openai")
    run_parser.add_argument("--model", default="gpt-4o")
    run_parser.add_argument("--max-cases", type=int, default=10)
    run_parser.add_argument("--concurrency", type=int, default=1)
    run_parser.add_argument("--seed", type=int, default=0)
    run_parser.add_argument("--timeout", type=int, default=30)
    run_parser.add_argument("--max-retries", type=int, default=2)
    run_parser.add_argument("--budget", type=float, default=5.0)
    execution_mode = run_parser.add_mutually_exclusive_group()
    execution_mode.add_argument("--dry-run", dest="dry_run", action="store_true", help="Use deterministic offline execution")
    execution_mode.add_argument("--live", dest="dry_run", action="store_false", help="Use the configured live provider")
    run_parser.set_defaults(dry_run=True)
    run_parser.add_argument("--confirm-live-provider", action="store_true")
    run_parser.set_defaults(handler=_run_benchmark)

    status_parser = subparsers.add_parser("status", help="Check a run's status")
    status_parser.add_argument("run_id")
    status_parser.set_defaults(handler=_show_status)

    resume_parser = subparsers.add_parser("resume", help="Resume a benchmark run")
    resume_parser.add_argument("run_id")
    resume_parser.set_defaults(handler=_resume_run)

    export_parser = subparsers.add_parser("export", help="Export a run")
    export_parser.add_argument("run_id")
    export_parser.add_argument("--format", choices=["json", "csv"], default="json")
    export_parser.set_defaults(handler=_export_result)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(args.handler(args))
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == "__main__":
    main()
