"""
Terminal User Interface for Carapace using Textual
"""

import os
import logging
from datetime import datetime

# Debug flag - set to False for production builds
DEBUG_ENABLED = os.environ.get('CARAPACE_DEBUG', 'false').lower() == 'true'

if DEBUG_ENABLED:
    # Set up debug logging to file ONLY - no console output
    log_file = f'tui_debug_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
    
    # Clear any existing handlers to ensure no console output
    root_logger = logging.getLogger()
    root_logger.handlers = []
    
    # Add only file handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    root_logger.addHandler(file_handler)
    root_logger.setLevel(logging.DEBUG)
    
    # Ensure no console output
    logging.getLogger().handlers = [h for h in logging.getLogger().handlers if not isinstance(h, logging.StreamHandler)]
    
    logger = logging.getLogger(__name__)
    logger.info(f"Starting TUI debug log in {log_file}")
else:
    # Production mode - disable all logging
    logging.disable(logging.CRITICAL)
    logger = logging.getLogger(__name__)

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer, Center
from textual.widgets import Header, Footer, Static, Button, DataTable, Input, Label, LoadingIndicator, TabbedContent, TabPane, ProgressBar, TextArea
from textual.binding import Binding
from textual.screen import Screen
from textual.reactive import reactive
from textual import work
from textual.message import Message
from rich.text import Text
from datetime import datetime
from pathlib import Path
import asyncio
import json

from carapace.db import Database
from carapace.installer import AddonInstaller
from carapace.parser import WikiParser
from carapace.paths import PathDetector


from textual.screen import ModalScreen, Screen

class InstallConfirmModal(ModalScreen):
    """Confirmation dialog for addon installation"""
    
    DEFAULT_CSS = """
    InstallConfirmModal {
        align: center middle;
        background: transparent;
    }
    
    #confirm-container {
        width: 50;
        height: 13;
        background: $panel;
        border: thick $primary;
        padding: 1;
    }
    
    #confirm-title {
        text-style: bold;
        color: $text;
        text-align: center;
        margin-top: 1;
        margin-bottom: 1;
    }
    
    #confirm-message {
        text-align: center;
        color: $text;
        margin-bottom: 1;
    }
    
    #button-container {
        align: center middle;
        height: 3;
    }
    
    #yes-button {
        margin: 0 1;
        min-width: 9;
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    
    #no-button {
        margin: 0 1;
        min-width: 8;
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    
    #yes-button:focus {
        background: $primary;
        color: $background;
    }
    
    #no-button:focus {
        background: $primary;
        color: $background;
    }
    """
    
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
    ]
    
    def __init__(self, addon_name: str):
        super().__init__()
        self.addon_name = addon_name
        self.result = False
    
    def compose(self) -> ComposeResult:
        # The actual modal
        with Container(id="confirm-container"):
            with Vertical():
                yield Static("[bold]Install Addon?[/bold]", id="confirm-title")
                yield Static(f"Do you want to install [cyan]{self.addon_name}[/cyan]?", id="confirm-message")
                
                with Horizontal(id="button-container"):
                    yield Button("Yes", id="yes-button")
                    yield Button("No", id="no-button")
    
    def on_mount(self) -> None:
        """Focus on Yes button by default"""
        self.query_one("#yes-button", Button).focus()
    
    def on_key(self, event) -> None:
        """Handle arrow key navigation and enter key"""
        if event.key == "left":
            self.query_one("#yes-button", Button).focus()
            event.stop()
        elif event.key == "right":
            self.query_one("#no-button", Button).focus()
            event.stop()
        elif event.key == "enter":
            # Check which button is focused and trigger it
            focused = self.focused
            if focused and isinstance(focused, Button):
                if focused.id == "yes-button":
                    self.action_confirm()
                elif focused.id == "no-button":
                    self.action_cancel()
            # Always stop enter from bubbling to prevent double-triggering
            event.stop()
            event.prevent_default()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses"""
        if event.button.id == "yes-button":
            self.action_confirm()
        elif event.button.id == "no-button":
            self.action_cancel()
    
    def action_confirm(self) -> None:
        """Confirm installation"""
        self.result = True
        self.dismiss(True)
    
    def action_cancel(self) -> None:
        """Cancel installation"""
        self.result = False
        self.dismiss(False)


class EditAddonModal(ModalScreen):
    """Modal for editing addon details"""
    
    DEFAULT_CSS = """
    EditAddonModal {
        align: center middle;
        background: transparent;
    }
    
    #edit-container {
        width: 80;
        height: auto;
        max-height: 40;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
    }
    
    #edit-title {
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    
    .edit-field {
        margin-bottom: 1;
    }
    
    .field-label {
        color: $text;
        text-style: bold;
        margin-bottom: 0;
    }
    
    Input {
        width: 100%;
        margin-top: 0;
        background: $boost;
        color: $text;
    }
    
    #button-container {
        align: center middle;
        margin-top: 1;
    }
    
    Button {
        margin: 0 1;
    }
    """
    
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]
    
    def __init__(self, addon_name: str, addon_data: dict):
        super().__init__()
        self.addon_name = addon_name
        self.addon_data = addon_data
        self.db = None
    
    def compose(self) -> ComposeResult:
        # The actual modal
        with Container(id="edit-container"):
            with Vertical():
                yield Static(f"[bold]Edit: {self.addon_name}[/bold]", id="edit-title")
                
                # Name field
                yield Static("[bold cyan]Name:[/bold cyan]", classes="field-label")
                yield Input(value=self.addon_name, id="edit-name")
                
                # Description field
                yield Static("[bold cyan]Description:[/bold cyan]", classes="field-label")
                desc = self.addon_data.get('description', '')
                yield Input(value=desc, placeholder="Enter description", id="edit-description")
                
                # Repository URL field
                yield Static("[bold cyan]Repository URL:[/bold cyan]", classes="field-label")
                repo_url = self.addon_data.get('repo_url', '')
                yield Input(value=repo_url, placeholder="https://github.com/user/repo", id="edit-repo-url")
                
                # Override URL field
                yield Static("[bold cyan]Override URL:[/bold cyan] (use if main URL is incorrect)", classes="field-label")
                override_url = self.addon_data.get('override_url', '')
                # Smart display: If override_url equals repo_url, show as empty
                # This indicates protection is active but was auto-set
                if override_url == repo_url:
                    override_url = ''
                yield Input(value=override_url, placeholder="Leave empty to use repository URL", id="edit-override-url")
                
                # Buttons
                with Horizontal(id="button-container"):
                    yield Button("Save (Ctrl+S)", variant="primary", id="save-button")
                    yield Button("Cancel (ESC)", variant="default", id="cancel-button")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses"""
        if event.button.id == "save-button":
            self.action_save()
        elif event.button.id == "cancel-button":
            self.action_cancel()
    
    def action_save(self) -> None:
        """Save the edited addon details"""
        from carapace.db import Database
        
        try:
            # Get values from inputs
            new_name = self.query_one("#edit-name", Input).value
            description = self.query_one("#edit-description", Input).value
            repo_url = self.query_one("#edit-repo-url", Input).value
            override_url = self.query_one("#edit-override-url", Input).value
            
            # Update database
            db = Database()
            cursor = db.conn.cursor()
            
            # Check if anything was manually edited
            cursor.execute("""
                SELECT name, description, repo_url, override_url 
                FROM addons WHERE name = ?
            """, (self.addon_name,))
            original = cursor.fetchone()
            
            # Smart protection: If user edited name or description but didn't set override,
            # automatically set override_url = repo_url to protect from wiki sync
            if original:
                changed = (new_name != original['name'] or 
                          description != (original['description'] or '') or
                          repo_url != (original['repo_url'] or ''))
                
                # If override is empty but something changed, set override = repo
                if changed and not override_url:
                    override_url = repo_url
                # If override equals repo_url, store it as NULL (to save space)
                elif override_url == repo_url:
                    override_url = repo_url  # Still store it to maintain protection
            
            # If name changed, update both addons and installed tables
            if new_name != self.addon_name:
                # Update addon name
                cursor.execute("""
                    UPDATE addons 
                    SET name = ?, description = ?, repo_url = ?, override_url = ?
                    WHERE name = ?
                """, (new_name, description, repo_url, override_url if override_url else None, self.addon_name))
                
                # Update installed table if installed
                cursor.execute("""
                    UPDATE installed 
                    SET name = ?
                    WHERE name = ? AND deleted_at_utc IS NULL
                """, (new_name, self.addon_name))
            else:
                # Just update other fields
                cursor.execute("""
                    UPDATE addons 
                    SET description = ?, repo_url = ?, override_url = ?
                    WHERE name = ?
                """, (description, repo_url, override_url if override_url else None, self.addon_name))
            
            db.conn.commit()
            db.close()
            
            self.app.notify(f"Saved changes to {new_name}")
            self.app.pop_screen()
            
            # Refresh the addon table
            self.app.load_all_addons()
            
        except Exception as e:
            self.app.notify(f"Failed to save: {e}", severity="error")
    
    def action_cancel(self) -> None:
        """Cancel editing"""
        self.app.pop_screen()


