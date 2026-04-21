#!/usr/bin/env python
"""Standalone consistency tester for Ligilo Esperanto evaluator (Gemini 1.5 Flash)."""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_MODEL = "gemini-1.5-flash"
DEFAULT_RUNS_PER_SAMPLE = 3
API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"


@dataclass
class Sample:
    sample_id: str
    text: str


SAMPLES: list[Sample] = [
    Sample("S01", "Saluton teamo, ni kunvenu je la oka por prepari la mision en la tendaro."),
    Sample("S02", "Mi estas skolto kaj mi lernas Esperanton chiutage kun mia patrolo."),
    Sample("S03", "Ni faris orientigon per mapo kaj kompaso apud la rivero."),
    Sample("S04", "Hodiau pluvas sed ni gardas bonan kunlaboron en la grupo."),
    Sample("S05", "Mi volas fari nodojn rapide, sed mi konfuzas la nomojn."),
    Sample("S06", "Nia gvidanto diris ke ni raportu post la nokta marsho."),
    Sample("S07", "Mi ne komprenas la frazoj kaj mi bezonas helpo por la finajxojn."),
    Sample("S08", "La patrolo preparis fajron sekure kaj kontrolis la areon."),
    Sample("S09", "Bonan matenon, hodiau ni trejnos signaladon kaj teaman laboron."),
    Sample("S10", "Yo soy scout y quiero aprender Esperanto para la mision internacional."),
    Sample("S11", "This is only English text about camping and teamwork."),
    Sample("S12", "Ni iras al tendaro morgau, cxu vi alportos la ilojn?"),
    Sample("S13", "La knaboj estis tre lacaj sed ili finis la taskon gxustatempe."),
    Sample("S14", "Patrolo stelo kolektis akvon, poste kuiris kaj raportis al la gvidanto."),
    Sample("S15", "Saluton"),
    Sample("S16", "Mi estas tre felicxa hodiau kaj mi dankas la teamo por subteni min."),
    Sample("S17", "Ni devas respekti naturon, lasi neniun rubon, kaj helpi aliajn."),
    Sample("S18", "Skoltoj, renkontigxu je la sesa por orientigo kaj sekureca kontrolo."),
    Sample("S19", "La misio estis malfacila, sed nia kunordigo estis tre bona."),
    Sample("S20", "patrolo patrolo patrolo, ni marshi rapide al tendaro nun"),
]


def load_system_prompt(prompt_path: Path) -> str:
    # Legas la majstran sisteman prompton el dosiero por eviti duobligitan tekston.
    return prompt_path.read_text(encoding="utf-8").strip()


def call_gemini(api_key: str, model: str, system_prompt: str, user_text: str, temperature: float) -> str:
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 500,
        },
    }

    req = request.Request(
        url=API_URL_TEMPLATE.format(model=model, api_key=api_key),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc

    parsed = json.loads(raw)
    candidates = parsed.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"No candidates in Gemini response: {raw}")

    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    if not parts or "text" not in parts[0]:
        raise RuntimeError(f"No text part in Gemini response: {raw}")

    return parts[0]["text"].strip()


def validate_strict_schema(obj: Any) -> tuple[bool, list[str]]:
    errors: list[str] = []

    if not isinstance(obj, dict):
        return False, ["Top-level response is not a JSON object"]

    required_keys = {"esperanto_level", "grammar_errors", "scout_terms_detected", "feedback_message"}
    obj_keys = set(obj.keys())

    missing = required_keys - obj_keys
    extra = obj_keys - required_keys
    if missing:
        errors.append(f"Missing keys: {sorted(missing)}")
    if extra:
        errors.append(f"Extra keys: {sorted(extra)}")

    level = obj.get("esperanto_level")
    if not isinstance(level, int) or not (1 <= level <= 5):
        errors.append("esperanto_level must be int between 1 and 5")

    grammar_errors = obj.get("grammar_errors")
    if not isinstance(grammar_errors, list) or not all(isinstance(item, str) for item in grammar_errors):
        errors.append("grammar_errors must be array of strings")

    scout_terms_detected = obj.get("scout_terms_detected")
    if not isinstance(scout_terms_detected, bool):
        errors.append("scout_terms_detected must be boolean")

    feedback_message = obj.get("feedback_message")
    if not isinstance(feedback_message, str) or len(feedback_message) > 240:
        errors.append("feedback_message must be string with max 240 chars")

    return len(errors) == 0, errors


