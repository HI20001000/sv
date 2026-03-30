import os
from pathlib import Path
from typing import List

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from code_components.document_browser import list_input_documents
from code_components.langChain import invoke_response, ping_model, stream_response
from code_components.script_processing import process_script_to_output


def _build_session() -> PromptSession:
    completer = WordCompleter(
        ["/help", "/clear", "/history", "/model", "/ping", "/docs", "/exit"],
        ignore_case=True,
    )
    style = Style.from_dict({"prompt": "ansicyan bold"})
    return PromptSession(
        history=FileHistory(".chat_history"),
        auto_suggest=AutoSuggestFromHistory(),
        completer=completer,
        style=style,
    )


def _print_banner(console: Console) -> None:
    banner = (
        "[bold cyan]LangChain Terminal Chat[/bold cyan]\n"
        "[white]输入内容直接对话，输入命令管理会话。[/white]\n"
        "[dim]/help 查看命令，/exit 退出[/dim]"
    )
    console.print(Panel(banner, border_style="cyan", expand=False))


def _print_help(console: Console) -> None:
    table = Table(title="命令列表", header_style="bold magenta")
    table.add_column("命令", style="cyan", no_wrap=True)
    table.add_column("说明", style="white")
    table.add_row("/help", "显示帮助信息")
    table.add_row("/clear", "清空屏幕（保留上下文记忆）")
    table.add_row("/history", "查看当前会话的上下文条目数量")
    table.add_row("/model", "查看当前连接的大模型配置")
    table.add_row("/ping", "发送最小请求验证模型连通性")
    table.add_row(
        "/docs",
        "选剧本后生成 cleaned/story_bible/units/framework/episodes，并输出拆集与逐集规划",
    )
    table.add_row("/exit", "退出程序")
    console.print(table)


def _print_model_info(console: Console) -> None:
    base_url = os.environ["LLM_BASE_URL"]
    model = os.environ["LLM_MODEL"]
    body = f"[bold]Model:[/bold] {model}\n[bold]Base URL:[/bold] {base_url}"
    console.print(Panel(body, title="[bold green]当前配置[/bold green]", border_style="green"))


def _print_document_table(console: Console, files: List[Path]) -> None:
    table = Table(title="input_documents 文件列表", header_style="bold magenta")
    table.add_column("#", style="cyan", no_wrap=True)
    table.add_column("文件名", style="white")
    table.add_column("类型", style="green")
    table.add_column("大小(KB)", style="yellow", justify="right")
    for index, path in enumerate(files, start=1):
        size_kb = f"{path.stat().st_size / 1024:.1f}"
        table.add_row(str(index), path.name, path.suffix.lower(), size_kb)
    console.print(table)


