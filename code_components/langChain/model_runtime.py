from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List, Tuple

from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel


def build_workflow(llm: ChatOpenAI):
    """LangChain workflow: prompt -> model -> parser."""
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a professional, direct, and reliable AI assistant. Keep responses concise and provide steps when needed.",
            ),
            MessagesPlaceholder("history"),
            ("human", "{input}"),
        ]
    )
    return prompt | llm | StrOutputParser()


def validate_env(console: Console) -> None:
    required = ["LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"]
    missing = [key for key in required if not os.getenv(key)]
    if not missing:
        return

    msg = "Missing required environment variables: " + ", ".join(missing) + "\nSet them in .env and retry."
    console.print(Panel(msg, title="[bold red]Configuration Error[/bold red]", border_style="red"))
    raise SystemExit(1)


def make_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.environ["LLM_MODEL"],
        api_key=os.environ["LLM_API_KEY"],
        base_url=os.environ["LLM_BASE_URL"],
        temperature=0.4,
        streaming=True,
        timeout=180,
        max_retries=2,
    )


def stream_response(
    chain, history: List[BaseMessage], user_input: str, console: Console
) -> str:
    text = ""
    with Live(
        Panel("[dim]Generating response...[/dim]", title="[bold green]Assistant[/bold green]"),
        refresh_per_second=20,
        console=console,
    ) as live:
        for chunk in chain.stream({"history": history, "input": user_input}):
            if not chunk:
                continue
            text += chunk
            live.update(
                Panel(
                    Markdown(text or " "),
                    title="[bold green]Assistant[/bold green]",
                    border_style="green",
                )
            )
    return text.strip()


def invoke_response(chain, history: List[BaseMessage], user_input: str) -> str:
    return chain.invoke({"history": history, "input": user_input})


def ping_model(llm: ChatOpenAI) -> Tuple[str, float]:
    start = time.perf_counter()
    resp = llm.invoke("Reply only: connection successful")
    elapsed = time.perf_counter() - start
    text = str(resp.content).strip() or "(empty response)"
    return text, elapsed


def clean_script_with_prompt(
    llm: ChatOpenAI,
    raw_script: str,
    prompt_path: Path | str = "prompt/script_cleaning_prompt_v1.md",
) -> str:
    response_text = _invoke_prompt_template(
        llm=llm,
        input_text=raw_script,
        prompt_path=prompt_path,
    )
    cleaned = response_text.strip()
    if cleaned == "[EMPTY_SCRIPT]":
        return ""
    return cleaned


def extract_script_features_with_prompt(
    llm: ChatOpenAI,
    script_text: str,
    prompt_path: Path | str = "prompt/script_feature_extraction_prompt_v1.md",
) -> str:
    return _invoke_prompt_template(
        llm=llm,
        input_text=script_text,
        prompt_path=prompt_path,
    ).strip()


def extract_unit_framework_with_prompt(
    llm: ChatOpenAI,
    unit_id: str,
    unit_text: str,
    prompt_path: Path | str = "prompt/unit_framework_extraction_prompt_v1.md",
) -> str:
    return _invoke_prompt_template_with_variables(
        llm=llm,
        prompt_path=prompt_path,
        variables={
            "UNIT_ID": unit_id,
            "UNIT_TEXT": unit_text,
        },
    ).strip()


def plan_unit_episode_split_with_prompt(
    llm: ChatOpenAI,
    unit_framework_json: str,
    target_episode_count: int,
    prompt_path: Path | str = "prompt/unit_episode_split_planning_prompt_v1.md",
) -> str:
    return _invoke_prompt_template_with_variables(
        llm=llm,
        prompt_path=prompt_path,
        variables={
            "UNIT_FRAMEWORK_JSON": unit_framework_json,
            "TARGET_EPISODE_COUNT": str(target_episode_count),
        },
    ).strip()


def plan_episode_generation_with_prompt(
    llm: ChatOpenAI,
    story_bible_json: str,
    unit_framework_json: str,
    episode_split_plan_json: str,
    target_episode_count: int,
    prompt_path: Path | str = "prompt/episode_generation_planning_prompt_v1.md",
) -> str:
    return _invoke_prompt_template_with_variables(
        llm=llm,
        prompt_path=prompt_path,
        variables={
            "STORY_BIBLE_JSON": story_bible_json,
            "UNIT_FRAMEWORK_JSON": unit_framework_json,
            "EPISODE_SPLIT_PLAN_JSON": episode_split_plan_json,
            "TARGET_EPISODE_COUNT": str(target_episode_count),
        },
    ).strip()


def generate_episode_content_with_prompt(
    llm: ChatOpenAI,
    story_bible_json: str,
    episode_plan_json: str,
    source_units_json: str,
    prompt_path: Path | str = "prompt/episode_content_generation_prompt_v1.md",
) -> str:
    return _invoke_prompt_template_with_variables(
        llm=llm,
        prompt_path=prompt_path,
        variables={
            "STORY_BIBLE_JSON": story_bible_json,
            "EPISODE_PLAN_JSON": episode_plan_json,
            "SOURCE_UNITS_JSON": source_units_json,
        },
    ).strip()


def generate_storyboard_with_prompt(
    llm: ChatOpenAI,
    story_bible_json: str,
    episode_json: str,
    prompt_path: Path | str = "prompt/storyboard_generation_prompt_v1.md",
) -> str:
    return _invoke_prompt_template_with_variables(
        llm=llm,
        prompt_path=prompt_path,
        variables={
            "STORY_BIBLE_JSON": story_bible_json,
            "EPISODE_JSON": episode_json,
        },
    ).strip()


def _invoke_prompt_template(
    llm: ChatOpenAI,
    input_text: str,
    prompt_path: Path | str,
) -> str:
    return _invoke_prompt_template_with_variables(
        llm=llm,
        prompt_path=prompt_path,
        variables={"RAW_SCRIPT": input_text},
    )


def _invoke_prompt_template_with_variables(
    llm: ChatOpenAI,
    prompt_path: Path | str,
    variables: dict[str, str],
) -> str:
    prompt_file = Path(prompt_path)
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

    prompt_template = prompt_file.read_text(encoding="utf-8")
    user_prompt = prompt_template
    for key, value in variables.items():
        user_prompt = user_prompt.replace(f"{{{{{key}}}}}", value)
    response = llm.invoke(user_prompt)
    return str(response.content)