class AddonDetailsScreen(Screen):
    """Beautiful full-screen addon details view"""
    
    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("q", "dismiss", "Back"),
        ("b", "dismiss", "Back"),
        ("i", "install", "Install"),
        ("e", "edit", "Edit"),
    ]
    
    DEFAULT_CSS = """
    AddonDetailsScreen {
        background: $surface;
    }
    
    #details-header {
        dock: top;
        height: 5;
        background: $boost;
        border-bottom: solid $primary;
        padding: 1 2;
    }
    
    #addon-name {
        text-style: bold;
        text-align: center;
        color: $text;
    }
    
    #addon-status {
        text-align: center;
        margin-top: 1;
    }
    
    #details-content {
        padding: 2 4;
        overflow-y: auto;
    }
    
    .detail-section {
        margin-bottom: 2;
        background: $boost;
        border: tall $primary 30%;
        padding: 1 2;
    }
    
    .section-title {
        text-style: bold underline;
        color: $primary;
        margin-bottom: 1;
    }
    
    .detail-field {
        margin: 1 0;
        color: $text;
    }
    
    .field-label {
        color: $primary;
        text-style: bold;
    }
    
    .tag-badge {
        background: $primary;
        color: $surface;
        padding: 0 1;
        margin: 0 1;
    }
    
    #details-footer {
        dock: bottom;
        height: 3;
        background: $boost;
        border-top: solid $primary;
        padding: 0 2;
        text-align: center;
    }
    
    .url-link {
        color: $accent;
        text-style: underline;
    }
    """
    
    def __init__(self, addon_name: str, addon_data: dict):
        super().__init__()
        self.addon_name = addon_name
        self.addon_data = addon_data
    
    def compose(self) -> ComposeResult:
        # Header with addon name and status
        with Container(id="details-header"):
            yield Static(f"✨ {self.addon_name} ✨", id="addon-name")
            
            status = self.addon_data.get('status', 'available')
            installed = self.addon_data.get('installed', False)
            
            if installed:
                status_text = "[green]● INSTALLED[/green]"
            elif status == 'available':
                status_text = "[cyan]◯ AVAILABLE[/cyan]"
            elif status == 'broken':
                status_text = "[red]✗ BROKEN[/red]"
            else:
                status_text = f"[yellow]◐ {status.upper()}[/yellow]"
            
            yield Static(status_text, id="addon-status")
        
        # Main content
        with ScrollableContainer(id="details-content"):
            # Description section
            with Container(classes="detail-section"):
                yield Static("📝 Description", classes="section-title")
                desc = self.addon_data.get('description', 'No description available')
                yield Static(desc, classes="detail-field")
            
            # URLs section
            urls_exist = self.addon_data.get('url') or self.addon_data.get('repo_url')
            if urls_exist:
                with Container(classes="detail-section"):
                    yield Static("🔗 Links", classes="section-title")
                    
                    url = self.addon_data.get('url')
                    if url:
                        yield Static(f"[bold]Homepage:[/bold] {url}", classes="detail-field")
                    
                    repo = self.addon_data.get('repo_url')
                    if repo:
                        yield Static(f"[bold]Repository:[/bold] {repo}", classes="detail-field")
                    
                    override = self.addon_data.get('override_url')
                    if override:
                        yield Static(f"[bold]Override:[/bold] {override}", classes="detail-field")
            
            # Tags section
            tags = self.addon_data.get('tags', [])
            if tags:
                with Container(classes="detail-section"):
                    yield Static("🏷️ Tags", classes="section-title")
                    with Horizontal():
                        for tag in tags:
                            # Special formatting for certain tags
                            if tag == 'recommended':
                                yield Static(f"🐢 {tag}", classes="tag-badge")
                            elif tag == 'featured':
                                yield Static(f"💎 {tag}", classes="tag-badge")
                            elif tag == 'leveling':
                                yield Static(f"📈 {tag}", classes="tag-badge")
                            elif tag == 'endgame':
                                yield Static(f"⚔️ {tag}", classes="tag-badge")
                            elif tag == 'superwow_required':
                                yield Static(f"⚠️ {tag}", classes="tag-badge")
                            else:
                                yield Static(tag, classes="tag-badge")
            
            # Installation info section (if installed)
            if installed:
                with Container(classes="detail-section"):
                    yield Static("💾 Installation Info", classes="section-title")
                    version = self.addon_data.get('version', 'Unknown')
                    yield Static(f"[bold]Version:[/bold] {version}", classes="detail-field")
                    
                    path = self.addon_data.get('path')
                    if path:
                        yield Static(f"[bold]Location:[/bold] {path}", classes="detail-field")
        
        # Footer with actions hint
        with Container(id="details-footer"):
            yield Static("[dim]Press [bold]I[/bold] to Install • [bold]E[/bold] to Edit • [bold]ESC[/bold] to go back[/dim]")
    
    def action_dismiss(self) -> None:
        """Go back to main screen"""
        self.app.pop_screen()
    
    def action_install(self) -> None:
        """Install this addon"""
        self.app.pop_screen()
        self.app.install_selected()
    
    def action_edit(self) -> None:
        """Edit this addon"""
        self.app.pop_screen()
        self.app.edit_addon()


