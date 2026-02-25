from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()

COLORS = {
    'RESET': '\033[0m',
    'BRIGHT': '\033[1m',
    'CYAN': '\033[96m',
    'YELLOW': '\033[93m',
    'GREEN': '\033[92m',
    'MAGENTA': '\033[95m',
    'BLUE': '\033[94m',
    'RED': '\033[91m',
    'WHITE': '\033[97m',
    'GRAY': '\033[90m',
}

LOG_CATEGORIES = {
    "SCRAPING": {"color": "CYAN", "enabled": True},
    "EVALUATING": {"color": "YELLOW", "enabled": True},
    "APPLYING": {"color": "GREEN", "enabled": True},
    "FORM": {"color": "MAGENTA", "enabled": True},
    "SESSION": {"color": "BLUE", "enabled": True},
    "SUCCESS": {"color": "GREEN", "enabled": True},
    "ERROR": {"color": "RED", "enabled": True},
    "WARNING": {"color": "YELLOW", "enabled": True},
    "INFO": {"color": "WHITE", "enabled": True},
    "DEBUG": {"color": "GRAY", "enabled": True},
    "SKIP": {"color": "RED", "enabled": True},
    "MATCH": {"color": "GREEN", "enabled": True},
    "AI": {"color": "MAGENTA", "enabled": True},
    "AI_INPUT": {"color": "MAGENTA", "enabled": False},
    "AI_OUTPUT": {"color": "CYAN", "enabled": True},
    "AI_TIMING": {"color": "YELLOW", "enabled": True},
    "SUMMARY": {"color": "CYAN", "enabled": True},
    # Interview Assistant categories
    "SENTINEL": {"color": "YELLOW", "enabled": True},
    "ADVISOR": {"color": "CYAN", "enabled": True},
    "AUDIO": {"color": "BLUE", "enabled": True},
    "TRANSCRIBE": {"color": "MAGENTA", "enabled": True},
}

def custom_print(category: str, message: str):
    config = LOG_CATEGORIES.get(category, {"color": "WHITE", "enabled": True})

    if not config['enabled']:
        return

    color = config['color']

    header_color = COLORS['BRIGHT'] + COLORS[color]
    formatted = f"{header_color}[{category}]{COLORS['RESET']} {COLORS['WHITE']}{message}{COLORS['RESET']}"
    print(formatted)

def print_header(text: str):
    console.print(f"\n[bold cyan]{text}[/bold cyan]")
    console.print("=" * 60)

def print_success(text: str):
    custom_print("SUCCESS", text)

def print_error(text: str):
    custom_print("ERROR", text)

def print_warning(text: str):
    custom_print("WARNING", text)

def print_info(text: str):
    console.print(f"[dim]{text}[/dim]")

def print_stats_table(stats: dict):
    table = Table(title="Application Statistics", box=box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")

    table.add_row("Total Jobs Scraped", str(stats.get('total_jobs', 0)))
    table.add_row("Total Evaluated", str(stats.get('total_evaluated', 0)))
    table.add_row("Applications Today", str(stats.get('applications_today', 0)))

    by_status = stats.get('applications_by_status', {})
    for status, count in by_status.items():
        table.add_row(f"  {status}", str(count))

    success_rate = stats.get('success_rate', 0)
    table.add_row("Success Rate", f"{success_rate:.1f}%")

    console.print("\n")
    console.print(table)
    console.print("\n")

def print_run_summary(scraped: int, evaluated: int, applied: int, today_total: int, daily_limit: int):
    summary = f"""
[bold]Scraping:[/bold] {scraped} jobs found
[bold]Evaluation:[/bold] {evaluated} jobs matched criteria
[bold]Applications:[/bold] {applied} submitted successfully
[bold]Today's Total:[/bold] {today_total}/{daily_limit}
"""
    console.print(Panel(summary, title="[bold green]Run Complete![/bold green]", border_style="green"))