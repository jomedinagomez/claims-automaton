"""Minimal CLI entry point for Semantic Kernel Claims Orchestration demos."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .runtime import create_runtime
from .parsers import parse_freeform_claim

# No additional document rules needed - rely on standard documents:
# - Police reports
# - Repair estimates  
# - Witness statements
# - Medical receipts
ADDITIONAL_DOCUMENT_RULES = []

app = typer.Typer(
    name="claims-sk",
    help="Semantic Kernel Claims Orchestration CLI",
    add_completion=False,
)

console = Console()


@app.command()
def process(
    claim_file: Path = typer.Argument(
        ...,
        help="Path to claim submission JSON or Markdown file",
        exists=True,
        file_okay=True,
        dir_okay=False,
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Directory to write handoff payload (default: ./output)",
    ),
    config_dir: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config directory",
    ),
    interactive: bool = typer.Option(
        True,
        "--interactive/--no-interactive",
        "-i/-I",
        help="Prompt for missing documents (default: enabled)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
):
    """
    Process a single claim submission through the orchestration workflow.
    
    If documents are missing and --interactive is enabled (default), you will be
    prompted to provide document paths. Otherwise, the claim will be saved in
    paused state.
    """

    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)
    console.print(
        Panel.fit(
            "[bold cyan]Claims Orchestration Demo[/bold cyan]\n"
            f"Processing claim from: [yellow]{claim_file}[/yellow]",
            border_style="cyan",
        )
    )

    claim_data = _load_claim_data(claim_file)
    result = asyncio.run(_run_orchestration(claim_data, config_dir, interactive))

    _display_results(result)
    if result.get("handoff_payload"):
        output_path = _export_handoff_payload(result, output_dir)
        console.print(f"\n[green]✓[/green] Handoff payload exported: [cyan]{output_path}[/cyan]")

    status = result.get("status")
    if status in {"approved", "denied"}:
        raise typer.Exit(0)
    
    if status == "paused":
        claim_id = claim_data.get("claim_id", "unknown")
        console.print(
            f"\n[blue]ℹ[/blue] Claim paused. Resume with:\n"
            f"  [cyan]python -m claims_sk.cli resume {claim_id}[/cyan]"
        )
        raise typer.Exit(0)

    console.print(f"\n[yellow]⚠[/yellow] Orchestration ended with status: [yellow]{status}[/yellow]")
    raise typer.Exit(1)


async def _run_orchestration(claim_data, config_dir, interactive=True):
    """
    Execute the orchestration workflow asynchronously.
    
    If interactive mode is enabled and documents are missing, prompts user
    to provide document paths and continues processing.
    """
    runtime = await create_runtime(config_dir=config_dir)
    orchestrator = runtime.get_orchestrator()
    
    # Initial processing
    result = await orchestrator.process_claim(claim_data)
    
    # Interactive pause/resume loop
    max_iterations = 3  # Prevent infinite loops
    iteration = 0
    
    while result["status"] == "paused" and interactive and iteration < max_iterations:
        iteration += 1
        missing_docs = result.get("missing_documents", [])
        
        if not missing_docs:
            break
        
        console.print("\n[bold yellow]⚠ Missing Information Detected[/bold yellow]")
        console.print("The claim cannot proceed without the following evidence:\n")
        
        for idx, doc_type in enumerate(missing_docs, 1):
            console.print(f"  {idx}. [cyan]{doc_type}[/cyan]")
        
        # Prompt user
        if not typer.confirm("\nWould you like to provide this information now?", default=True):
            console.print("[dim]Claim saved in paused state. Use 'resume' command to continue later.[/dim]")
            break
        
        # Collect supplemental evidence
        additional_payload = _collect_missing_information(missing_docs)
        
        if not _has_additional_payload(additional_payload):
            console.print("[yellow]No information provided. Claim will remain paused.[/yellow]")
            break
        
        # Continue processing
        console.print("\n[bold]Resuming orchestration with additional evidence...[/bold]")
        claim_id = claim_data.get("claim_id") or result.get("context", {}).get("claim_id")
        
        try:
            result = await orchestrator.continue_claim(
                claim_id=claim_id,
                additional_documents=additional_payload,
            )
        except Exception as e:
            console.print(f"[red]Error resuming claim:[/red] {e}")
            break
    
    return result


def _display_results(result):
    """
    Display orchestration results in formatted output.
    """
    status = result.get("status", "unknown")
    termination_reason = result.get("termination_reason", "unknown")
    context = result.get("context", {})
    rounds = result.get("rounds_executed", 0)
    
    # Status panel
    status_color = {
        "approved": "green",
        "denied": "red",
        "stalled": "yellow",
        "timeout": "yellow",
        "paused": "blue",
    }.get(status, "white")
    
    console.print(
        Panel.fit(
            f"[bold {status_color}]{status.upper()}[/bold {status_color}]\n"
            f"Termination Reason: {termination_reason}\n"
            f"Rounds Executed: {rounds}",
            title="[bold]Orchestration Result[/bold]",
            border_style=status_color,
        )
    )
    
    # If paused, show missing requirements prominently
    if status == "paused":
        missing_docs = result.get("missing_documents", []) or context.get("missing_documents", [])
        if missing_docs:
            console.print("\n[bold yellow]⚠ Required Information:[/bold yellow]")
            for idx, doc in enumerate(missing_docs, 1):
                console.print(f"  {idx}. [cyan]{doc}[/cyan]")
            console.print("\n[dim]Provide this information (chat or document) to continue processing.[/dim]")
    
    # Context metadata table
    metadata_table = Table(title="Context Metadata", show_header=True)
    metadata_table.add_column("Key", style="cyan")
    metadata_table.add_column("Value", style="white")
    
    key_fields = [
        "claim_id",
        "policy_number",
        "agent_decision",
        "handoff_status",
    ]

    for key in key_fields:
        if key in context:
            value = context[key]
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value) if value else "[]"
            metadata_table.add_row(key, str(value))

    console.print(metadata_table)
    
    # Handoff payload preview (if available)
    if result.get("handoff_payload"):
        payload = result["handoff_payload"]
        console.print("\n[bold cyan]Handoff Payload Preview:[/bold cyan]")
        console.print(json.dumps(payload, indent=2))


def _load_claim_data(path: Path) -> Dict[str, Any]:
    """Load claim data from JSON or Markdown format."""
    try:
        with open(path, "r", encoding="utf-8") as stream:
            content = stream.read()
        
        # Check file extension
        if path.suffix.lower() == ".json":
            claim_data = json.loads(content)
        elif path.suffix.lower() in [".md", ".markdown", ".txt"]:
            claim_data = parse_freeform_claim(content, path)
        else:
            console.print(f"[yellow]Warning:[/yellow] Unknown file type {path.suffix}, attempting markdown parse")
            claim_data = parse_freeform_claim(content, path)

        missing, resolved = _resolve_documents(claim_data, path.parent)
        if resolved:
            claim_data["document_paths"] = resolved

        combined_missing = claim_data.get("missing_documents", [])
        combined_missing.extend(missing)
        combined_missing.extend(_infer_additional_requirements(claim_data))
        deduped = []
        for item in combined_missing:
            if item and item not in deduped:
                deduped.append(item)
        if deduped:
            claim_data["missing_documents"] = deduped
            console.print("[yellow]Warning:[/yellow] Required documentation is missing:")
            for doc in deduped:
                console.print(f"  - {doc}")

        return claim_data
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]Error loading claim file:[/red] {exc}")
        raise typer.Exit(1) from exc


def _resolve_documents(claim_data: Dict[str, Any], base_dir: Path) -> Tuple[List[str], List[str]]:
    """Resolve referenced attachments and report any that are missing."""
    documents = claim_data.get("documents") or []
    if not documents:
        return [], []

    missing: List[str] = []
    resolved: List[str] = []

    for doc_name in documents:
        doc_path = Path(doc_name)
        candidates: List[Path] = []
        if doc_path.is_absolute():
            candidates.append(doc_path)
        else:
            candidates.append(base_dir / doc_path)
            candidates.append(base_dir / "documents" / doc_path.name)

        match = next((candidate for candidate in candidates if candidate.exists()), None)
        if match:
            resolved.append(str(match))
            continue

        preferred = candidates[0] if candidates else doc_path
        missing.append(str(preferred))

    return missing, resolved


def _infer_additional_requirements(claim_data: Dict[str, Any]) -> List[str]:
    documents = claim_data.get("documents") or []
    resolved_paths = claim_data.get("document_paths") or []
    observed = []
    for value in documents + resolved_paths:
        try:
            observed.append(Path(value).name.lower())
        except Exception:
            observed.append(str(value).lower())

    missing: List[str] = []
    for rule in ADDITIONAL_DOCUMENT_RULES:
        if not observed:
            missing.append(rule["label"])
            continue
        if not any(keyword in name for name in observed for keyword in rule["keywords"]):
            missing.append(rule["label"])
    return missing


def _collect_missing_information(missing_doc_types: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Allow users to satisfy missing requirements via text or file uploads."""

    payload: Dict[str, List[Dict[str, Any]]] = {"documents": [], "notes": []}
    console.print("\n[bold]Provide additional evidence for the items below.[/bold]")
    console.print("[dim]For each requirement choose: chat (inline answer), file (upload), or skip.[/dim]\n")

    for doc_type in missing_doc_types:
        while True:
            choice = typer.prompt(
                f"How would you like to provide '{doc_type}'? (chat/file/skip)",
                default="chat",
            ).strip().lower()

            if choice in {"skip", "s"}:
                console.print(f"  [dim]Skipping {doc_type}[/dim]")
                break

            if choice in {"chat", "text", "answer"}:
                note = _prompt_inline_response(doc_type)
                if note:
                    payload["notes"].append(note)
                else:
                    console.print(f"  [dim]No details captured for {doc_type}[/dim]")
                break

            if choice in {"file", "doc", "upload"}:
                docs = _prompt_for_file_evidence(doc_type)
                if docs:
                    payload["documents"].extend(docs)
                    break
                if not typer.confirm("  No files captured. Try again?", default=True):
                    break
                continue

            console.print("  [yellow]Please answer with 'chat', 'file', or 'skip'.[/yellow]")

    return {key: value for key, value in payload.items() if value}


