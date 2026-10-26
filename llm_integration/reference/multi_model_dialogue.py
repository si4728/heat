from __future__ import annotations

import argparse
import gc
import json
import os
import re
import sys
import time
from collections import deque
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable
from uuid import uuid4


Responder = Callable[[str, str], str]

MAX_CONTEXT_CHARS = 6000
MAX_MEMORY_ITEMS = 12
DEFAULT_MODELS_CONFIG_PATH = Path("models.json")
DEFAULT_MAX_TOKENS = 2048


@dataclass(frozen=True)
class DialogueStep:
    round_number: int
    model_role: str
    model_key: str
    input_prompt: str
    output_text: str
    step_type: str = "response"


@dataclass(frozen=True)
class ModelSpec:
    key: str
    label: str
    provider: str
    model_name: str
    model_path: str | None = None
    llama_n_ctx: int | None = None


@dataclass(frozen=True)
class AgentSpec:
    key: str
    role: str
    model_ref: str
    system_prompt: str
    temperature: float = 0.7
    max_tokens: int | None = None


@dataclass(frozen=True)
class WorkflowEvent:
    run_id: str
    task_id: str
    round_number: int
    agent_key: str
    agent_role: str
    model_ref: str
    input_prompt: str
    output_text: str
    event_type: str = "response"
    elapsed_seconds: float | None = None
    error: str | None = None


_local_llms: dict[str, Any] = {}
_local_llm_order: list[str] = []
_local_llm_lock = RLock()