def _handle_docs_command(console: Console, session: PromptSession, llm) -> None:
    files = list_input_documents()
    if not files:
        console.print(
            Panel(
                "input_documents 目录下没有可读取的 .txt 或 .docx 文件。",
                title="[bold yellow]Documents[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    _print_document_table(console, files)
    raw_choice = session.prompt([("class:prompt", "Select file # (Enter 取消) > ")]).strip()
    if not raw_choice:
        return
    if not raw_choice.isdigit():
        console.print(
            Panel(
                "请输入数字编号。",
                title="[bold red]Documents[/bold red]",
                border_style="red",
            )
        )
        return

    selected_index = int(raw_choice)
    if selected_index < 1 or selected_index > len(files):
        console.print(
            Panel(
                f"编号超出范围，请输入 1 - {len(files)}。",
                title="[bold red]Documents[/bold red]",
                border_style="red",
            )
        )
        return

    selected_path = files[selected_index - 1]
    workflow_logs: list[str] = []
    try:
        with console.status("[bold green]正在执行处理流程...[/bold green]") as status:
            def on_progress(stage: str, payload: dict[str, object]) -> None:
                message = str(payload.get("message", stage))
                status.update(f"[bold green]{message}[/bold green]")
                if not workflow_logs or workflow_logs[-1] != message:
                    workflow_logs.append(message)
                    console.print(f"[cyan]流程[/cyan] {message}")

            result = process_script_to_output(
                llm=llm,
                source_path=selected_path,
                progress_callback=on_progress,
            )
    except Exception as exc:
        console.print(
            Panel(
                f"处理失败：{exc}",
                title="[bold red]Documents[/bold red]",
                border_style="red",
            )
        )
        return

    workflow_text = "\n".join(f"{index}. {line}" for index, line in enumerate(workflow_logs, start=1))
    summary = (
        "[bold green]处理完成[/bold green]\n"
        f"源文件: {selected_path.name}\n"
        f"项目目录: {result.project_dir}\n"
        f"清洗输出: {result.cleaned_script_path}\n"
        f"特征输出: {result.story_bible_path}\n"
        f"Unit 输出: {result.story_units_path}\n"
        f"Unit 框架输出: {result.unit_frameworks_path}\n"
        f"拆集计划(项目): {result.project_episode_plan_path}\n"
        f"拆集计划(根目录): {result.root_episode_plan_path}\n"
        f"逐集规划(项目): {result.project_episode_generation_plan_path}\n"
        f"逐集规划(根目录): {result.root_episode_generation_plan_path}\n"
        f"剧集内容目录: {result.episodes_dir}\n"
        f"剧集计划目录: {result.episodes_plan_dir}\n"
        f"分镜目录: {result.storyboards_dir}\n"
        f"Unit 数量: {result.unit_count}\n"
        f"目标剧集数: {result.target_episode_count}\n"
        f"计划剧集数: {result.planned_episode_count}\n"
        f"逐集规划条目数: {result.planned_episode_outline_count}\n"
        f"已生成剧集数: {result.generated_episode_count}\n"
        f"已生成分镜数: {result.generated_storyboard_count}\n"
        f"总耗时: {result.total_elapsed_seconds:.2f}s\n"
        f"原文字数: {result.source_chars}\n"
        f"清洗后字数: {result.cleaned_chars}\n"
        "\n"
        "流程详情:\n"
        f"{workflow_text}"
    )
    console.print(Panel(summary, title="[bold green]Documents[/bold green]", border_style="green"))


def run_terminal_chat(llm, chain, console: Console) -> None:
    history: List[BaseMessage] = []
    session = _build_session()

    console.clear()
    _print_banner(console)

    while True:
        try:
            raw = session.prompt([("class:prompt", "\nYou > ")])
        except (KeyboardInterrupt, EOFError):
            console.print("\n[bold yellow]会话结束。[/bold yellow]")
            break

        user_input = raw.strip()
        if not user_input:
            continue

        if user_input == "/exit":
            console.print("[bold yellow]已退出。[/bold yellow]")
            break
        if user_input == "/help":
            _print_help(console)
            continue
        if user_input == "/clear":
            console.clear()
            _print_banner(console)
            continue
        if user_input == "/history":
            console.print(
                Panel(
                    f"当前上下文消息数量: [bold]{len(history)}[/bold]",
                    title="[bold blue]History[/bold blue]",
                    border_style="blue",
                    expand=False,
                )
            )
            continue
        if user_input == "/model":
            _print_model_info(console)
            continue
        if user_input == "/ping":
            try:
                text, elapsed = ping_model(llm)
                console.print(
                    Panel(
                        f"[bold green]连通成功[/bold green]\n"
                        f"耗时: {elapsed:.2f}s\n"
                        f"返回: {text}",
                        title="[bold green]Ping Result[/bold green]",
                        border_style="green",
                    )
                )
            except Exception as exc:
                console.print(
                    Panel(
                        f"连通失败：{exc}",
                        title="[bold red]Ping Result[/bold red]",
                        border_style="red",
                    )
                )
            continue
        if user_input == "/docs":
            _handle_docs_command(console, session, llm)
            continue

        console.print(
            Panel(
                Markdown(user_input),
                title="[bold cyan]You[/bold cyan]",
                border_style="cyan",
            )
        )

        try:
            assistant_text = stream_response(chain, history, user_input, console)
            if not assistant_text:
                assistant_text = invoke_response(chain, history, user_input)
                console.print(
                    Panel(
                        Markdown(assistant_text),
                        title="[bold green]Assistant[/bold green]",
                        border_style="green",
                    )
                )
        except Exception as exc:
            console.print(
                Panel(
                    f"调用模型失败：{exc}",
                    title="[bold red]错误[/bold red]",
                    border_style="red",
                )
            )
            continue

        history.append(HumanMessage(content=user_input))
        history.append(AIMessage(content=assistant_text))