def parse_json_response(text: str) -> tuple[dict[str, Any] | None, str | None]:
    # Iuj modelaj respondoj venas kun senmarka teksto antaux/posta; ni provas rekta parse unue.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj, None
        return None, "Parsed JSON is not an object"
    except json.JSONDecodeError:
        pass

    # Rezerva provo: trovu la unuan JSON-objekton inter plej grandaj krampoj.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj, None
            return None, "Recovered JSON is not an object"
        except json.JSONDecodeError as exc:
            return None, f"JSON decode error: {exc}"

    return None, "No JSON object found"


def export_results_json(path: Path, payload: dict[str, Any]) -> None:
    # Konservas kompletan resumon kaj per-rulan diagnozon por posta analizo.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def export_results_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    # CSV estas utila por rapida filtrado en kalkultabelo.
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "sample_id",
        "run_idx",
        "is_valid_schema",
        "parse_error",
        "schema_errors",
        "esperanto_level",
        "scout_terms_detected",
        "grammar_errors_count",
        "feedback_message",
        "raw_excerpt",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_consistency_test(
    api_key: str,
    model: str,
    prompt_path: Path,
    runs_per_sample: int,
    temperature: float,
    pause_seconds: float,
    output_json_path: Path,
    output_csv_path: Path,
) -> int:
    system_prompt = load_system_prompt(prompt_path)

    total_calls = len(SAMPLES) * runs_per_sample
    valid_schema_calls = 0
    fully_consistent_samples = 0
    sample_level_spreads: list[int] = []
    run_rows: list[dict[str, Any]] = []
    sample_summaries: list[dict[str, Any]] = []

    print(f"Model: {model}")
    print(f"Samples: {len(SAMPLES)}")
    print(f"Runs per sample: {runs_per_sample}")
    print(f"Total calls: {total_calls}")
    print("-" * 72)

    for sample in SAMPLES:
        level_results: list[int] = []
        scout_bool_results: list[bool] = []
        schema_errors_accum: list[str] = []

        for run_idx in range(1, runs_per_sample + 1):
            row_base: dict[str, Any] = {
                "sample_id": sample.sample_id,
                "run_idx": run_idx,
                "is_valid_schema": False,
                "parse_error": "",
                "schema_errors": "",
                "esperanto_level": "",
                "scout_terms_detected": "",
                "grammar_errors_count": "",
                "feedback_message": "",
                "raw_excerpt": "",
            }
            try:
                raw_text = call_gemini(
                    api_key=api_key,
                    model=model,
                    system_prompt=system_prompt,
                    user_text=sample.text,
                    temperature=temperature,
                )
                row_base["raw_excerpt"] = raw_text[:240].replace("\n", " ")
            except RuntimeError as exc:
                schema_errors_accum.append(f"Run {run_idx}: API error: {exc}")
                row_base["schema_errors"] = f"API error: {exc}"
                run_rows.append(row_base)
                if pause_seconds > 0:
                    time.sleep(pause_seconds)
                continue

            parsed_obj, parse_err = parse_json_response(raw_text)
            if parse_err:
                schema_errors_accum.append(f"Run {run_idx}: {parse_err}")
                row_base["parse_error"] = parse_err
                run_rows.append(row_base)
                if pause_seconds > 0:
                    time.sleep(pause_seconds)
                continue

            is_valid, schema_errors = validate_strict_schema(parsed_obj)
            if not is_valid:
                schema_errors_accum.append(f"Run {run_idx}: {'; '.join(schema_errors)}")
                row_base["schema_errors"] = "; ".join(schema_errors)
            else:
                valid_schema_calls += 1
                level_results.append(parsed_obj["esperanto_level"])
                scout_bool_results.append(parsed_obj["scout_terms_detected"])
                row_base["is_valid_schema"] = True
                row_base["esperanto_level"] = parsed_obj["esperanto_level"]
                row_base["scout_terms_detected"] = parsed_obj["scout_terms_detected"]
                row_base["grammar_errors_count"] = len(parsed_obj["grammar_errors"])
                row_base["feedback_message"] = parsed_obj["feedback_message"]

            run_rows.append(row_base)

            if pause_seconds > 0:
                time.sleep(pause_seconds)

        sample_valid_runs = len(level_results)
        if sample_valid_runs > 0:
            spread = max(level_results) - min(level_results)
            sample_level_spreads.append(spread)
            bool_consistent = len(set(scout_bool_results)) == 1
            level_consistent = spread == 0
            sample_consistent = bool_consistent and level_consistent and sample_valid_runs == runs_per_sample
            if sample_consistent:
                fully_consistent_samples += 1

            print(
                f"{sample.sample_id}: valid_runs={sample_valid_runs}/{runs_per_sample}, "
                f"level_spread={spread}, scout_bool_values={sorted(set(scout_bool_results))}, "
                f"fully_consistent={sample_consistent}"
            )
        else:
            spread = None
            bool_consistent = False
            level_consistent = False
            sample_consistent = False
            print(f"{sample.sample_id}: valid_runs=0/{runs_per_sample}, fully_consistent=False")

        sample_summaries.append(
            {
                "sample_id": sample.sample_id,
                "sample_text": sample.text,
                "valid_runs": sample_valid_runs,
                "runs_per_sample": runs_per_sample,
                "level_values": level_results,
                "scout_bool_values": scout_bool_results,
                "level_spread": spread,
                "level_consistent": level_consistent,
                "scout_bool_consistent": bool_consistent,
                "fully_consistent": sample_consistent,
                "issues": schema_errors_accum,
            }
        )

        if schema_errors_accum:
            print("  Issues:")
            for issue in schema_errors_accum:
                print(f"  - {issue}")

    print("-" * 72)
    strict_json_rate = valid_schema_calls / total_calls if total_calls else 0.0
    sample_consistency_rate = fully_consistent_samples / len(SAMPLES) if SAMPLES else 0.0
    avg_level_spread = statistics.mean(sample_level_spreads) if sample_level_spreads else float("nan")

    print(f"Strict JSON success rate: {strict_json_rate:.2%} ({valid_schema_calls}/{total_calls})")
    print(f"Full consistency rate: {sample_consistency_rate:.2%} ({fully_consistent_samples}/{len(SAMPLES)})")
    print(f"Average esperanto_level spread: {avg_level_spread:.2f}")

    summary_payload = {
        "model": model,
        "samples": len(SAMPLES),
        "runs_per_sample": runs_per_sample,
        "total_calls": total_calls,
        "metrics": {
            "strict_json_success_rate": strict_json_rate,
            "valid_schema_calls": valid_schema_calls,
            "full_consistency_rate": sample_consistency_rate,
            "fully_consistent_samples": fully_consistent_samples,
            "average_esperanto_level_spread": avg_level_spread,
        },
        "sample_summaries": sample_summaries,
        "run_rows": run_rows,
    }
    export_results_json(output_json_path, summary_payload)
    export_results_csv(output_csv_path, run_rows)
    print(f"Exported JSON report: {output_json_path}")
    print(f"Exported CSV report: {output_csv_path}")

    # Elirkodo: 0 se almenaux 90% de respondoj sekvas la striktan JSON-kontrakton.
    return 0 if strict_json_rate >= 0.90 else 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gemini consistency test for Ligilo Esperanto evaluator")
    parser.add_argument(
        "--api-key",
        default=os.getenv("GEMINI_API_KEY", ""),
        help="Gemini API key (or set GEMINI_API_KEY)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--prompt-path",
        default="prompts/gemini_esperanto_system_prompt.txt",
        help="Path to system prompt file",
    )
    parser.add_argument(
        "--runs-per-sample",
        type=int,
        default=DEFAULT_RUNS_PER_SAMPLE,
        help=f"How many times to run each sample (default: {DEFAULT_RUNS_PER_SAMPLE})",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Sampling temperature (default: 0.2)",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=0.0,
        help="Optional pause between calls to reduce rate limiting",
    )
    parser.add_argument(
        "--output-json",
        default="outputs/gemini_consistency_report.json",
        help="Output JSON report path",
    )
    parser.add_argument(
        "--output-csv",
        default="outputs/gemini_consistency_runs.csv",
        help="Output CSV runs path",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    if not args.api_key:
        print("Error: Missing API key. Use --api-key or set GEMINI_API_KEY.", file=sys.stderr)
        return 2

    prompt_path = Path(args.prompt_path)
    if not prompt_path.exists():
        print(f"Error: Prompt file not found: {prompt_path}", file=sys.stderr)
        return 2

    if args.runs_per_sample < 1:
        print("Error: --runs-per-sample must be >= 1", file=sys.stderr)
        return 2

    return run_consistency_test(
        api_key=args.api_key,
        model=args.model,
        prompt_path=prompt_path,
        runs_per_sample=args.runs_per_sample,
        temperature=args.temperature,
        pause_seconds=args.pause_seconds,
        output_json_path=Path(args.output_json),
        output_csv_path=Path(args.output_csv),
    )


if __name__ == "__main__":
    raise SystemExit(main())