class CarapaceTUI(App):
    """Main TUI application for Carapace"""
    
    TITLE = "Carapace - TurtleWoW Addon Manager"
    # Theme is set via command line or environment variable
    
    # Disable command palette
    ENABLE_COMMAND_PALETTE = False
    
    def __init__(self):
        super().__init__()
        # Preserve cursor positions for each tab
        self.all_table_cursor = None
        self.installed_table_cursor = None
    
    CSS = """
    Screen {
        background: $surface;
        padding: 0;
        margin: 0;
    }
    
    ModalScreen {
        background: transparent;
    }
    
    #search-row, #search-row-installed {
        height: 3;
        margin: 0 0 1 0;
    }
    
    #search-all, #search-installed {
        width: 30%;
        min-width: 20;
        height: 3;
        background: $boost;
        border: none;
        margin: 0 1;
        padding: 1 1;
    }
    
    DataTable {
        height: 1fr;
        scrollbar-size: 1 1;
    }
    
    DataTable > .datatable--header {
        text-style: bold;
        background: $primary 20%;
        color: $text;
        text-align: center;
    }
    
    DataTable > .datatable--cursor {
        background: $primary 40%;
        color: $text;
        text-style: bold;
    }
    
    DataTable:focus > .datatable--cursor {
        background: $primary 60%;
    }
    
    DataTable > .datatable--odd-row {
        background: $boost;
    }
    
    DataTable > .datatable--even-row {
        background: $surface;
    }
    
    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary 20%;
        color: $text;
        padding: 0 1;
    }
    
    #addon-counter, #installed-counter {
        width: auto;
        min-width: 10;
        height: 3;
        padding: 1;
        text-align: center;
        color: $text;
        background: $boost;
        border: none;
        margin: 0 1;
    }
    
    #action-bar, #action-bar-installed {
        width: 1fr;
        height: 3;
        padding: 0 1;
        text-align: left;
        background: $boost;
        border: none;
        color: $text;
        margin: 0 1;
        padding-left: 1;
        padding-right: 1;
    }
    
    /* Removed menu-bar - integrated into search row */
    
    TabbedContent {
        height: 1fr;
    }
    
    TabPane {
        padding: 0 1;
    }
    
    TabbedContent ContentSwitcher {
        padding: 0;
        height: 1fr;
    }
    """
    
    BINDINGS = [
        Binding("escape", "quit", "Exit Carapace"),
        Binding("f1", "show_help", "Help"),
        Binding("f2", "install", "Install"),
        Binding("f3", "uninstall", "Uninstall"),
        Binding("f4", "toggle_enable", "Enable/Disable Addon"),
        Binding("f5", "update", "Update Addon"),
        Binding("f6", "mark_all", "Mark All"),
        Binding("f7", "clear_marks", "Unmark All"),
        Binding("f8", "sync", "Update Addons List DB from GitHub"),
        Binding("f9", "edit", "Edit Addon"),
        Binding("f11", "export_list", "Export List"),
        Binding("f12", "update_all", "Update Addons DB + auto-update all installed"),
        Binding("space", "mark", "Mark/Unmark"),
        Binding("tab", "toggle_tab", "Tab", show=False),
        Binding("enter", "quick_install", "Quick Install", show=False),
        Binding("ctrl+f8", "debug_filter_urls", "Debug URLs", show=False),  # Hidden debug function
    ]
    
    def __init__(self):
        super().__init__()
        self.parser = WikiParser()
        self.addon_path = PathDetector().get_addon_path()
        self.all_addons = []
        self.installed_addons = {}
        self.current_filter = ""
        self.selected_addon = None
        self.marked_addons = set()  # For multiple selection
        self.debug_url_filter = False  # Hidden filter for problematic URLs
    
    def compose(self) -> ComposeResult:
        logger.debug("Composing TUI widgets")
        yield Header(show_clock=True)
        
        with TabbedContent(initial="all-tab"):
            with TabPane("All Addons", id="all-tab"):
                yield Horizontal(
                    Input(placeholder="Type to search...", id="search-all"),
                    Static("0 of 0", id="addon-counter"),
                    Static("", id="action-bar"),  # Will be updated with proper theme colors
                    id="search-row"
                )
                yield DataTable(id="all-table", zebra_stripes=True, cursor_type="row")
            
            with TabPane("Installed", id="installed-tab"):
                yield Horizontal(
                    Input(placeholder="Type to search...", id="search-installed"),
                    Static("0 of 0", id="installed-counter"),
                    Static("", id="action-bar-installed"),  # Will be updated with proper theme colors
                    id="search-row-installed"
                )
                yield DataTable(id="installed-table", zebra_stripes=True, cursor_type="row")
        
        # No footer or status bar to maximize space
        logger.debug("Compose complete")
    
    
    def format_tag_icons(self, tags: list):
        """Convert tags to colored icon representation - returns Rich Text object"""
        from rich.text import Text
        icons = Text()
        
        for tag in tags:
            if tag == 'recommended':
                icons.append("🐢", style="green")  # Turtle for TurtleWoW recommended
            elif tag == 'featured':
                icons.append("♦", style="bold cyan")  # Diamond
            elif tag == 'leveling':
                icons.append("↑", style="yellow")  # Up arrow
            elif tag == 'endgame':
                icons.append("⚔", style="red")  # Swords
            elif tag == 'superwow_required':
                icons.append("!", style="bold red")  # Exclamation
            elif tag == 'superwow_features':
                icons.append("S", style="magenta")  # S for SuperWoW
            
            if icons.plain:  # Only add space if we have content
                icons.append(" ")
        
        return icons
    
    
    def format_action_bar(self, tab="all") -> str:
        """Format the action bar with theme-appropriate colors using Rich Text"""
        from rich.text import Text
        
        # Create a Rich Text object for proper styling
        text = Text()
        
        if tab == "all":
            # Line 1: F1 Help           F2 Install         F3 Uninstall      F4 Enable/Disable Addon
            text.append(" ", style="dim")  # Left padding
            text.append("F", style="bold blue")
            text.append("1", style="bold")
            text.append(" Help           ", style="dim")
            text.append("F", style="bold blue")
            text.append("2", style="bold")
            text.append(" Install         ", style="dim")
            text.append("F", style="bold blue")
            text.append("3", style="bold")
            text.append(" Uninstall      ", style="dim")
            text.append("F", style="bold blue")
            text.append("4", style="bold")
            text.append(" Enable/Disable Addon\n", style="dim")
            
            # Line 2: F5 Update Addon   F6 Mark All        F7 Unmark All     F8 Update Addons List DB from GitHub
            text.append(" ", style="dim")  # Left padding
            text.append("F", style="bold blue")
            text.append("5", style="bold")
            text.append(" Update Addon   ", style="dim")
            text.append("F", style="bold blue")
            text.append("6", style="bold")
            text.append(" Mark All        ", style="dim")
            text.append("F", style="bold blue")
            text.append("7", style="bold")
            text.append(" Unmark All     ", style="dim")
            text.append("F", style="bold blue")
            text.append("8", style="bold")
            text.append(" Update Addons List DB from GitHub\n", style="dim")
            
            # Line 3: F9 Edit Addon    ESC Exit Carapace  F12 Update Addons DB + auto-update all installed Addons
            text.append(" ", style="dim")  # Left padding
            text.append("F", style="bold blue")
            text.append("9", style="bold")
            text.append(" Edit Addon    ", style="dim")
            text.append("E", style="bold blue")
            text.append("SC", style="bold")
            text.append(" Exit Carapace  ", style="dim")
            text.append("F", style="bold blue")
            text.append("12", style="bold")
            text.append(" Update Addons DB + auto-update all installed Addons", style="dim")
        else:  # installed tab
            # First line (top)
            text.append(" ", style="dim")  # Left padding
            text.append("F", style="bold blue")
            text.append("1", style="bold")
            text.append(" Help           ", style="dim")
            text.append("F", style="bold blue")
            text.append("3", style="bold")
            text.append(" Uninstall      ", style="dim")
            text.append(" F", style="bold blue")
            text.append("4", style="bold")
            text.append(" Enable/Disable  ", style="dim")
            text.append("F", style="bold blue")
            text.append("5", style="bold")
            text.append(" Update Addon\n", style="dim")
            
            # Empty line in between
            text.append("\n")
            
            # Third line (bottom)
            text.append(" ", style="dim")  # Left padding
            text.append("F", style="bold blue")
            text.append("6", style="bold")
            text.append(" Mark All       ", style="dim")
            text.append("F", style="bold blue")
            text.append("7", style="bold")
            text.append(" Unmark All      ", style="dim")
            text.append("F", style="bold blue")
            text.append("12", style="bold")
            text.append(" Update All     ", style="dim")
            text.append("E", style="bold blue")
            text.append("SC", style="bold")
            text.append(" Exit", style="dim")
        
        return text
    
    @work(exclusive=True, thread=True)
    def check_for_app_updates(self) -> None:
        """Check for application updates in background"""
        try:
            from carapace.app_updater import check_for_app_updates
            update_info = check_for_app_updates()
            if update_info:
                msg = f"Update available: v{update_info['new_version']} (current: v{update_info['current_version']})"
                self.call_from_thread(self.notify, msg, severity="information", timeout=10)
        except Exception as e:
            logger.debug(f"Could not check for app updates: {e}")
    
    def on_mount(self) -> None:
        """Called when app is mounted"""
        # Set the Tokyo Night theme
        self.theme = "tokyo-night"
        logger.info("Theme set to tokyo-night")
        
        # Update action bars with proper theme colors
        try:
            action_bar = self.query_one("#action-bar", Static)
            action_bar.update(self.format_action_bar("all"))
        except:
            pass
        
        # Check for application updates in background (non-blocking)
        self.check_for_app_updates()
        
        try:
            action_bar_installed = self.query_one("#action-bar-installed", Static)
            action_bar_installed.update(self.format_action_bar("installed"))
        except:
            pass
    
    def on_ready(self) -> None:
        """Called when app is fully ready"""
        logger.info("TUI ready")
        
        # Update action bars with proper theme colors
        try:
            action_bar = self.query_one("#action-bar", Static)
            action_bar.update(self.format_action_bar("all"))
        except:
            pass
        
        try:
            action_bar_installed = self.query_one("#action-bar-installed", Static)
            action_bar_installed.update(self.format_action_bar("installed"))
        except:
            pass
        
        # Focus the search input initially
        self.query_one("#search-all", Input).focus()
        
        logger.info("Starting worker threads to load data")
        self.load_all_addons()
        self.load_installed_addons()
        
        # Trigger a refresh after a short delay to ensure checkmarks show
        self.set_timer(0.5, lambda: self.update_all_table())
    
    
    
    
    @work(thread=True)
    def load_all_addons(self) -> None:
        """Load all addons from database"""
        logger.info("load_all_addons thread started")
        
        try:
            db = Database()
            cursor = db.conn.cursor()
            logger.debug("Database connection established")
            cursor.execute("""
                SELECT name, description, homepage_url, repo_url, status, tags
                FROM addons
                WHERE deleted_at_utc IS NULL
                ORDER BY name
            """)
            logger.debug("Query executed")
            
            addons = []
            for row in cursor.fetchall():
                # Skip addons with empty names
                if not row[0]:
                    continue
                    
                addon = {
                    'name': row[0],
                    'description': row[1] or '',
                    'url': row[2] or '',
                    'repo_url': row[3] or '',
                    'status': row[4] or 'available',
                    'tags': json.loads(row[5]) if row[5] else []
                }
                addons.append(addon)
            
            # Update instance variable
            self.all_addons = addons
            
            logger.info(f"Loaded {len(addons)} addons from database")
            
            db.close()
            
            # Only update table if installed addons are already loaded
            # Otherwise wait for installed addons to load first
            if self.installed_addons is not None:
                # Schedule UI update on main thread
                logger.debug("Calling update_all_table from thread")
                self.call_from_thread(self.update_all_table)
                logger.debug("Update scheduled")
            
            # Also try updating synchronously as a test
            # self.update_all_table()
            
        except Exception as e:
            logger.error(f"Error loading all addons: {e}", exc_info=True)
    
    @work(thread=True)
    def load_installed_addons(self) -> None:
        """Load installed addons"""
        db = Database()
        installer = AddonInstaller(db)
        installer.sync_installed_state()
        installed = installer.get_installed_addons()
        db.close()
        
        # Update instance variable
        self.installed_addons = installed
        
        # Schedule UI updates on main thread
        self.call_from_thread(self.update_installed_table)
        # Don't update all table here - let the caller handle it with cursor preservation
    
    @work(thread=True)
    def load_broken_addons(self) -> None:
        """Load broken addons from database"""
        db = Database()
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT name, description, homepage_url, status
            FROM addons
            WHERE status IN ('broken', 'missing', 'unstable')
            AND deleted_at_utc IS NULL
            ORDER BY name
        """)
        
        broken = []
        for row in cursor.fetchall():
            broken.append({
                'name': row[0],
                'description': row[1] or '',
                'url': row[2] or '',
                'status': row[3]
            })
        
        db.close()
        
        # Schedule UI update on main thread
        self.call_from_thread(self.update_broken_table, broken)
    
    def update_all_table_preserve_cursor(self) -> None:
        """Update the all addons table while preserving cursor position"""
        # Since update_all_table now preserves cursor internally, just call it
        self.update_all_table()
    
    def update_all_table(self) -> None:
        """Update the all addons table"""
        import time
        call_time = time.time()
        logger.info(f"update_all_table called at {call_time:.3f} with {len(self.all_addons)} addons")
        
        try:
            table = self.query_one("#all-table", DataTable)
            logger.debug("Got all-table widget")
            
            # Always save current cursor position before clearing
            saved_cursor = table.cursor_coordinate
            logger.debug(f"Current cursor position: {saved_cursor}")
            
            # Only set up columns if they don't exist yet
            if len(table.columns) == 0:
                logger.debug("No columns exist, adding them")
                table.add_column("", key="status", width=2)
                table.add_column("Name", key="name", width=25)
                table.add_column("Tags", key="tags", width=8)
                table.add_column("Description", key="description")  # No width = use remaining space
            else:
                # If columns exist, just clear the rows
                logger.debug(f"Columns exist, clearing {table.row_count} rows")
                table.clear(columns=False)  # Clear rows only, keep columns
            
            # Use current filter
            filter_text = self.current_filter
            logger.debug(f"Filtering with: '{filter_text}'")
            
            # Helper function to check if URL is problematic
            def is_problematic_url(url):
                """Check if URL is non-standard or problematic"""
                if not url:
                    return True  # No URL is problematic
                
                url_lower = url.lower()
                
                # Standard patterns for good URLs
                standard_patterns = [
                    r'^https?://github\.com/[\w\-]+/[\w\-]+/?$',
                    r'^https?://gitlab\.com/[\w\-]+/[\w\-]+/?$',
                    r'^https?://bitbucket\.org/[\w\-]+/[\w\-]+/?$',
                    # Also allow /tree/branch-name for specific branches
                    r'^https?://github\.com/[\w\-]+/[\w\-]+/tree/[\w\-\.]+/?$',
                    r'^https?://gitlab\.com/[\w\-]+/[\w\-]+/tree/[\w\-\.]+/?$',
                ]
                
                import re
                for pattern in standard_patterns:
                    if re.match(pattern, url_lower):
                        return False  # URL matches standard pattern
                
                # Check for problematic patterns
                if any(x in url_lower for x in ['.zip', '.rar', '.7z', '/download/', '/releases/', '/wiki/', '/blob/']):
                    return True
                
                # URLs with extra path segments or query params (but allow /tree/)
                if '?' in url or '#' in url:
                    return True
                
                # Check if it's a tree URL that didn't match our patterns (might have unusual branch name)
                if '/tree/' in url_lower and ('github.com' in url_lower or 'gitlab.com' in url_lower):
                    return False  # Allow any tree URL on GitHub/GitLab
                
                # Check segment count (but be more lenient)
                if url.count('/') > 5:  # Changed from 4 to 5 to allow /tree/branch
                    return True
                
                return True  # Default to problematic if not standard
            
            # Separate marked and unmarked addons
            marked_addons = []
            unmarked_addons = []
            
            for addon in self.all_addons:
                # Apply debug filter if active
                if self.debug_url_filter:
                    repo_url = addon.get('repo_url', '')
                    if not is_problematic_url(repo_url):
                        continue  # Skip addons with good URLs in debug mode
                
                is_marked = addon['name'] in self.marked_addons
                
                # Marked addons are NEVER filtered out
                if is_marked:
                    marked_addons.append(addon)
                # Only filter unmarked addons
                elif not filter_text or filter_text in addon['name'].lower() or filter_text in addon['description'].lower():
                    unmarked_addons.append(addon)
            
            # Add marked addons first (at the top)
            rows_added = 0
            from rich.text import Text
            
            # First add all marked addons
            for addon in marked_addons:
                addon_key = addon['name'].lower()
                is_installed = addon_key in self.installed_addons
                
                # Marked addons show different icons based on state
                if is_installed:
                    addon_info = self.installed_addons.get(addon_key)
                    if addon_info and addon_info.get('enabled') == 0:
                        status_icon = "◇"  # Marked + Disabled (hollow diamond)
                        status_style = "dim cyan"
                    else:
                        status_icon = "◆"  # Marked + Enabled
                        status_style = "bold cyan"
                else:
                    status_icon = "◆"  # Marked + Not installed
                    status_style = "bold cyan"
                
                # Format tags as icons
                tag_icons = self.format_tag_icons(addon.get('tags', []))
                
                # Get full description
                desc = addon['description']
                
                status_text = Text(status_icon, style=status_style)
                desc_text = Text(desc, style="dim")
                
                table.add_row(
                    status_text,
                    addon['name'],
                    tag_icons,
                    desc_text,
                    key=addon['name']
                )
                rows_added += 1
            
            # Then add unmarked addons
            for addon in unmarked_addons:
                # Check if installed and enabled state
                addon_key = addon['name'].lower()
                is_installed = addon_key in self.installed_addons
                status = addon.get('status', 'available')
                
                # Status icon for unmarked addons
                if is_installed:
                    # Check if addon is enabled or disabled
                    addon_info = self.installed_addons.get(addon_key)
                    if addon_info and addon_info.get('enabled') == 0:
                        status_icon = "○"  # Disabled (empty circle)
                        status_style = "dim"
                    else:
                        status_icon = "✓"  # Installed and enabled
                        status_style = "green"
                elif status == 'broken':
                    status_icon = "✗"  # Broken
                    status_style = "red"
                elif status == 'missing':
                    status_icon = "?"  # Missing
                    status_style = "yellow"
                else:
                    status_icon = "·"  # Available
                    status_style = "dim"
                
                # Format tags as icons
                tag_icons = self.format_tag_icons(addon.get('tags', []))
                
                # Get full description
                desc = addon['description']
                
                status_text = Text(status_icon, style=status_style)
                desc_text = Text(desc, style="dim")
                
                table.add_row(
                    status_text,
                    addon['name'],
                    tag_icons,
                    desc_text,
                    key=addon['name']
                )
                rows_added += 1
            
            filtered_count = len(self.all_addons) - len(marked_addons) - len(unmarked_addons)
            logger.info(f"Added {rows_added} rows to all-table (marked: {len(marked_addons)}, filtered out: {filtered_count})")
            logger.debug(f"Table now has {table.row_count} rows and {len(table.columns)} columns")
            logger.debug(f"Table columns: {[col.label for col in table.columns.values()]}")
            
            # Restore cursor position
            try:
                table.cursor_coordinate = saved_cursor
                logger.debug(f"Restored cursor to: {saved_cursor}")
            except Exception as e:
                logger.warning(f"Failed to restore cursor: {e}")
            
            # Update the counter
            try:
                counter = self.query_one("#addon-counter", Static)
                total = len(self.all_addons)
                shown = len(marked_addons) + len(unmarked_addons)
                
                # Add marked count if any
                if self.marked_addons:
                    counter.update(f"{shown}/{total} ([bold cyan]{len(self.marked_addons)}✓[/bold cyan])")
                else:
                    counter.update(f"{shown}/{total}")
            except:
                pass  # Counter might not exist yet
            
        except Exception as e:
            logger.error(f"Error updating all table: {e}", exc_info=True)
    
    def update_installed_table(self) -> None:
        """Update the installed addons table"""
        table = self.query_one("#installed-table", DataTable)
        
        # Always save current cursor position before clearing
        saved_cursor = table.cursor_coordinate
        logger.debug(f"Current cursor position in installed table: {saved_cursor}")
        
        # Only set up columns if they don't exist yet
        if len(table.columns) == 0:
            table.add_column("", key="status", width=2)  # Status column for mark indicator
            table.add_column("Name", key="name", width=25)
            table.add_column("Folder", key="folder", width=20)
            table.add_column("Version", key="version", width=10)
            table.add_column("Tags", key="tags", width=8)
            table.add_column("Description", key="description")  # No width = use remaining space
        else:
            # If columns exist, just clear the rows
            table.clear(columns=False)  # Clear rows only, keep columns
        
        # Use current filter
        filter_text = self.current_filter
        
        # Separate marked and unmarked installed addons
        marked_installed = []
        unmarked_installed = []
        
        for addon_key, addon in self.installed_addons.items():
            is_marked = addon['name'] in self.marked_addons
            
            # Marked addons are NEVER filtered
            if is_marked:
                marked_installed.append((addon_key, addon))
            # Only filter unmarked addons
            elif not filter_text or filter_text in addon['name'].lower():
                unmarked_installed.append((addon_key, addon))
        
        from rich.text import Text
        
        # Add marked addons first
        for addon_key, addon in marked_installed:
            # Format folder
            folder = Path(addon['path']).name if addon['path'] else 'Unknown'
            
            # Get addon details from all_addons
            addon_details = None
            for a in self.all_addons:
                if a['name'].lower() == addon_key:
                    addon_details = a
                    break
            
            # Format tags as icons
            tags = addon_details.get('tags', []) if addon_details else []
            tag_icons = self.format_tag_icons(tags)
            
            # Get full description
            desc = addon_details.get('description', '') if addon_details else ''
            desc_text = Text(desc, style="dim")
            
            # Marked status icon - show if disabled
            if addon.get('enabled') == 0:
                status_text = Text("◇", style="dim cyan")  # Marked + Disabled
            else:
                status_text = Text("◆", style="bold cyan")  # Marked + Enabled
            
            table.add_row(
                status_text,
                addon['name'],
                folder,
                addon['version'] or 'Unknown',
                tag_icons,
                desc_text,
                key=addon['name']
            )
        
        # Add unmarked addons
        for addon_key, addon in unmarked_installed:
            # Format folder
            folder = Path(addon['path']).name if addon['path'] else 'Unknown'
            
            # Get addon details from all_addons
            addon_details = None
            for a in self.all_addons:
                if a['name'].lower() == addon_key:
                    addon_details = a
                    break
            
            # Format tags as icons
            tags = addon_details.get('tags', []) if addon_details else []
            tag_icons = self.format_tag_icons(tags)
            
            # Get full description
            desc = addon_details.get('description', '') if addon_details else ''
            desc_text = Text(desc, style="dim")
            
            # Status icon for unmarked installed addons
            if addon.get('enabled') == 0:
                status_text = Text("○", style="dim")  # Disabled
            else:
                status_text = Text("✓", style="green")  # Enabled
            
            table.add_row(
                status_text,
                addon['name'],
                folder,
                addon['version'] or 'Unknown',
                tag_icons,
                desc_text,
                key=addon['name']
            )
        
        # Restore cursor position
        try:
            table.cursor_coordinate = saved_cursor
            logger.debug(f"Restored cursor to: {saved_cursor}")
        except Exception as e:
            # If cursor position is invalid (e.g., fewer rows now), just log it
            logger.warning(f"Failed to restore cursor in installed table: {e}")
        
        # Update the counter
        try:
            counter = self.query_one("#installed-counter", Static)
            total = len(self.installed_addons)
            shown = len(marked_installed) + len(unmarked_installed)
            
            # Add marked count if any
            if self.marked_addons:
                # Filter to only show marked count for installed addons
                marked_count = len([a for a in self.marked_addons if a.lower() in self.installed_addons])
                if marked_count > 0:
                    counter.update(f"{shown}/{total} ([bold cyan]{marked_count}✓[/bold cyan])")
                else:
                    counter.update(f"{shown}/{total}")
            else:
                counter.update(f"{shown}/{total}")
        except:
            pass  # Counter might not exist yet
    
    def update_broken_table(self, broken_addons) -> None:
        """Update the broken addons table"""
        table = self.query_one("#broken-table", DataTable)
        
        # Only set up columns if they don't exist yet
        if len(table.columns) == 0:
            table.add_column("Name", key="name", width=25)
            table.add_column("Description", key="description", width=50)
            table.add_column("Status", key="status", width=10)
        else:
            # If columns exist, just clear the rows
            table.clear(columns=False)  # Clear rows only, keep columns
        
        # Add rows
        for addon in broken_addons:
            # Show full description and URL - no truncation needed
            table.add_row(
                addon['name'],
                addon['description'] or '',
                addon['status'],
                key=addon['name']
            )
    
    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes - live fuzzy search"""
        logger.debug(f"Input changed: {event.input.id} = '{event.value}'")
        if event.input.id == "search-all":
            self.current_filter = event.value.lower()
            logger.debug(f"Setting filter to: '{self.current_filter}'")
            self.update_all_table()
        elif event.input.id == "search-installed":
            self.current_filter = event.value.lower()
            logger.debug(f"Setting filter to: '{self.current_filter}'")
            self.update_installed_table()
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search input submission - focus table"""
        if event.input.id == "search-all":
            table = self.query_one("#all-table", DataTable)
            table.focus()
        elif event.input.id == "search-installed":
            table = self.query_one("#installed-table", DataTable)
            table.focus()
    
    def on_key(self, event) -> None:
        """Handle key events - auto-focus search on letter keys"""
        # Don't process keys if a modal is open
        if len(self.screen_stack) > 1:
            return
            
        # Check if we're in a search input
        focused = self.focused
        if focused and isinstance(focused, Input):
            if event.key in ("down", "up"):
                # Move focus to the table and handle navigation
                if focused.id == "search-all":
                    table = self.query_one("#all-table", DataTable)
                    table.focus()
                    if event.key == "down":
                        table.action_cursor_down()
                    else:
                        table.action_cursor_up()
                    event.prevent_default()
                elif focused.id == "search-installed":
                    table = self.query_one("#installed-table", DataTable)
                    table.focus()
                    if event.key == "down":
                        table.action_cursor_down()
                    else:
                        table.action_cursor_up()
                    event.prevent_default()
        else:
            # Check if Enter was pressed on DataTable
            if event.key == "enter" and isinstance(focused, DataTable) and self.selected_addon:
                # Trigger quick install with dialog
                self.action_quick_install()
                event.prevent_default()
                event.stop()
                return
            
            # Auto-focus search on letter keys if not in an input
            if event.key and len(event.key) == 1 and event.key.isalpha():
                # Get the active tab's search input
                try:
                    tabbed = self.query_one(TabbedContent)
                    active_tab = tabbed.active
                    
                    if active_tab == "all-tab":
                        search = self.query_one("#search-all", Input)
                    else:
                        search = self.query_one("#search-installed", Input)
                    
                    # Focus the search and add the character
                    search.focus()
                    # Use call_after_refresh to ensure focus completes before adding text
                    self.call_after_refresh(lambda: self._append_to_search(search, event.key))
                    event.prevent_default()
                except:
                    pass
    
    def on_mouse_down(self, event) -> None:
        """Handle mouse down - track which button was pressed"""
        # For right-click marking
        if event.button == 3:  # Right button
            # Store the current addon before the click
            self._addon_before_click = self.selected_addon
            # Set a flag that we have a pending right-click mark
            self._pending_right_click_mark = True
            # Schedule a check after the click processes with a small delay
            self.set_timer(0.1, self._check_right_click_same_row)
    
    def _check_right_click_same_row(self) -> None:
        """Check if right-click was on the same row that was already highlighted"""
        if hasattr(self, '_pending_right_click_mark') and self._pending_right_click_mark:
            self._pending_right_click_mark = False  # Always clear the flag
            # Check if we're still on the same row (no row_highlighted event fired)
            if hasattr(self, '_addon_before_click') and self._addon_before_click == self.selected_addon:
                # Same row was clicked, mark/unmark it now
                if self.selected_addon:
                    self.action_mark()
    
    def _append_to_search(self, search_input: Input, char: str) -> None:
        """Append a character to the search input after focus"""
        search_input.value = search_input.value + char
        search_input.cursor_position = len(search_input.value)
    
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row highlighting in tables"""
        previous_addon = self.selected_addon
        self.selected_addon = str(event.row_key.value) if event.row_key else None
        logger.debug(f"Selected addon: {self.selected_addon}")
        
        # Check if this was triggered by a right-click (we set a flag)
        if hasattr(self, '_pending_right_click_mark') and self._pending_right_click_mark:
            self._pending_right_click_mark = False
            # Always mark on right-click, whether row changed or not
            if self.selected_addon:
                self.action_mark()
    
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection - from Enter key"""
        # Update selected addon but don't trigger install
        # The Enter key binding will handle the install
        if event.row_key:
            self.selected_addon = str(event.row_key.value)
    
    def on_data_table_refresh(self, event) -> None:
        """Log when table is refreshed"""
        logger.debug(f"DataTable refresh event from {event.sender}")
    
    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Handle tab activation - always focus the DataTable"""
        logger.debug(f"Tab activated: {event.pane.id}")
        # Always focus the DataTable in the activated tab
        if event.pane.id == "all-tab":
            try:
                table = self.query_one("#all-table", DataTable)
                table.focus()
                logger.debug("Focused all-table after tab switch")
            except:
                pass
        elif event.pane.id == "installed-tab":
            try:
                table = self.query_one("#installed-table", DataTable)
                table.focus()
                logger.debug("Focused installed-table after tab switch")
            except:
                pass
    
    
    @work(thread=True)
    def install_selected(self) -> None:
        """Install selected or marked addons"""
        # Determine what to install
        to_install = list(self.marked_addons) if self.marked_addons else ([self.selected_addon] if self.selected_addon else [])
        
        if not to_install:
            self.call_from_thread(self.notify, "No addons selected or marked", severity="warning")
            return
        
        # Simple notification instead of ugly modal
        if len(to_install) == 1:
            self.call_from_thread(self.notify, f"Installing {to_install[0]}...", timeout=None)
        else:
            self.call_from_thread(self.notify, f"Installing {len(to_install)} addons...", timeout=None)
        
        # Install each addon
        from carapace.db import Database
        from carapace.installer import AddonInstaller
        
        db = Database()
        installer = AddonInstaller(db)
        success_count = 0
        failed = []
        
        for idx, addon_name in enumerate(to_install, 1):
            # Update notification with progress
            if len(to_install) > 1:
                self.call_from_thread(self.notify, f"Installing {addon_name} ({idx}/{len(to_install)})...", timeout=None)
            
            if installer.install_addon(addon_name):
                success_count += 1
            else:
                failed.append(addon_name)
        
        db.close()
        
        # Clear marks after installation
        self.marked_addons.clear()
        
        # Reload data
        self.load_installed_addons()
        self.load_all_addons()  # Refresh to update status
        
        # Notify results
        if success_count > 0:
            if failed:
                self.call_from_thread(self.notify, f"✓ Installed {success_count} addons. ✗ Failed: {', '.join(failed)}", severity="warning")
            else:
                self.call_from_thread(self.notify, f"✓ Successfully installed {success_count} addon(s)")
        else:
            self.call_from_thread(self.notify, "✗ Failed to install addons", severity="error")
    
    @work(thread=True)
    def update_selected(self) -> None:
        """Update selected addon"""
        if not self.selected_addon:
            return
        
        # Show progress modal
        self.call_from_thread(self.show_progress_modal, "Updating", f"Updating {self.selected_addon}...")
        
        db = Database()
        installer = AddonInstaller(db)
        success = installer.update_addon(self.selected_addon)
        db.close()
        
        # Dismiss modal
        self.call_from_thread(self.dismiss_progress_modal)
        
        if success:
            self.load_installed_addons()
            self.call_from_thread(self.notify, f"Updated {self.selected_addon}")
        else:
            self.call_from_thread(self.notify, f"Failed to update {self.selected_addon}", severity="error")
    
    @work(thread=True)
    def uninstall_selected(self) -> None:
        """Uninstall selected or marked addons"""
        # Determine what to uninstall - marked addons or selected addon
        to_uninstall = list(self.marked_addons) if self.marked_addons else ([self.selected_addon] if self.selected_addon else [])
        
        if not to_uninstall:
            self.call_from_thread(self.notify, "No addons selected or marked", severity="warning")
            return
        
        # Show progress modal
        if len(to_uninstall) == 1:
            self.call_from_thread(self.show_progress_modal, "Uninstalling", f"Uninstalling {to_uninstall[0]}...")
        else:
            self.call_from_thread(self.show_progress_modal, "Uninstalling", f"Uninstalling {len(to_uninstall)} addons...")
        
        db = Database()
        installer = AddonInstaller(db)
        success_count = 0
        failed = []
        
        for idx, addon_name in enumerate(to_uninstall, 1):
            # Update progress
            self.call_from_thread(self.update_progress_modal, f"Uninstalling {addon_name} ({idx}/{len(to_uninstall)})...")
            
            if installer.remove_addon(addon_name):
                success_count += 1
                # Remove from marked addons after successful uninstall
                self.marked_addons.discard(addon_name)
            else:
                failed.append(addon_name)
        
        db.close()
        
        # Dismiss modal
        self.call_from_thread(self.dismiss_progress_modal)
        
        # Clear marked addons if batch uninstall
        if len(to_uninstall) > 1:
            self.marked_addons.clear()
        
        # Reload data
        self.load_installed_addons()
        self.load_all_addons()  # Refresh to update status
        
        # Notify results
        if success_count > 0:
            if failed:
                self.call_from_thread(self.notify, f"Uninstalled {success_count} addons. Failed: {', '.join(failed)}", severity="warning")
            else:
                self.call_from_thread(self.notify, f"Successfully uninstalled {success_count} addon(s)")
        else:
            self.call_from_thread(self.notify, "Failed to uninstall addons", severity="error")
    
    @work(thread=True)
    def sync_wiki(self) -> None:
        """Sync with wiki - preserves manual edits"""
        # Show persistent notification
        self.call_from_thread(self.notify, "Checking wiki for updates...", timeout=None)
        
        try:
            import requests
            
            # Use MediaWiki API to check revision efficiently
            api_url = 'https://turtle-wow.fandom.com/api.php'
            params = {
                'action': 'query',
                'prop': 'revisions',
                'titles': 'Addons',
                'rvprop': 'ids|timestamp',
                'format': 'json'
            }
            
            response = requests.get(api_url, params=params, timeout=10)
            data = response.json()
            
            # Extract revision info
            current_revision = None
            pages = data.get('query', {}).get('pages', {})
            for page_id, page_data in pages.items():
                revisions = page_data.get('revisions', [])
                if revisions:
                    current_revision = str(revisions[0].get('revid'))
                    break
            
            if not current_revision:
                self.call_from_thread(self.notify, "Could not get wiki revision", severity="warning")
            
            # Check stored revision
            db = Database()
            cursor = db.conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'wiki_revision'")
            stored = cursor.fetchone()
            stored_revision = stored['value'] if stored else None
            
            if current_revision and current_revision == stored_revision:
                self.call_from_thread(self.notify, "Wiki has not changed, skipping sync", severity="information")
                db.close()
                return
            
            # Parse wiki
            self.call_from_thread(self.notify, "Fetching addon list from wiki...", timeout=None)
            addons = self.parser.parse_from_url()
            
            # Save to database - but preserve manual edits
            self.call_from_thread(self.notify, f"Updating database with {len(addons)} addons...", timeout=None)
            db = Database()
            cursor = db.conn.cursor()
            count = 0
            
            for addon in addons:
                # Check if this addon has been manually edited
                cursor.execute("""
                    SELECT name, override_url, repo_url, description 
                    FROM addons 
                    WHERE name = ? AND deleted_at_utc IS NULL
                """, (addon['name'],))
                existing = cursor.fetchone()
                
                if existing and existing['override_url']:
                    # Has override URL - only update tags, preserve everything else
                    import json
                    old_tags = []
                    cursor.execute("SELECT tags FROM addons WHERE name = ?", (addon['name'],))
                    tags_row = cursor.fetchone()
                    if tags_row and tags_row['tags']:
                        old_tags = json.loads(tags_row['tags'])
                    
                    # Merge tags
                    new_tags = addon.get('tags', [])
                    merged_tags = list(set(old_tags + new_tags))
                    
                    cursor.execute("""
                        UPDATE addons 
                        SET tags = ?, updated_at_utc = ?
                        WHERE name = ? AND deleted_at_utc IS NULL
                    """, (json.dumps(merged_tags), datetime.utcnow().isoformat(), addon['name']))
                else:
                    # No manual edits - normal upsert
                    addon_data = {
                        'name': addon['name'],
                        'description': addon.get('description', ''),
                        'homepage_url': addon.get('url', ''),
                        'repo_url': addon.get('repo_url', ''),
                        'tags': addon.get('tags', []),
                        'status': addon.get('status', 'available')
                    }
                    db.upsert_addon(addon_data)
                
                count += 1
                # Update progress every 50 addons
                if count % 50 == 0:
                    self.call_from_thread(self.notify, f"Processing addons... {count}/{len(addons)}", timeout=None)
            
            db.conn.commit()
            
            # Save the revision ID if we have it
            if current_revision:
                cursor.execute("DELETE FROM settings WHERE key = 'wiki_revision'")
                cursor.execute("INSERT INTO settings (key, value) VALUES ('wiki_revision', ?)", (current_revision,))
                db.conn.commit()
            
            db.close()
            
            # Reload data
            self.load_all_addons()
            self.load_installed_addons()
            
            self.call_from_thread(self.notify, f"✓ Wiki sync complete - {len(addons)} addons", severity="information", timeout=5)
        except Exception as e:
            self.call_from_thread(self.notify, f"Wiki sync failed: {e}", severity="error")
    
    @work(thread=True)
    def check_for_updates(self) -> None:
        """Check for addon updates"""
        db = Database()
        installer = AddonInstaller(db)
        updates = installer.check_for_updates()
        db.close()
        
        if updates:
            msg = f"Updates available for: {', '.join([u['name'] for u in updates])}"
        else:
            msg = "All addons are up to date"
        
        self.call_from_thread(self.notify, msg)
    
    def show_addon_details(self) -> None:
        """Show details for selected addon"""
        if not self.selected_addon:
            self.notify("No addon selected", severity="warning")
            return
        
        # Find addon data
        addon_data = None
        for addon in self.all_addons:
            if addon['name'] == self.selected_addon:
                addon_data = addon.copy()  # Make a copy to add extra info
                break
        
        if addon_data:
            # Check if installed
            addon_data['installed'] = self.selected_addon.lower() in self.installed_addons
            if addon_data['installed']:
                installed_info = self.installed_addons.get(self.selected_addon.lower(), {})
                addon_data['version'] = installed_info.get('version', 'Unknown')
                addon_data['path'] = installed_info.get('path', '')
            
            self.push_screen(AddonDetailsScreen(self.selected_addon, addon_data))
        else:
            self.notify(f"Could not find details for {self.selected_addon}", severity="error")
    
    def edit_addon(self) -> None:
        """Edit selected addon details"""
        if not self.selected_addon:
            self.notify("No addon selected", severity="warning")
            return
        
        # Get full addon data from database
        from carapace.db import Database
        db = Database()
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT name, description, homepage_url, repo_url, override_url, status, tags
            FROM addons
            WHERE name = ?
        """, (self.selected_addon,))
        
        row = cursor.fetchone()
        db.close()
        
        if row:
            addon_data = {
                'name': row['name'],
                'description': row['description'] or '',
                'url': row['homepage_url'] or '',
                'repo_url': row['repo_url'] or '',
                'override_url': row['override_url'] or '',
                'status': row['status'] or 'available',
                'tags': json.loads(row['tags']) if row['tags'] else []
            }
            self.push_screen(EditAddonModal(self.selected_addon, addon_data))
        else:
            self.notify(f"Could not find {self.selected_addon} in database", severity="error")
    
    def fix_broken_addon(self) -> None:
        """Open broken addon fixer for selected addon"""
        if not self.selected_addon:
            return
        
        # For now, just show a notification
        self.notify(f"Fix broken addon: {self.selected_addon} (not implemented yet)")
    
    def action_refresh(self) -> None:
        """Refresh current view"""
        # Force immediate update with existing data
        if self.all_addons:
            self.update_all_table()
            logger.info(f"Forced refresh with {len(self.all_addons)} addons")
        
        # Then reload from database
        self.load_all_addons()
        self.load_installed_addons()
        self.notify("Refreshed")
    
    def action_focus_search(self) -> None:
        """Focus search input"""
        # Find active tab and focus its search
        try:
            tabbed = self.query_one(TabbedContent)
            active_tab = tabbed.active
            
            if active_tab == "all-tab":
                self.query_one("#search-all", Input).focus()
            elif active_tab == "installed-tab":
                self.query_one("#search-installed", Input).focus()
        except:
            pass
    
    def action_install(self) -> None:
        """Install selected addon"""
        self.install_selected()
    
    def action_quick_install(self) -> None:
        """Quick install with confirmation on Enter key"""
        if not self.selected_addon:
            self.notify("No addon selected", severity="warning")
            return
        
        # Check if already installed
        if self.selected_addon.lower() in self.installed_addons:
            self.notify(f"{self.selected_addon} is already installed", severity="info")
            return
        
        # Show confirmation dialog in a worker
        self.run_worker(self._show_install_confirm, name="quick_install")
    
    async def _show_install_confirm(self) -> None:
        """Show install confirmation modal"""
        result = await self.push_screen_wait(InstallConfirmModal(self.selected_addon))
        
        if result:
            # Install the addon in a separate worker
            # Use a partial function to bind the addon name
            from functools import partial
            install_func = partial(self._install_single_addon, self.selected_addon)
            self.run_worker(install_func, name="install_single", thread=True)
    
    def _install_single_addon(self, addon_name: str) -> None:
        """Install a single addon without showing progress modal"""
        from carapace.db import Database
        from carapace.installer import AddonInstaller
        
        # Simple notification instead of modal
        self.call_from_thread(self.notify, f"Installing {addon_name}...", timeout=None)
        
        db = Database()
        installer = AddonInstaller(db)
        
        if installer.install_addon(addon_name):
            self.call_from_thread(self.notify, f"✓ {addon_name} installed successfully")
            # Update installed list synchronously right here
            installer.sync_installed_state()
            installed = installer.get_installed_addons()
            self.installed_addons = installed
            logger.info(f"Updated installed_addons, now have {len(self.installed_addons)} installed")
            # Now update the table with the fresh installed list
            self.call_from_thread(self.update_all_table)
            self.call_from_thread(self.update_installed_table)
        else:
            self.call_from_thread(self.notify, f"✗ Failed to install {addon_name}", severity="error")
        
        db.close()
    
    def action_update(self) -> None:
        """Update selected addon"""
        self.update_selected()
    
    def action_uninstall(self) -> None:
        """Uninstall selected addon"""
        self.uninstall_selected()
    
    def action_sync(self) -> None:
        """Sync with wiki and refresh"""
        self.sync_wiki()
        self.action_refresh()
    
    # def action_details(self) -> None:
    #     """Show addon details"""
    #     self.show_addon_details()
    
    def action_edit(self) -> None:
        """Edit selected addon"""
        self.edit_addon()
    
    def action_mark(self) -> None:
        """Mark/unmark current addon for batch operations"""
        if not self.selected_addon:
            return
        
        if self.selected_addon in self.marked_addons:
            self.marked_addons.remove(self.selected_addon)
        else:
            self.marked_addons.add(self.selected_addon)
        
        # Get the active tab to determine which table to update
        try:
            tabbed = self.query_one(TabbedContent)
            active_tab = tabbed.active
            
            if active_tab == "all-tab":
                table = self.query_one("#all-table", DataTable)
                current_coord = table.cursor_coordinate
                self.update_all_table()
            else:
                table = self.query_one("#installed-table", DataTable)
                current_coord = table.cursor_coordinate
                self.update_installed_table()
            
            # Restore cursor position after update
            if current_coord:
                try:
                    table.cursor_coordinate = current_coord
                except:
                    pass  # If the row doesn't exist anymore, just ignore
        except:
            pass
    
    def action_select(self) -> None:
        """Handle enter key on selected item"""
        # Get active tab
        try:
            tabbed = self.query_one(TabbedContent)
            active_tab = tabbed.active
            
            if active_tab == "all-tab":
                self.install_selected()
            elif active_tab == "installed-tab":
                self.update_selected()
        except:
            pass
    
    def action_toggle_enable(self) -> None:
        """Enable or disable selected addon"""
        if not self.selected_addon:
            self.notify("No addon selected", severity="warning")
            return
        
        # Check if addon is installed
        if self.selected_addon.lower() not in self.installed_addons:
            self.notify(f"{self.selected_addon} is not installed", severity="info")
            return
        
        self.toggle_addon_enabled()
    
    def disable_addon(self, addon_name: str) -> bool:
        """Disable an addon by removing its junction (keep in .repos)"""
        from carapace.db import Database
        import os
        from pathlib import Path
        import subprocess
        
        db = Database()
        cursor = db.conn.cursor()
        
        # Get addon info
        cursor.execute("""
            SELECT path FROM installed 
            WHERE name = ? AND deleted_at_utc IS NULL
        """, (addon_name,))
        
        addon_row = cursor.fetchone()
        if not addon_row:
            db.close()
            return False
        
        addon_path = Path(addon_row['path'])
        
        try:
            # Windows: Remove junction
            if os.path.islink(addon_path) or os.path.exists(addon_path):
                subprocess.run(['cmd', '/c', 'rmdir', str(addon_path)], check=False, capture_output=True)
            
            # Update database to mark as disabled
            cursor.execute("""
                UPDATE installed 
                SET enabled = 0 
                WHERE name = ? AND deleted_at_utc IS NULL
            """, (addon_name,))
            db.conn.commit()
            
            # Update installed list (keys are lowercase)
            addon_key = addon_name.lower()
            if addon_key in self.installed_addons:
                self.installed_addons[addon_key]['enabled'] = 0
            
            db.close()
            return True
        except Exception as e:
            logger.error(f"Failed to disable {addon_name}: {e}")
            db.close()
            return False
    
    def enable_addon(self, addon_name: str) -> bool:
        """Enable an addon by creating junction from .repos"""
        from carapace.db import Database
        from carapace.installer import AddonInstaller
        from pathlib import Path
        import subprocess
        
        db = Database()
        installer = AddonInstaller(db)
        cursor = db.conn.cursor()
        
        # Get addon info
        cursor.execute("""
            SELECT path FROM installed 
            WHERE name = ? AND deleted_at_utc IS NULL
        """, (addon_name,))
        
        addon_row = cursor.fetchone()
        if not addon_row:
            db.close()
            return False
        
        addon_path = Path(addon_row['path'])  # This is the full path like E:\Games\TurtleWoW\Interface\AddOns\Attack
        
        try:
            # Find the repo folder - should be in AddOns/.repos/AddonName
            repo_folder = installer.addon_path / ".repos" / addon_path.name
            if not repo_folder.exists():
                logger.error(f"Repository not found for {addon_name} at {repo_folder}")
                db.close()
                return False
            
            # Remove existing path if it exists (might be leftover from disable)
            if addon_path.exists():
                # Just use rmdir for junctions, it's simpler and works
                subprocess.run(['cmd', '/c', 'rmdir', str(addon_path)], check=False, capture_output=True)
            
            # Create junction from AddOns/AddonName to AddOns/.repos/AddonName
            # IMPORTANT: addon_path is the target (where junction will be created)
            #            repo_folder is the source (what the junction points to)
            subprocess.run(['mklink', '/J', str(addon_path), str(repo_folder)], 
                         shell=True, check=True, capture_output=True)
            
            # Update database to mark as enabled
            cursor.execute("""
                UPDATE installed 
                SET enabled = 1 
                WHERE name = ? AND deleted_at_utc IS NULL
            """, (addon_name,))
            db.conn.commit()
            
            # Update installed list (keys are lowercase)
            addon_key = addon_name.lower()
            if addon_key in self.installed_addons:
                self.installed_addons[addon_key]['enabled'] = 1
            
            db.close()
            return True
        except Exception as e:
            logger.error(f"Failed to enable {addon_name}: {e}")
            db.close()
            return False
    
    @work(thread=True)
    def toggle_addon_enabled(self) -> None:
        """Toggle addon enabled/disabled state"""
        from carapace.db import Database
        
        db = Database()
        cursor = db.conn.cursor()
        
        # Get addon from database to check current state
        cursor.execute("""
            SELECT name, enabled 
            FROM installed 
            WHERE name = ? AND deleted_at_utc IS NULL
        """, (self.selected_addon,))
        
        addon_row = cursor.fetchone()
        if not addon_row:
            db.close()
            self.call_from_thread(self.notify, f"{self.selected_addon} is not installed", severity="warning")
            return
        
        is_currently_enabled = addon_row['enabled'] == 1
        db.close()
        
        # Toggle based on database state
        if is_currently_enabled:
            success = self.disable_addon(self.selected_addon)
            if success:
                self.call_from_thread(self.notify, f"Disabled {self.selected_addon}")
            else:
                self.call_from_thread(self.notify, f"Failed to disable {self.selected_addon}", severity="error")
        else:
            success = self.enable_addon(self.selected_addon)
            if success:
                self.call_from_thread(self.notify, f"Enabled {self.selected_addon}")
            else:
                self.call_from_thread(self.notify, f"Failed to enable {self.selected_addon}", severity="error")
        
        # Refresh the table UI - both All and Installed tabs
        self.call_from_thread(self.update_all_table)
        self.call_from_thread(self.update_installed_table)
    
    def action_show_help(self) -> None:
        """Show program info and help"""
        from textual.widgets import Static
        from textual.containers import VerticalScroll
        import platform
        import sys
        from pathlib import Path
        
        class HelpModal(ModalScreen):
            """Help dialog showing program info"""
            
            DEFAULT_CSS = """
            HelpModal {
                align: center middle;
                background: transparent;
            }
            
            #help-container {
                width: 70;
                height: 80%;
                background: $panel;
                border: thick $primary;
                padding: 1 2;
            }
            
            #help-title {
                text-style: bold;
                color: $text;
                text-align: center;
                margin-bottom: 1;
            }
            
            .help-section {
                margin-bottom: 1;
            }
            
            .help-link {
                color: $accent;
                text-style: underline;
            }
            """
            
            BINDINGS = [
                ("escape", "dismiss", "Close"),
            ]
            
            def compose(self) -> ComposeResult:
                # The actual modal
                with Container(id="help-container"):
                    yield Static("[bold]🐢🐢🐢 Carapace 🐢🐢🐢\n\na WoW addon manager[/bold]", id="help-title")
                    
                    with VerticalScroll():
                        # Get system info
                        py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
                        os_info = f"{platform.system()} {platform.release()}"
                        wow_path = self.app.addon_path.parent.parent if self.app.addon_path else "Not configured"
                        
                        yield Static(
                            "[bold cyan]About Carapace:[/bold cyan]\n"
                            "A modern addon manager for classic/vanilla WoW servers.\n"
                            "Designed specifically for TurtleWoW community\n"
                            "But can be expanded to similar communities.\n"
                            "\n"
                            "[bold cyan]Version Information:[/bold cyan]\n"
                            f"Carapace Version: MVP (Development)\n"
                            f"Python: {py_version}\n"
                            f"Operating System: {os_info}\n"
                            f"WoW Directory: {wow_path}\n"
                            "\n"
                            "[bold cyan]Key Features:[/bold cyan]\n"
                            "• Git-based addon installation with junction links\n"
                            "• Live fuzzy search - just start typing\n"
                            "• Enable/Disable addons without uninstalling\n"
                            "• Batch operations with marking system\n"
                            "• Tokyo Night theme by default\n"
                            "• Auto-update all installed addons\n"
                            "\n"
                            "[bold cyan]Contact / Help:[/bold cyan]\n"
                            "For detailed documentation and help, or to\n"
                            "report issues or request features visit our GitHub:\n"
                            "[cyan]https://github.com/mikl0s/Carapace[/cyan]\n"
                            "\n"
                            "[bold cyan]Quick Start:[/bold cyan]\n"
                            "• Type any letter to start searching\n"
                            "• Press Enter on an addon to install it\n"
                            "• Use Space to mark multiple addons\n"
                            "• Press F2 to install marked addons\n"
                            "• Press F12 to update all installed addons\n"
                            "\n"
                            "[bold cyan]Credits:[/bold cyan]\n"
                            "Created for the TurtleWoW community\n"
                            "Built with Textual TUI framework in Python\n"
                            "\n"
                            "[bold cyan]Donations & Support:[/bold cyan]\n"
                            "If you find this tool useful, consider supporting me\n"
                            "either in TurtleWoW or hiring me for a job :D\n"
                        )
            
            def action_dismiss(self) -> None:
                """Close the help dialog"""
                self.app.pop_screen()
        
        self.push_screen(HelpModal())
    
    def action_update_all(self) -> None:
        """Update all installed addons"""
        self.update_all_addons()
    
    @work(thread=True)
    def update_all_addons(self) -> None:
        """Update all installed addons in background"""
        if not self.installed_addons:
            self.call_from_thread(self.notify, "No addons installed", severity="info")
            return
        
        # Show progress modal
        addon_count = len(self.installed_addons)
        self.call_from_thread(self.show_progress_modal, "Updating All", f"Updating {addon_count} addons...")
        
        db = Database()
        installer = AddonInstaller(db)
        success_count = 0
        failed = []
        
        for idx, (addon_key, addon_info) in enumerate(self.installed_addons.items(), 1):
            addon_name = addon_info['name']
            self.call_from_thread(self.update_progress_modal, f"Updating {addon_name} ({idx}/{addon_count})...")
            
            if installer.update_addon(addon_name):
                success_count += 1
            else:
                failed.append(addon_name)
        
        db.close()
        
        # Dismiss progress modal
        self.call_from_thread(self.dismiss_progress_modal)
        
        # Reload data
        self.load_installed_addons()
        self.load_all_addons()
        
        # Notify results
        if success_count > 0:
            if failed:
                self.call_from_thread(self.notify, f"Updated {success_count} addons. Failed: {', '.join(failed)}", severity="warning")
            else:
                self.call_from_thread(self.notify, f"Successfully updated {success_count} addon(s)")
        else:
            self.call_from_thread(self.notify, "No addons needed updates", severity="info")
    
    def action_mark_all(self) -> None:
        """Mark all visible addons"""
        try:
            tabbed = self.query_one(TabbedContent)
            active_tab = tabbed.active
            
            if active_tab == "all-tab":
                table = self.query_one("#all-table", DataTable)
                # Mark all non-installed addons
                for row_key in table.rows:
                    addon_name = str(row_key.value)
                    if addon_name.lower() not in self.installed_addons:
                        self.marked_addons.add(addon_name)
                
                # Refresh table to show marks
                self.update_all_table()
        except:
            pass
    
    def action_clear_marks(self) -> None:
        """Clear all marked addons"""
        self.marked_addons.clear()
        
        # Refresh both tables
        self.update_all_table()
        self.update_installed_table()
    
    def action_export_list(self) -> None:
        """Export installed addon list to file"""
        if not self.installed_addons:
            self.notify("No addons installed to export", severity="info")
            return
        
        # Create export file
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"carapace_addons_{timestamp}.txt"
        
        try:
            with open(filename, 'w') as f:
                f.write(f"# Carapace Addon List - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Total: {len(self.installed_addons)} addons\n\n")
                
                for addon_key, addon_info in sorted(self.installed_addons.items()):
                    f.write(f"{addon_info['name']}\n")
            
            self.notify(f"Exported addon list to {filename}")
        except Exception as e:
            self.notify(f"Failed to export: {e}", severity="error")
    
    def action_debug_filter_urls(self) -> None:
        """Hidden debug function to filter addons with problematic URLs"""
        self.debug_url_filter = not self.debug_url_filter
        
        if self.debug_url_filter:
            self.notify("🔍 Debug: Showing only addons with problematic URLs", severity="warning")
        else:
            self.notify("Debug: Showing all addons")
        
        # Refresh the table with the filter
        self.update_all_table()


def run_tui():
    """Run the TUI application"""
    import os
    # Set Tokyo Night theme via environment variable
    os.environ["TEXTUAL_THEME"] = "tokyo-night"
    app = CarapaceTUI()
    app.run()


if __name__ == "__main__":
    run_tui()