def _prompt_for_file_evidence(doc_type: str) -> List[Dict[str, Any]]:
    """Collect one or more files/directories for a specific requirement."""

    documents: List[Dict[str, Any]] = []
    console.print("  [dim]Enter a file path or directory. Leave blank to cancel.[/dim]")

    while True:
        path_str = typer.prompt(
            f"    File or directory for '{doc_type}'",
            default="",
            show_default=False,
        )

        if not path_str.strip():
            break

        path = Path(path_str.strip()).expanduser()

        if path.is_dir():
            dir_files = [file_path for file_path in path.iterdir() if file_path.is_file()]
            if not dir_files:
                console.print("    [yellow]Directory is empty.[/yellow]")
                continue
            console.print(f"    [green]✓[/green] Added {len(dir_files)} files from directory")
            for file_path in dir_files:
                documents.append({
                    "type": doc_type,
                    "filename": file_path.name,
                    "path": str(file_path.resolve()),
                })
            break

        if path.is_file():
            console.print(f"    [green]✓[/green] File captured: {path.name}")
            documents.append({
                "type": doc_type,
                "filename": path.name,
                "path": str(path.resolve()),
            })
            if not typer.confirm("    Add another file for this requirement?", default=False):
                break
            continue

        console.print(f"    [red]✗[/red] File or directory not found: {path_str}")
        if not typer.confirm("    Try again?", default=True):
            break

    return documents


