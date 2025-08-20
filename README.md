# 🐢 Carapace - Modern WoW Addon Manager

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) 
![Windows](https://img.shields.io/badge/platform-Windows-blue)
![Status](https://img.shields.io/badge/status-MVP-green)
![GitHub Repo](https://img.shields.io/badge/github-mikl0s%2Fcarapace-blue?logo=github)

A powerful, modern addon manager for World of Warcraft classic/vanilla servers, designed specifically for TurtleWoW and similar communities.

## ✨ Key Features

- **🔍 Instant Search** - Just start typing! Any letter automatically focuses search
- **📦 Git-Based Installation** - Uses Git repositories with Windows junctions for efficient storage
- **🎯 Smart Marking System** - Space to mark/unmark, right-click also marks
- **🔄 Enable/Disable Without Uninstalling** - Keep addons updated but disabled
- **🎨 Beautiful Tokyo Night Theme** - Easy on the eyes for extended use
- **⚡ F-Key Shortcuts** - All major functions mapped to F1-F12
- **📊 Live Counter** - Shows filtered/total addons with marked count
- **🛡️ Preserves Manual Edits** - Wiki sync won't overwrite your custom URLs
- **✅ Smart Sync** - Only updates when wiki changes (checks revision ID)
- **🎯 Small Modal Overlays** - Non-intrusive confirmation dialogs

## 🚀 Quick Start

### Requirements

- **Windows** (7/10/11)
- **Python 3.11+** (if running from source)
- **Git** (for addon installation)
- **WoW Classic/TurtleWoW** client

### Installation

```bash
# Clone the repository
git clone https://github.com/mikl0s/carapace.git
cd carapace

# Install dependencies
pip install -r requirements.txt

# Run the TUI
python -m carapace.tui
```

### First Run

1. **Auto-detects** TurtleWoW installation from registry
2. **Creates** necessary folders (`.repos`, database)
3. **Syncs** addon database from wiki
4. **Applies** Tokyo Night theme automatically

## ⌨️ Keyboard Shortcuts

### Navigation & Actions

| Key | Action | Description |
|-----|--------|-------------|
| **Any Letter** | Search | Auto-focuses search and types |
| **↑↓** | Navigate | Move through addon list |
| **Enter** | Quick Install | Shows confirmation modal |
| **Space** | Mark/Unmark | Select for batch operations |
| **Right Click** | Mark/Unmark | Alternative marking method |
| **Tab** | Switch Tabs | Toggle All/Installed tabs |
| **ESC** | Exit | Close the application |

### Function Keys (All Addons Tab)

```
F1 Help           F2 Install         F3 Uninstall      F4 Enable/Disable
F5 Update Addon   F6 Mark All        F7 Unmark All     F8 Update DB from Wiki
F9 Edit Addon     ESC Exit           F12 Update DB + auto-update all
```

### Function Keys (Installed Tab)

```
F1 Help           F3 Uninstall      F4 Enable/Disable  F5 Update Addon

F6 Mark All       F7 Unmark All     F12 Update All     ESC Exit
```

## 🎯 Core Features Explained

### Git-Based Installation

```
Interface/AddOns/
├── .repos/                    # Hidden folder with Git repositories
│   ├── pfQuest/              # Full Git repository
│   └── BigWigs/              # Full Git repository
├── pfQuest → .repos/pfQuest  # Windows junction (like a shortcut)
└── BigWigs → .repos/BigWigs  # Windows junction
```

**Benefits:**
- Single source of truth in `.repos`
- Easy updates with `git pull`
- Enable/disable by adding/removing junctions
- No duplicate files

### Smart Wiki Sync

The F8 sync feature:
1. **Checks revision ID** via MediaWiki API (lightweight)
2. **Skips if unchanged** - no database modifications
3. **Preserves manual edits** - keeps override URLs
4. **Only merges tags** for manually edited addons

### Marking System

- **Visual feedback**: Marked addons show `[M]` prefix
- **Persistent**: Marked addons stay at top when filtering
- **Batch operations**: F2 installs all marked, F3 uninstalls all marked
- **Quick selection**: F6 marks all visible, F7 clears all marks

### Modal Overlays

- **Transparent background** - TUI remains visible
- **Small centered dialogs** - 50x13 for confirmations
- **Arrow key navigation** - Left/Right to select Yes/No
- **Visual focus** - Selected button highlighted in theme color

## 🛠️ Advanced Configuration

### Database Schema

Located at `%APPDATA%\Carapace\app.db`:

- **addons** - Main addon repository (name, repo_url, override_url, tags)
- **installed** - Tracks installed addons and their paths
- **settings** - Stores preferences and wiki revision
- **events** - Audit trail of all operations
- **addon_history** - Tracks changes over time

### Override URLs

When an addon's repository URL is wrong:

1. Press **F9** to edit addon
2. Set the **Override URL** field
3. This URL takes precedence over wiki URL
4. Protected from wiki sync overwrites

### Manual Edit Protection

Addons with `override_url` set are protected:
- Wiki sync only updates their tags
- Name, description, repo_url preserved
- Ensures your fixes aren't lost

**Smart Protection**: When you edit an addon's name or description without setting an override URL, the system automatically sets `override_url = repo_url` to protect your changes from being overwritten by wiki sync. The override field appears empty in the edit dialog when this auto-protection is active.

## 🐛 Troubleshooting

### Debug Logs

Every session creates `tui_debug_YYYYMMDD_HHMMSS.log`

Check latest log:
```powershell
Get-ChildItem tui_debug_*.log | Sort-Object LastWriteTime -Descending | Select-Object -First 1
```

### Common Issues

**Enter key doesn't work**
- Fixed: Uses worker thread for modal display

**Duplicate addons in list**
- Run `python fix_addon_duplicates.py`
- Merges duplicates, preserves tags

**Wiki sync overwrites my changes**
- Fixed: Sync now preserves override URLs
- Only updates unmodified addons

**Can't see which button is selected**
- Fixed: Focus state now shows with theme colors
- Arrow keys navigate between Yes/No

## 📊 Project Architecture

### Core Components

1. **Database Layer** (`carapace/db.py`)
   - Soft-delete pattern (deleted_at_utc)
   - JSON storage for tags
   - Override URL support

2. **Installer** (`carapace/installer.py`)
   - Git clone → `.repos/`
   - Junction creation → `AddOns/`
   - Zip fallback for non-Git sources
   - Subfolder detection for nested addons

3. **TUI** (`carapace/tui.py`)
   - Textual framework
   - Worker threads for async operations
   - Modal overlays with ModalScreen
   - Theme-aware styling

4. **Parser** (`carapace/parser.py`)
   - Wiki HTML parsing
   - Quirks handling for inconsistencies
   - Tag extraction and categorization

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Workflow

1. **Always check debug logs** before fixing issues
2. **Update PROJECT_STATUS.md** after changes
3. **Test with actual TurtleWoW** installation
4. **Follow soft-delete pattern** in database

## 📜 Recent Updates

- **Smart Wiki Sync** - Checks revision before updating
- **Manual Edit Protection** - Override URLs preserved
- **Small Modal Overlays** - Non-intrusive confirmations
- **Arrow Key Navigation** - For modal buttons
- **Right-Click Marking** - Alternative selection method
- **Duplicate Fix Script** - Cleans database duplicates
- **Live Addon Counter** - Shows filtered/total/marked

## 📈 Performance

- **858 addons** load in < 1 second
- **Wiki revision check** uses API (10KB vs 500KB+)
- **Batch operations** handle 100+ addons smoothly
- **Search** is instant with no delay

## 🙏 Credits

- Created for the **TurtleWoW** community
- Built with [Textual](https://github.com/Textualize/textual) TUI framework
- Theme: [Tokyo Night](https://github.com/enkia/tokyo-night-vscode-theme)
- Icons inspired by classic WoW

## 📋 Status

See [PROJECT_STATUS.md](docs/PROJECT_STATUS.md) for detailed progress.

**Current Version**: MVP (Functional)
- ✅ Core features complete
- ✅ Database management solid
- ✅ Git installation working
- ✅ Wiki sync with protection
- ✅ Modal overlays implemented
- 🔄 Profile support planned

---

*Slow and steady wins the raid* 🐢