class LlamaCppClient:
    def __init__(
        self,
        models: dict[str, ModelSpec] | None = None,
        keep_loaded: bool = True,
        max_loaded_models: int = 1,
        serialize_requests: bool = True,
    ) -> None:
        self.models = models or {}
        self.keep_loaded = keep_loaded
        self.max_loaded_models = max(1, max_loaded_models)
        self.serialize_requests = serialize_requests

    def generate(
        self,
        model_ref: str,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        model = self.resolve_model(model_ref)
        if not model.model_path:
            raise ValueError(f"Model has no GGUF path: {model_ref}")

        lock_context = _local_llm_lock if self.serialize_requests else nullcontext()
        with lock_context:
            llm, cache_key = self.load_model(model.model_path, model.llama_n_ctx)
            try:
                response = llm.create_chat_completion(
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt or "You are a helpful AI assistant.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
                )
                content = response["choices"][0]["message"]["content"]
                return remove_thinking_blocks(str(content))
            finally:
                if not self.keep_loaded:
                    unload_local_llm(cache_key)

    def resolve_model(self, model_ref: str) -> ModelSpec:
        if model_ref in self.models:
            model = self.models[model_ref]
            if model.provider != "llama_cpp":
                raise ValueError(
                    f"Only llama_cpp models are supported in standalone CLI mode: {model_ref}"
                )
            return model

        expanded_path = os.path.expandvars(model_ref)
        if Path(expanded_path).exists():
            return ModelSpec(
                key=Path(expanded_path).stem,
                label=Path(expanded_path).stem,
                provider="llama_cpp",
                model_name=Path(expanded_path).stem,
                model_path=expanded_path,
                llama_n_ctx=None,
            )

        raise ValueError(
            f"Unknown model reference: {model_ref}. Use a llama_cpp key from models.json or a GGUF path."
        )

    def load_model(self, model_path: str, llama_n_ctx: int | None = None) -> tuple[Any, str]:
        resolved_path = os.path.expandvars(model_path)
        resolved_n_ctx = llama_n_ctx or int(os.getenv("LLAMA_N_CTX", "4096"))
        cache_key = f"{resolved_path}::n_ctx={resolved_n_ctx}"

        if self.keep_loaded and cache_key in _local_llms:
            touch_cache_key(cache_key)
            return _local_llms[cache_key], cache_key

        if not Path(resolved_path).exists():
            raise FileNotFoundError(f"Model file not found: {resolved_path}")

        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise RuntimeError(
                "llama-cpp-python is required for direct local model communication. "
                "Install dependencies from requirements.txt."
            ) from exc

        llm = Llama(
            model_path=resolved_path,
            n_ctx=resolved_n_ctx,
            n_threads=int(os.getenv("LLAMA_N_THREADS", "8")),
            n_batch=int(os.getenv("LLAMA_N_BATCH", "512")),
            n_gpu_layers=int(os.getenv("LLAMA_N_GPU_LAYERS", "0")),
            verbose=False,
        )

        if self.keep_loaded:
            _local_llms[cache_key] = llm
            touch_cache_key(cache_key)
            enforce_local_llm_cache_limit(self.max_loaded_models)

        return llm, cache_key


class Agent:
    def __init__(self, spec: AgentSpec, client: LlamaCppClient) -> None:
        self.spec = spec
        self.client = client

    def build_prompt(self, original_prompt: str, memory_text: str) -> str:
        sections = [
            f"[Role]\n{self.spec.role}",
            f"[Original User Request]\n{original_prompt}",
        ]
        if memory_text:
            sections.append(f"[Dialogue Memory]\n{memory_text}")
        sections.append("[Instruction]\nRespond according to your role. Be concise, concrete, and useful.")
        return "\n\n".join(sections)

    def run(self, original_prompt: str, memory_text: str, dry_run: bool = False) -> tuple[str, str]:
        prompt = self.build_prompt(original_prompt, memory_text)
        if dry_run:
            return prompt, f"[dry-run] {self.spec.role} would call llama_cpp:{self.spec.model_ref}"

        output = self.client.generate(
            model_ref=self.spec.model_ref,
            prompt=prompt,
            system_prompt=self.spec.system_prompt,
            temperature=self.spec.temperature,
            max_tokens=self.spec.max_tokens,
        )
        return prompt, output


class WorkflowManager:
    def __init__(self, agents: Iterable[Agent]) -> None:
        self.agents = list(agents)
        if not self.agents:
            raise ValueError("At least one agent is required.")

    def iter_events(
        self,
        original_prompt: str,
        rounds: int = 1,
        dry_run: bool = False,
    ) -> Iterable[WorkflowEvent]:
        prompt = (original_prompt or "").strip()
        if not prompt:
            raise ValueError("Prompt is required.")

        run_id = str(uuid4())
        rounds = clamp_rounds(rounds)
        memory_items: list[str] = []

        for round_number in range(1, rounds + 1):
            queue = deque(self.agents)
            while queue:
                agent = queue.popleft()
                task_id = str(uuid4())
                started_at = time.perf_counter()

                try:
                    input_prompt, output_text = agent.run(
                        prompt,
                        build_memory_text(memory_items),
                        dry_run=dry_run,
                    )
                except Exception as exc:
                    yield WorkflowEvent(
                        run_id=run_id,
                        task_id=task_id,
                        round_number=round_number,
                        agent_key=agent.spec.key,
                        agent_role=agent.spec.role,
                        model_ref=agent.spec.model_ref,
                        input_prompt="",
                        output_text="",
                        event_type="error",
                        elapsed_seconds=time.perf_counter() - started_at,
                        error=str(exc),
                    )
                    return

                yield WorkflowEvent(
                    run_id=run_id,
                    task_id=task_id,
                    round_number=round_number,
                    agent_key=agent.spec.key,
                    agent_role=agent.spec.role,
                    model_ref=agent.spec.model_ref,
                    input_prompt=input_prompt,
                    output_text=output_text,
                    elapsed_seconds=time.perf_counter() - started_at,
                )

                memory_items.append(
                    f"{agent.spec.role} ({agent.spec.key}):\n{shrink_text(output_text)}"
                )

        yield WorkflowEvent(
            run_id=run_id,
            task_id=str(uuid4()),
            round_number=rounds,
            agent_key="FINAL",
            agent_role="FINAL",
            model_ref="FINAL",
            input_prompt="",
            output_text=memory_items[-1] if memory_items else "",
            event_type="final",
        )


def touch_cache_key(cache_key: str) -> None:
    if cache_key in _local_llm_order:
        _local_llm_order.remove(cache_key)
    _local_llm_order.append(cache_key)


def unload_local_llm(cache_key: str) -> None:
    llm = _local_llms.pop(cache_key, None)
    if cache_key in _local_llm_order:
        _local_llm_order.remove(cache_key)
    if llm is not None:
        close_method = getattr(llm, "close", None)
        if callable(close_method):
            close_method()
        del llm
        gc.collect()


def enforce_local_llm_cache_limit(max_loaded_models: int) -> None:
    while len(_local_llm_order) > max_loaded_models:
        unload_local_llm(_local_llm_order[0])


def load_model_specs(config_path: Path = DEFAULT_MODELS_CONFIG_PATH) -> tuple[dict[str, ModelSpec], dict[str, Any]]:
    if not config_path.exists():
        return {}, {}

    data = json.loads(config_path.read_text(encoding="utf-8"))
    models: dict[str, ModelSpec] = {}
    for item in data.get("models", []):
        key = str(item.get("key", "")).strip()
        provider = str(item.get("provider", "")).strip()
        model_name = str(item.get("model_name", "")).strip()
        if not key or provider != "llama_cpp" or not model_name:
            continue

        llama_n_ctx_value = item.get("llama_n_ctx")
        try:
            llama_n_ctx = int(llama_n_ctx_value) if llama_n_ctx_value not in (None, "") else None
        except (TypeError, ValueError):
            llama_n_ctx = None

        models[key] = ModelSpec(
            key=key,
            label=str(item.get("label") or model_name or key),
            provider=provider,
            model_name=model_name,
            model_path=(
                os.path.expandvars(str(item.get("model_path")))
                if item.get("model_path")
                else None
            ),
            llama_n_ctx=llama_n_ctx,
        )

    return models, data.get("local_llm_cache", {})


def clamp_rounds(value: int, minimum: int = 1, maximum: int = 10) -> int:
    return max(minimum, min(value, maximum))


def shrink_text(text: str) -> str:
    text = text or ""
    if len(text) <= MAX_CONTEXT_CHARS:
        return text
    half = MAX_CONTEXT_CHARS // 2
    return text[:half] + "\n\n...\n\n" + text[-half:]


def build_memory_text(memory_items: list[str]) -> str:
    if not memory_items:
        return ""
    return "\n\n".join(memory_items[-MAX_MEMORY_ITEMS:])


def remove_thinking_blocks(text: str) -> str:
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.IGNORECASE | re.DOTALL).strip()