def _prompt_inline_response(doc_type: str) -> Optional[Dict[str, str]]:
    """Capture inline narrative data for a missing requirement."""

    console.print("  [dim]Type ':edit' to open your editor for multi-line input.[/dim]")
    response = typer.prompt(
        f"  Provide details for '{doc_type}'",
        default="",
        show_default=False,
    )

    if response.strip() == ":edit":
        template = f"# Provide details for {doc_type}\n"
        editor_response = typer.edit(template)
        if editor_response:
            response = "\n".join(
                line for line in editor_response.splitlines() if not line.startswith("#")
            )
        else:
            response = ""

    if not response.strip():
        return None

    return {
        "type": doc_type,
        "content": response.strip(),
    }


def _has_additional_payload(payload: Optional[Dict[str, List[Dict[str, Any]]]]) -> bool:
    if not payload:
        return False
    return bool(payload.get("documents") or payload.get("notes"))
def _export_handoff_payload(result, output_dir):
    """
    Export handoff payload to JSON file.
    """
    output_dir = output_dir or Path("./output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    claim_id = result.get("context", {}).get("claim_id", "unknown")
    output_path = output_dir / f"{claim_id}_handoff.json"
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result.get("handoff_payload"), f, indent=2)
    
    return output_path
@app.command()
def version():
    """Display basic version information."""
    console.print(
        Panel.fit(
            "[bold cyan]Semantic Kernel Claims Orchestration[/bold cyan]\n"
            "Version: 0.1.0",
            border_style="cyan",
        )
    )


