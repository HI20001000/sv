import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from code_components.langChain import build_workflow, make_llm, validate_env
from code_components.terminal_chat import run_terminal_chat

console = Console()


def main() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path, encoding="utf-8-sig")
    validate_env(console)

    llm = make_llm()
    chain = build_workflow(llm)
    run_terminal_chat(llm=llm, chain=chain, console=console)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        console.print(
            Panel(
                f"程序异常退出：{exc}",
                title="[bold red]Fatal[/bold red]",
                border_style="red",
            )
        )
        sys.exit(1)