def build_model_b_prompt(original_prompt: str, memory_text: str, model_a_output: str) -> str:
    return (
        "You are LLM-B.\n\n"
        "Review LLM-A's latest answer.\n"
        "Correct mistakes.\n"
        "Add missing information.\n"
        "Challenge weak reasoning if necessary.\n"
        "Produce an improved answer.\n\n"
        f"[Original Prompt]\n{original_prompt}\n\n"
        f"[Dialogue Memory]\n{memory_text}\n\n"
        f"[Latest LLM-A Answer]\n{shrink_text(model_a_output)}"
    )


def build_model_a_followup_prompt(original_prompt: str, memory_text: str, model_b_output: str) -> str:
    return (
        "You are LLM-A.\n\n"
        "Review LLM-B's latest answer.\n"
        "Resolve disagreements.\n"
        "Integrate useful improvements.\n"
        "Produce the next best answer.\n\n"
        f"[Original Prompt]\n{original_prompt}\n\n"
        f"[Dialogue Memory]\n{memory_text}\n\n"
        f"[Latest LLM-B Answer]\n{shrink_text(model_b_output)}"
    )


def run_dual_model_dialogue(
    model_a_key: str,
    model_b_key: str,
    original_prompt: str,
    rounds: int,
    responder: Responder,
) -> list[DialogueStep]:
    return list(
        iter_dual_model_dialogue_steps(
            model_a_key=model_a_key,
            model_b_key=model_b_key,
            original_prompt=original_prompt,
            rounds=rounds,
            responder=responder,
        )
    )