@app.command()
def resume(
    claim_id: str = typer.Argument(
        ...,
        help="Claim ID to resume processing",
    ),
    documents_dir: Optional[Path] = typer.Option(
        None,
        "--documents",
        "-d",
        help="Directory containing additional documents to upload",
        exists=True,
        dir_okay=True,
        file_okay=False,
    ),
    config_dir: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Configuration directory",
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output directory for results",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
):
    """
    Resume processing a paused claim after providing missing documents.
    
    Example:
        python -m claims_sk.cli resume CLM-1120105522 -d ./new_docs -o ./output
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    
    async def _resume_claim():
        console.print(f"[bold cyan]Resuming claim:[/bold cyan] {claim_id}")
        
        # Bootstrap runtime
        runtime = await create_runtime(config_dir=config_dir)
        orchestrator = runtime.get_orchestrator()
        
        # Prepare additional documents if provided
        additional_documents = None
        if documents_dir:
            console.print(f"[dim]Loading documents from: {documents_dir}[/dim]")
            documents = []
            for doc_path in documents_dir.iterdir():
                if doc_path.is_file():
                    documents.append({
                        "type": doc_path.stem,
                        "filename": doc_path.name,
                        "path": str(doc_path),
                    })
            additional_documents = {"documents": documents}
            console.print(f"[green]✓[/green] Loaded {len(documents)} additional documents")
        
        # Resume orchestration
        console.print(f"[bold]Resuming orchestration...[/bold]")
        result = await orchestrator.continue_claim(
            claim_id=claim_id,
            additional_documents=additional_documents,
        )
        
        # Display results
        _display_results(result)
        
        # Export handoff payload if available
        if result.get("handoff_payload"):
            handoff_path = _export_handoff_payload(result, output_dir)
            console.print(f"[green]✓[/green] Handoff payload exported to: {handoff_path}")
        
        return result
    
    try:
        asyncio.run(_resume_claim())
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Orchestration failed:[/red] {e}")
        if verbose:
            console.print_exception()
        raise typer.Exit(code=1)


@app.command()
def list_sessions(
    config_dir: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Configuration directory",
    ),
):
    """
    List all saved claim sessions.
    
    Example:
        python -m claims_sk.cli list-sessions
    """
    async def _list_sessions():
        runtime = await create_runtime(config_dir=config_dir)
        orchestrator = runtime.get_orchestrator()
        
        if not orchestrator.session_store:
            console.print("[yellow]Session persistence is disabled[/yellow]")
            return
        
        sessions = orchestrator.session_store.list_sessions()
        
        if not sessions:
            console.print("[dim]No saved sessions found[/dim]")
            return
        
        table = Table(title="Saved Sessions")
        table.add_column("Claim ID", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Messages", style="yellow")
        table.add_column("Saved At", style="dim")
        
        for claim_id in sessions:
            session_data = orchestrator.session_store.load_session(claim_id)
            if session_data:
                metadata = session_data["metadata"]
                table.add_row(
                    claim_id,
                    metadata.get("status", "unknown"),
                    str(len(session_data["chat_history"].messages)),
                    metadata.get("saved_at", "unknown"),
                )
        
        console.print(table)
    
    asyncio.run(_list_sessions())


def main():
    """
    Main entry point for the CLI.
    """
    app()


if __name__ == "__main__":
    main()
