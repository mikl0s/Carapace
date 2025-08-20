#!/usr/bin/env python3
"""
Carapace CLI - Command Line Interface for the Carapace Addon Manager
"""

import typer
from typing import Optional, List
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.progress import track
from rich.panel import Panel
from rich import print as rprint
from rich.text import Text
import logging
from datetime import datetime

from carapace.parser import WikiParser
from carapace.db import Database
from carapace.paths import PathDetector
from carapace.installer import AddonInstaller
from carapace import __version__

# Setup
app = typer.Typer(help="Carapace - TurtleWoW Addon Manager")
console = Console()
logger = logging.getLogger(__name__)

# Get database path
def get_db() -> Database:
    """Get database connection"""
    return Database()

@app.command()
def sync(
    force: bool = typer.Option(False, "--force", "-f", help="Force refresh even if recently synced"),
    local: Optional[Path] = typer.Option(None, "--local", "-l", help="Parse from local HTML file instead of wiki")
):
    """Sync addon catalog from wiki"""
    console.print("\n[bold cyan]Carapace Addon Sync[/bold cyan]")
    console.print("-" * 40)
    
    parser = WikiParser()
    db = get_db()
    
    try:
        if local:
            console.print(f"Parsing from local file: {local}")
            if not local.exists():
                console.print(f"[red]Error: File not found: {local}[/red]")
                raise typer.Exit(1)
            addons = parser.parse_from_file(local)
        else:
            # Check wiki revision before syncing
            if not force:
                try:
                    import requests
                    api_url = "https://turtle-wow.fandom.com/api.php"
                    params = {
                        "action": "query",
                        "prop": "revisions",
                        "titles": "Addons",
                        "rvprop": "timestamp|ids",
                        "format": "json",
                        "formatversion": "2"
                    }
                    response = requests.get(api_url, params=params)
                    current_revid = response.json()['query']['pages'][0]['revisions'][0]['revid']
                    
                    # Check stored revision
                    stored_revid = db.get_setting("wiki_revision_id")
                    if stored_revid and str(current_revid) == stored_revid:
                        console.print("[green]Wiki has not changed since last sync[/green]")
                        console.print("[dim]Use --force to sync anyway[/dim]")
                        return
                    
                    # Store new revision ID
                    db.set_setting("wiki_revision_id", str(current_revid))
                except Exception as e:
                    logger.debug(f"Could not check wiki revision: {e}")
            
            console.print("Fetching from TurtleWoW wiki...")
            addons = parser.parse_from_url()
        
        console.print(f"[green][OK][/green] Parsed {len(addons)} addons")
        
        # Store in database
        for addon in track(addons, description="", console=console, transient=True):
            db.upsert_addon(addon)
        
        # Log event
        db.log_event("sync_complete", details={
            "addon_count": len(addons),
            "source": "local" if local else "wiki"
        })
        
        console.print(f"[green][OK][/green] Database updated successfully")
        
        # Show statistics
        stats_table = Table(title="Sync Statistics")
        stats_table.add_column("Category", style="cyan")
        stats_table.add_column("Count", justify="right")
        
        # Count tags
        tag_counts = {}
        for addon in addons:
            for tag in addon.get('tags', []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        
        # Recalculate tags from the stored addons
        stored_addons = db.get_addons()
        stored_tag_counts = {}
        for addon in stored_addons:
            for tag in addon.get('tags', []):
                stored_tag_counts[tag] = stored_tag_counts.get(tag, 0) + 1
        
        stats_table.add_row("Total Addons", str(len(stored_addons)))
        stats_table.add_row("Recommended", str(stored_tag_counts.get('recommended', 0)))
        stats_table.add_row("Featured", str(stored_tag_counts.get('featured', 0)))
        stats_table.add_row("SuperWoW Required", str(stored_tag_counts.get('superwow_required', 0)))
        stats_table.add_row("SuperWoW Features", str(stored_tag_counts.get('superwow_features', 0)))
        
        console.print("\n", stats_table)
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        logger.exception("Sync failed")
        raise typer.Exit(1)
    finally:
        db.close()

@app.command()
def list(
    search: Optional[str] = typer.Argument(None, help="Search term to filter addons"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter by tag"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of results to show"),
    all: bool = typer.Option(False, "--all", "-a", help="Show all results"),
    installed_only: bool = typer.Option(False, "--installed", "-i", help="Show only installed addons")
):
    """List available addons"""
    db = get_db()
    installer = AddonInstaller(db)
    
    try:
        # Sync installed state with filesystem
        installer.sync_installed_state()
        
        # Get installed addons for highlighting
        installed_addons = installer.get_installed_addons()
        
        addons = db.get_addons()
        
        # Filter by search term
        if search:
            search_lower = search.lower()
            addons = [a for a in addons if search_lower in a['name'].lower() or 
                     search_lower in a.get('description', '').lower()]
        
        # Filter by tag
        if tag:
            addons = [a for a in addons if tag in a.get('tags', [])]
        
        # Filter by installed status
        if installed_only:
            addons = [a for a in addons if a['name'].lower() in installed_addons]
        
        # Create table
        title = f"Available Addons ({len(addons)} total"
        installed_count = sum(1 for a in addons if a['name'].lower() in installed_addons)
        if installed_count > 0:
            title += f", {installed_count} installed"
        title += ")"
        
        table = Table(title=title)
        table.add_column("", width=2)  # Status indicator
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")
        table.add_column("Tags", style="yellow")
        
        # Limit results unless --all
        display_addons = addons if all else addons[:limit]
        
        for addon in display_addons:
            # Check if installed
            is_installed = addon['name'].lower() in installed_addons
            
            # Status indicator
            status = "[green]*[/green]" if is_installed else " "
            
            # Style the name differently if installed
            name_style = "[bold green]" + addon['name'] + "[/bold green]" if is_installed else addon['name']
            
            tags_str = ", ".join(addon.get('tags', []))
            desc = addon.get('description', '')[:60] + "..." if len(addon.get('description', '')) > 60 else addon.get('description', '')
            
            table.add_row(status, name_style, desc, tags_str)
        
        console.print(table)
        
        if installed_count > 0:
            console.print(f"\n[dim][green]*[/green] = Installed addon[/dim]")
        
        if not all and len(addons) > limit:
            console.print(f"[dim]Showing {limit} of {len(addons)} results. Use --all to see all.[/dim]")
        
    finally:
        db.close()

@app.command()
def info(addon_name: str):
    """Show detailed information about an addon"""
    db = get_db()
    installer = AddonInstaller(db)
    
    try:
        # Sync installed state
        installer.sync_installed_state()
        
        addons = db.get_addons()
        
        # Find addon (case-insensitive)
        addon = None
        for a in addons:
            if a['name'].lower() == addon_name.lower():
                addon = a
                break
        
        if not addon:
            # Try partial match
            matches = [a for a in addons if addon_name.lower() in a['name'].lower()]
            if matches:
                if len(matches) == 1:
                    addon = matches[0]
                else:
                    console.print(f"[yellow]Multiple matches found for '{addon_name}':[/yellow]")
                    for match in matches[:10]:
                        console.print(f"  - {match['name']}")
                    raise typer.Exit(1)
            else:
                console.print(f"[red]Addon not found: {addon_name}[/red]")
                raise typer.Exit(1)
        
        # Check installation status
        is_installed = installer.is_installed(addon['name'])
        installed_version = installer.get_installed_version(addon['name']) if is_installed else None
        
        # Build status line
        status_line = "[green]* INSTALLED[/green]" if is_installed else "[dim]Not installed[/dim]"
        if installed_version and installed_version != "unknown":
            status_line += f" (version: {installed_version})"
        
        # Display addon info
        panel_content = f"""[bold]{addon['name']}[/bold]

[cyan]Status:[/cyan]
{status_line}

[cyan]Description:[/cyan]
{addon.get('description', 'No description available')}

[cyan]Repository:[/cyan]
{addon.get('repo_url', 'N/A')}

[cyan]Tags:[/cyan]
{', '.join(addon.get('tags', [])) or 'None'}

[cyan]Host:[/cyan]
{addon.get('host', 'N/A')}
"""
        
        border_style = "green" if is_installed else "cyan"
        panel = Panel(panel_content, title="Addon Information", border_style=border_style)
        console.print(panel)
        
    finally:
        db.close()

@app.command()
def installed(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed information"),
    rescan: bool = typer.Option(False, "--rescan", "-r", help="Rescan addon directory")
):
    """List installed addons"""
    db = get_db()
    installer = AddonInstaller(db)
    
    try:
        # Optionally rescan
        if rescan:
            console.print("Rescanning addon directory...")
            newly_found, removed = installer.sync_installed_state()
            if newly_found > 0 or removed > 0:
                console.print(f"[cyan]Found {newly_found} new, removed {removed} missing[/cyan]")
        
        # Get installed addons
        installed_addons = installer.get_installed_addons()
        
        if not installed_addons:
            console.print("[yellow]No addons installed[/yellow]")
            addon_path = installer.addon_path
            if addon_path:
                console.print(f"[dim]Addon directory: {addon_path}[/dim]")
            else:
                console.print("[dim]No addon directory configured. Run 'carapace path --detect'[/dim]")
            return
        
        # Get addon details from database
        all_addons = {a['name'].lower(): a for a in db.get_addons()}
        
        # Create table
        table = Table(title=f"Installed Addons ({len(installed_addons)} total)")
        
        if verbose:
            table.add_column("Addon", style="green", no_wrap=True)
            table.add_column("Folder", style="cyan")
            table.add_column("Description", style="white")
            table.add_column("Repository", style="blue")
            table.add_column("Tags", style="yellow")
        else:
            table.add_column("Addon", style="green", no_wrap=True)
            table.add_column("Folder", style="cyan")
            table.add_column("Description", style="white")
            table.add_column("Tags")
        
        # Sort by addon name
        for addon_key in sorted(installed_addons.keys()):
            installed_info = installed_addons[addon_key]
            addon_name = installed_info['name']
            folder_name = Path(installed_info['path']).name if installed_info['path'] else 'unknown'
            
            # Get details from catalog
            catalog_info = all_addons.get(addon_key, {})
            description = catalog_info.get('description', 'Not in catalog')
            
            # Format tags with colors
            tag_list = catalog_info.get('tags', [])
            tags_text = Text()
            for i, tag in enumerate(tag_list):
                if i > 0:
                    tags_text.append(", ")
                    
                if tag == 'recommended':
                    tags_text.append(tag, style="green")
                elif tag == 'featured':
                    tags_text.append(tag, style="bold cyan")
                elif tag == 'leveling':
                    tags_text.append(tag, style="yellow")
                elif tag == 'endgame':
                    tags_text.append(tag, style="red")
                elif tag == 'superwow_required':
                    tags_text.append(tag, style="bold red")
                elif tag == 'superwow_features':
                    tags_text.append(tag, style="magenta")
                else:
                    tags_text.append(tag)
            
            repo_url = catalog_info.get('repo_url', installed_info.get('repo_url', ''))
            
            # Truncate description if needed
            if len(description) > 50 and not verbose:
                description = description[:47] + "..."
            
            if verbose:
                # Show repo URL in verbose mode
                if repo_url:
                    if len(repo_url) > 40:
                        repo_url = "..." + repo_url[-37:]
                else:
                    repo_url = "N/A"
                
                table.add_row(
                    addon_name,
                    folder_name,
                    description,
                    repo_url,
                    tags_text if tag_list else ""
                )
            else:
                table.add_row(
                    addon_name,
                    folder_name,
                    description,
                    tags_text if tag_list else ""
                )
        
        console.print(table)
        
        if installer.addon_path:
            console.print(f"\n[dim]Addon directory: {installer.addon_path}[/dim]")
        
    finally:
        db.close()

@app.command()
def search(query: str, limit: int = typer.Option(10, "--limit", "-n")):
    """Search for addons by name or description"""
    db = get_db()
    
    try:
        addons = db.get_addons()
        query_lower = query.lower()
        
        # Score and sort results
        results = []
        for addon in addons:
            score = 0
            name_lower = addon['name'].lower()
            desc_lower = addon.get('description', '').lower()
            
            # Exact name match
            if name_lower == query_lower:
                score = 100
            # Name starts with query
            elif name_lower.startswith(query_lower):
                score = 80
            # Query in name
            elif query_lower in name_lower:
                score = 60
            # Query in description
            elif query_lower in desc_lower:
                score = 40
            
            if score > 0:
                results.append((score, addon))
        
        # Sort by score
        results.sort(key=lambda x: x[0], reverse=True)
        
        if not results:
            console.print(f"[yellow]No results found for '{query}'[/yellow]")
            raise typer.Exit(0)
        
        # Display results
        table = Table(title=f"Search Results for '{query}'")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")
        table.add_column("Score", justify="right", style="green")
        
        for score, addon in results[:limit]:
            desc = addon.get('description', '')[:50] + "..." if len(addon.get('description', '')) > 50 else addon.get('description', '')
            table.add_row(addon['name'], desc, str(score))
        
        console.print(table)
        
        if len(results) > limit:
            console.print(f"\n[dim]Showing top {limit} of {len(results)} results.[/dim]")
        
    finally:
        db.close()

@app.command()
def stats():
    """Show database statistics"""
    db = get_db()
    
    try:
        addons = db.get_addons()
        
        # Calculate statistics
        total = len(addons)
        
        # Count by tags
        tag_counts = {}
        for addon in addons:
            for tag in addon.get('tags', []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        
        # Count by host
        host_counts = {}
        for addon in addons:
            url = addon.get('repo_url', '')
            if 'github.com' in url:
                host = 'GitHub'
            elif 'gitlab.com' in url:
                host = 'GitLab'
            elif 'bitbucket.org' in url:
                host = 'BitBucket'
            else:
                host = 'Other'
            host_counts[host] = host_counts.get(host, 0) + 1
        
        # Create statistics panel
        stats_content = f"""[bold]Database Statistics[/bold]

[cyan]Total Addons:[/cyan] {total}

[cyan]By Tag:[/cyan]"""
        
        for tag, count in sorted(tag_counts.items()):
            stats_content += f"\n  • {tag}: {count}"
        
        stats_content += f"\n\n[cyan]By Host:[/cyan]"
        for host, count in sorted(host_counts.items()):
            stats_content += f"\n  • {host}: {count}"
        
        panel = Panel(stats_content, title="Carapace Statistics", border_style="cyan")
        console.print(panel)
        
    finally:
        db.close()

@app.command()
def tui(ctx: typer.Context):
    """Launch the Terminal User Interface"""
    from carapace.tui import run_tui
    run_tui()

@app.command()
def path(
    set_path: Optional[Path] = typer.Option(None, "--set", "-s", help="Set WoW installation path"),
    auto_detect: bool = typer.Option(False, "--detect", "-d", help="Auto-detect WoW installation")
):
    """Check or set TurtleWoW installation path"""
    db = get_db()
    detector = PathDetector()
    
    try:
        if set_path:
            # Manual path setting
            if detector.set_wow_path(set_path):
                addon_path = detector.ensure_addon_directory(set_path)
                if addon_path:
                    db.set_setting("wow_path", str(set_path))
                    db.set_setting("addon_path", str(addon_path))
                    console.print(f"[green][OK][/green] WoW path set to: {set_path}")
                    console.print(f"[green][OK][/green] AddOns folder: {addon_path}")
                else:
                    console.print(f"[red]Error:[/red] Could not create AddOns directory")
            else:
                console.print(f"[red]Error:[/red] Invalid path - TurtleWoW.exe not found")
            return
        
        if auto_detect:
            # Auto-detect path
            console.print("Detecting TurtleWoW installation...")
            wow_path = detector.detect_wow_path()
            
            if wow_path:
                addon_path = detector.ensure_addon_directory(wow_path)
                if addon_path:
                    db.set_setting("wow_path", str(wow_path))
                    db.set_setting("addon_path", str(addon_path))
                    console.print(f"[green][OK][/green] Found TurtleWoW at: {wow_path}")
                    console.print(f"[green][OK][/green] AddOns folder: {addon_path}")
                else:
                    console.print(f"[yellow]Warning:[/yellow] Could not create AddOns directory")
            else:
                console.print("[yellow]Could not auto-detect TurtleWoW installation[/yellow]")
                console.print("Please set manually with: carapace path --set <path>")
            return
        
        # Show current path
        stored_path = db.get_setting("wow_path")
        stored_addon_path = db.get_setting("addon_path")
        
        if stored_path:
            path_obj = Path(stored_path)
            if detector._validate_wow_directory(path_obj):
                console.print(f"[cyan]WoW Path:[/cyan] {stored_path}")
                console.print(f"[cyan]AddOns Path:[/cyan] {stored_addon_path or 'Not set'}")
                
                # Check if directories exist
                if not path_obj.exists():
                    console.print("[yellow]Warning:[/yellow] Path no longer exists")
                elif stored_addon_path and not Path(stored_addon_path).exists():
                    console.print("[yellow]Warning:[/yellow] AddOns directory missing")
            else:
                console.print(f"[yellow]Stored path invalid:[/yellow] {stored_path}")
                console.print("Run 'carapace path --detect' to auto-detect")
        else:
            console.print("[yellow]No WoW path configured[/yellow]")
            console.print("\nOptions:")
            console.print("  Auto-detect: carapace path --detect")
            console.print("  Set manually: carapace path --set <path>")
            
            # Try detection and show if found
            wow_path = detector.detect_wow_path()
            if wow_path:
                console.print(f"\n[dim]Detected at: {wow_path}[/dim]")
                console.print("[dim]Run 'carapace path --detect' to use this path[/dim]")
    
    finally:
        db.close()

@app.command()
def install(addon_name: str):
    """Install an addon"""
    db = get_db()
    installer = AddonInstaller(db)
    
    try:
        # Check if already installed
        if installer.is_installed(addon_name):
            console.print(f"[yellow]{addon_name} is already installed[/yellow]")
            console.print("[dim]Use 'carapace update' to update it[/dim]")
            return
        
        # Get addon info from database
        addons = db.get_addons()
        addon = None
        for a in addons:
            if a['name'].lower() == addon_name.lower():
                addon = a
                break
        
        if not addon:
            console.print(f"[red]Addon not found: {addon_name}[/red]")
            console.print("[dim]Use 'carapace search' to find addons[/dim]")
            raise typer.Exit(1)
        
        if not addon.get('repo_url'):
            console.print(f"[red]No repository URL for {addon_name}[/red]")
            raise typer.Exit(1)
        
        console.print(f"Installing {addon['name']}...")
        console.print(f"[dim]Repository: {addon['repo_url']}[/dim]")
        
        # Install
        with console.status("[cyan]Downloading and installing...[/cyan]"):
            success = installer.install_addon(addon['name'], addon['repo_url'])
        
        if success:
            console.print(f"[green][OK][/green] Successfully installed {addon['name']}")
        else:
            console.print(f"[red]Failed to install {addon['name']}[/red]")
            console.print("[dim]Check logs for details[/dim]")
            raise typer.Exit(1)
    
    finally:
        db.close()

@app.command()
def remove(addon_name: str, 
          confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation")):
    """Remove an installed addon"""
    db = get_db()
    installer = AddonInstaller(db)
    
    try:
        # Check if installed
        if not installer.is_installed(addon_name):
            console.print(f"[yellow]{addon_name} is not installed[/yellow]")
            return
        
        # Get installed info
        installed = installer.get_installed_addons()
        addon_info = installed.get(addon_name.lower())
        
        if not confirm:
            console.print(f"Remove {addon_info['name']}?")
            console.print(f"[dim]Path: {addon_info['path']}[/dim]")
            response = typer.confirm("Are you sure?")
            if not response:
                console.print("[yellow]Cancelled[/yellow]")
                return
        
        # Remove
        console.print(f"Removing {addon_info['name']}...")
        success = installer.remove_addon(addon_info['name'])
        
        if success:
            console.print(f"[green][OK][/green] Successfully removed {addon_info['name']}")
        else:
            console.print(f"[red]Failed to remove {addon_info['name']}[/red]")
            raise typer.Exit(1)
    
    finally:
        db.close()

@app.command()
def update(
    addon_name: Optional[str] = typer.Argument(None, help="Addon to update (or all)"),
    check_only: bool = typer.Option(False, "--check", "-c", help="Only check for updates"),
    all_addons: bool = typer.Option(False, "--all", "-a", help="Update all addons")
):
    """Update installed addons"""
    db = get_db()
    installer = AddonInstaller(db)
    
    try:
        if check_only:
            # Check for updates
            console.print("Checking for updates...")
            with console.status("[cyan]Fetching update information...[/cyan]"):
                updates = installer.check_for_updates()
            
            if not updates:
                console.print("[green]All addons are up to date![/green]")
                return
            
            # Show available updates
            table = Table(title=f"Available Updates ({len(updates)} addons)")
            table.add_column("Addon", style="cyan")
            table.add_column("Current Version", style="yellow")
            table.add_column("Commits Behind", style="red")
            
            for update in updates:
                table.add_row(
                    update['name'],
                    update['current_version'],
                    str(update['commits_behind'])
                )
            
            console.print(table)
            console.print("\n[dim]Run 'carapace update <addon>' or 'carapace update --all' to update[/dim]")
            return
        
        if all_addons:
            # Update all addons with updates
            console.print("Checking for updates...")
            updates = installer.check_for_updates()
            
            if not updates:
                console.print("[green]All addons are up to date![/green]")
                return
            
            console.print(f"Found {len(updates)} addon(s) with updates")
            
            for update in updates:
                console.print(f"\nUpdating {update['name']}...")
                success = installer.update_addon(update['name'])
                if success:
                    console.print(f"[green][OK][/green] Updated {update['name']}")
                else:
                    console.print(f"[yellow]Failed to update {update['name']}[/yellow]")
            
            return
        
        if addon_name:
            # Update specific addon
            if not installer.is_installed(addon_name):
                console.print(f"[yellow]{addon_name} is not installed[/yellow]")
                return
            
            console.print(f"Updating {addon_name}...")
            with console.status("[cyan]Updating...[/cyan]"):
                success = installer.update_addon(addon_name)
            
            if success:
                console.print(f"[green][OK][/green] Successfully updated {addon_name}")
            else:
                console.print(f"[red]Failed to update {addon_name}[/red]")
                raise typer.Exit(1)
        else:
            # No addon specified, show help
            console.print("Usage:")
            console.print("  carapace update --check       # Check for updates")
            console.print("  carapace update <addon>       # Update specific addon")
            console.print("  carapace update --all         # Update all addons")
    
    finally:
        db.close()

@app.command()
def version():
    """Show version information"""
    console.print(f"[bold cyan]Carapace[/bold cyan] v{__version__}")
    console.print("TurtleWoW Addon Manager")
    console.print("https://github.com/mikl0s/carapace")
    
    # Check for app updates
    from carapace.app_updater import check_for_app_updates
    update_info = check_for_app_updates()
    if update_info:
        console.print(f"\n[yellow]Update available: v{update_info['new_version']}[/yellow]")
        console.print(f"Run 'carapace self-update' to update")

@app.command()
def self_update(
    check_only: bool = typer.Option(False, "--check", "-c", help="Only check for updates, don't install")
):
    """Check for and install Carapace application updates"""
    from carapace.app_updater import ApplicationUpdater
    
    console.print(f"[cyan]Current version:[/cyan] v{__version__}")
    console.print("[cyan]Checking for updates...[/cyan]")
    
    updater = ApplicationUpdater()
    update_available, release = updater.check_for_updates()
    
    if not update_available:
        console.print("[green]✓ Carapace is up to date![/green]")
        return
    
    if not release:
        console.print("[red]✗ Could not check for updates[/red]")
        raise typer.Exit(1)
    
    # Show update information
    console.print(f"\n[green]Update available![/green]")
    console.print(f"[cyan]New version:[/cyan] {release['tag_name']}")
    console.print(f"[cyan]Release date:[/cyan] {release['published_at'][:10]}")
    
    if release.get('body'):
        console.print("\n[cyan]Release notes:[/cyan]")
        # Show first 5 lines of release notes
        lines = release['body'].split('\n')[:5]
        for line in lines:
            if line.strip():
                console.print(f"  {line}")
        if len(release['body'].split('\n')) > 5:
            console.print("  ...")
    
    console.print(f"\n[dim]Full release: {release['html_url']}[/dim]")
    
    if check_only:
        return
    
    # Check if running from source
    if not getattr(sys, 'frozen', False):
        console.print("\n[yellow]Note: Running from source code.[/yellow]")
        console.print("Please download the latest release manually from:")
        console.print(f"[link]{release['html_url']}[/link]")
        return
    
    # Confirm update
    if not typer.confirm("\nDo you want to install this update?"):
        console.print("[yellow]Update cancelled[/yellow]")
        return
    
    # Perform update
    console.print("\n[cyan]Downloading update...[/cyan]")
    
    with console.status("[cyan]Installing update...[/cyan]"):
        success = updater.perform_update(release)
    
    if success:
        console.print("[green]✓ Update downloaded and installed![/green]")
        console.print("[yellow]Carapace will restart with the new version...[/yellow]")
        raise typer.Exit(0)
    else:
        console.print("[red]✗ Failed to install update[/red]")
        console.print("Please download manually from:")
        console.print(f"[link]{release['html_url']}[/link]")
        raise typer.Exit(1)

@app.command()
def update_db(
    force: bool = typer.Option(False, "--force", "-f", help="Force download even if up to date"),
    check_only: bool = typer.Option(False, "--check", "-c", help="Only check for updates, don't download")
):
    """Check for and download database updates from GitHub"""
    from carapace.updater import DatabaseUpdater
    from carapace.db import Database
    
    # Get database path
    db = Database()
    db_path = Path(db.db_path)
    db.close()
    
    updater = DatabaseUpdater(db_path)
    
    # Show current database info
    info = updater.get_database_info()
    if info['exists']:
        console.print(f"[cyan]Current database:[/cyan]")
        console.print(f"  Version: {info.get('version', 'unknown')}")
        console.print(f"  Addons: {info.get('addon_count', 'unknown')}")
        console.print(f"  Updated: {info.get('updated', 'unknown')}")
    else:
        console.print("[yellow]No local database found[/yellow]")
    
    console.print()
    
    # Check for updates
    console.print("[cyan]Checking for updates...[/cyan]")
    update_available, remote_manifest = updater.check_for_updates()
    
    if remote_manifest:
        console.print(f"[cyan]Remote database:[/cyan]")
        console.print(f"  Version: {remote_manifest.get('version', 'unknown')}")
        console.print(f"  Addons: {remote_manifest.get('addon_count', 'unknown')}")
        console.print(f"  Updated: {remote_manifest.get('updated', 'unknown')}")
        console.print(f"  Size: {remote_manifest.get('file_size', 0) / 1024:.1f} KB")
    
    if check_only:
        if update_available:
            console.print("\n[green]✓ Update available![/green]")
        else:
            console.print("\n[green]✓ Database is up to date[/green]")
        return
    
    if not update_available and not force:
        console.print("\n[green]✓ Database is up to date[/green]")
        return
    
    if force:
        console.print("\n[yellow]Forcing database download...[/yellow]")
    else:
        console.print("\n[yellow]Downloading update...[/yellow]")
    
    # Download the update
    if force and remote_manifest:
        checksum = remote_manifest.get('checksum')
        success = updater.download_database(checksum)
        if success:
            with open(updater.manifest_path, 'w') as f:
                import json
                json.dump(remote_manifest, f, indent=2)
    else:
        success = updater.update_database()
    
    if success:
        console.print("[green]✓ Database updated successfully![/green]")
    else:
        console.print("[red]✗ Failed to update database[/red]")

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging")
):
    """Carapace - TurtleWoW Addon Manager"""
    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    # If no command was provided, show help
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit(0)

if __name__ == "__main__":
    app()