def iter_dual_model_dialogue_steps(
    model_a_key: str,
    model_b_key: str,
    original_prompt: str,
    rounds: int,
    responder: Responder,
):
    prompt = (original_prompt or "").strip()
    if not prompt:
        raise ValueError("Prompt is required.")

    rounds = clamp_rounds(rounds)
    memory_items: list[str] = []

    model_a_input = prompt
    yield DialogueStep(0, "LLM-A", model_a_key, model_a_input, "", "prompt")

    try:
        model_a_output = responder(model_a_key, model_a_input)
    except Exception as exc:
        yield DialogueStep(0, "SYSTEM", "ERROR", model_a_input, str(exc), "error")
        return

    yield DialogueStep(0, "LLM-A", model_a_key, model_a_input, model_a_output, "response")
    memory_items.append(f"LLM-A:\n{shrink_text(model_a_output)}")

    for round_number in range(1, rounds + 1):
        memory_text = build_memory_text(memory_items)
        model_b_input = build_model_b_prompt(prompt, memory_text, model_a_output)
        yield DialogueStep(round_number, "LLM-B", model_b_key, model_b_input, "", "prompt")

        try:
            model_b_output = responder(model_b_key, model_b_input)
        except Exception as exc:
            yield DialogueStep(round_number, "SYSTEM", "ERROR", model_b_input, str(exc), "error")
            return

        yield DialogueStep(round_number, "LLM-B", model_b_key, model_b_input, model_b_output, "response")
        memory_items.append(f"LLM-B:\n{shrink_text(model_b_output)}")

        memory_text = build_memory_text(memory_items)
        model_a_input = build_model_a_followup_prompt(prompt, memory_text, model_b_output)
        yield DialogueStep(round_number, "LLM-A", model_a_key, model_a_input, "", "prompt")

        try:
            model_a_output = responder(model_a_key, model_a_input)
        except Exception as exc:
            yield DialogueStep(round_number, "SYSTEM", "ERROR", model_a_input, str(exc), "error")
            return

        yield DialogueStep(round_number, "LLM-A", model_a_key, model_a_input, model_a_output, "response")
        memory_items.append(f"LLM-A:\n{shrink_text(model_a_output)}")

    yield DialogueStep(rounds, "FINAL", "FINAL", "", model_a_output, "final")


def parse_agent_spec(value: str, temperature: float, max_tokens: int | None) -> AgentSpec:
    parts = [part.strip() for part in value.split("|", 3)]
    if len(parts) != 4 or not all(parts):
        raise argparse.ArgumentTypeError(
            "Agent must use this format: agent_key|role|model_key_or_gguf_path|system_prompt"
        )

    key, role, model_ref, system_prompt = parts
    return AgentSpec(
        key=key,
        role=role,
        model_ref=model_ref,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def load_agents_from_file(path: Path, temperature: float, max_tokens: int | None) -> list[AgentSpec]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Agent config file must contain a JSON list.")

    agents: list[AgentSpec] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Each agent config item must be an object.")
        agents.append(
            AgentSpec(
                key=str(item["key"]),
                role=str(item["role"]),
                model_ref=str(item.get("model_ref") or item.get("model_key") or item["model"]),
                system_prompt=str(item.get("system_prompt", "")),
                temperature=float(item.get("temperature", temperature)),
                max_tokens=(
                    int(item["max_tokens"])
                    if item.get("max_tokens") is not None
                    else max_tokens
                ),
            )
        )
    return agents


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if args.prompt:
        return args.prompt.strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise ValueError("Prompt is required. Use --prompt, --prompt-file, or stdin.")


def event_to_dict(event: WorkflowEvent) -> dict[str, object]:
    return {
        "run_id": event.run_id,
        "task_id": event.task_id,
        "round_number": event.round_number,
        "agent_key": event.agent_key,
        "agent_role": event.agent_role,
        "model_ref": event.model_ref,
        "input_prompt": event.input_prompt,
        "output_text": event.output_text,
        "event_type": event.event_type,
        "elapsed_seconds": event.elapsed_seconds,
        "error": event.error,
    }


def format_event(event: WorkflowEvent, show_prompts: bool = False) -> str:
    lines = [
        "",
        f"### Round {event.round_number} | {event.agent_role} | {event.event_type}",
        f"- agent: {event.agent_key}",
        f"- model: {event.model_ref}",
    ]
    if event.elapsed_seconds is not None:
        lines.append(f"- elapsed: {event.elapsed_seconds:.2f}s")
    if event.error:
        lines.append(f"- error: {event.error}")
    if show_prompts and event.input_prompt:
        lines.extend(["", "[Input Prompt]", event.input_prompt])
    if event.output_text:
        lines.extend(["", "[Output]", event.output_text])
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a standalone multi-model dialogue workflow with direct llama.cpp GGUF loading."
    )
    parser.add_argument("--prompt", help="User prompt to process.")
    parser.add_argument("--prompt-file", help="Read the user prompt from a UTF-8 text file.")
    parser.add_argument(
        "--agent",
        action="append",
        default=[],
        help="Agent definition: agent_key|role|model_key_or_gguf_path|system_prompt. Can be repeated.",
    )
    parser.add_argument("--agents-file", help="JSON file containing a list of agent definitions.")
    parser.add_argument("--models-config", default=str(DEFAULT_MODELS_CONFIG_PATH))
    parser.add_argument("--rounds", type=int, default=1, help="Number of times to run the agent chain.")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--max-loaded-models", type=int)
    parser.add_argument("--unload-after-use", action="store_true")
    parser.add_argument("--no-serialize", action="store_true")
    parser.add_argument("--show-prompts", action="store_true", help="Print full generated prompts.")
    parser.add_argument("--json", action="store_true", help="Print workflow events as JSON.")
    parser.add_argument("--output", help="Write output to a UTF-8 text file.")
    parser.add_argument("--dry-run", action="store_true", help="Build prompts without loading models.")
    return parser


def build_agents_from_args(args: argparse.Namespace, client: LlamaCppClient) -> list[Agent]:
    specs: list[AgentSpec] = []

    if args.agents_file:
        specs.extend(load_agents_from_file(Path(args.agents_file), args.temperature, args.max_tokens))

    for raw_agent in args.agent:
        specs.append(parse_agent_spec(raw_agent, args.temperature, args.max_tokens))

    if not specs:
        raise ValueError(
            "At least one agent is required. Example: "
            '--agent "planner|Planner|Gemma_Local_1|You create a concise plan."'
        )

    return [Agent(spec, client) for spec in specs]


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        models, cache_config = load_model_specs(Path(args.models_config))
        client = LlamaCppClient(
            models=models,
            keep_loaded=not args.unload_after_use,
            max_loaded_models=args.max_loaded_models
            or int(cache_config.get("max_loaded_models", 1) or 1),
            serialize_requests=not args.no_serialize
            and bool(cache_config.get("serialize_requests", True)),
        )
        prompt = read_prompt(args)
        agents = build_agents_from_args(args, client)
        manager = WorkflowManager(agents)
        events = list(manager.iter_events(prompt, rounds=args.rounds, dry_run=args.dry_run))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        output = json.dumps([event_to_dict(event) for event in events], ensure_ascii=False, indent=2)
    else:
        output = "\n".join(format_event(event, show_prompts=args.show_prompts) for event in events)

    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)

    return 1 if any(event.event_type == "error" for event in events) else 0


if __name__ == "__main__":
    raise SystemExit(main())


