# navitaire-help-exporter

A command-line tool (`navhelp`) that **finds the CHM help installed with Navitaire applications** (New Skies, GoNow, Government Security and Device Manager), **identifies which product and version each file belongs to**, and **converts it to structured Markdown**, ready to read in any editor or to use as a knowledge base for AI agents.

All processing is local. The tool sends nothing to the Internet, and this repository does not contain, and must never contain, any Navitaire documentation.

---

## Contents

1. [What problem it solves](#what-problem-it-solves)
2. [Key concepts](#key-concepts)
3. [Security and confidentiality](#security-and-confidentiality)
4. [Requirements](#requirements)
5. [Step-by-step installation](#step-by-step-installation)
6. [Quick start](#quick-start)
7. [Commands in detail](#commands-in-detail)
8. [Configuration](#configuration)
9. [Where it searches and what it excludes](#where-it-searches-and-what-it-excludes)
10. [Recognised products](#recognised-products)
11. [How the product is identified](#how-the-product-is-identified)
12. [How the version is determined](#how-the-version-is-determined)
13. [Output structure](#output-structure)
14. [MCP server](#mcp-server)
15. [Using it with AI agents](#using-it-with-ai-agents)
16. [Troubleshooting](#troubleshooting)
17. [Development](#development)
18. [Licence and attribution](#licence-and-attribution)

---

## What problem it solves

Navitaire desktop applications ship their manuals as **CHM** files (*Compiled HTML Help*, the classic Windows help format opened with F1). These files:

- are spread across dozens of installation folders, often **duplicated** (the same help copied into every plug-in);
- exist in **several versions** of the same product side by side (for example, several New Skies versions installed in parallel);
- have names that do not always say which product they belong to or which version they document;
- are hard to search and cannot be read by modern tools or AI agents.

`navhelp` solves this in four steps:

1. **Discovers** every `.chm` under `C:\Program Files (x86)\Navitaire` (except excluded folders).
2. **Groups** duplicates by content (SHA-256 hash): each distinct help file is processed only once.
3. **Classifies** each help file (which product it is) and **resolves the installed version** from the Windows registry and the executables, always recording the evidence used.
4. **Converts** each help file into a Markdown folder with a table of contents, keyword index, images, metadata and diagnostics, plus an overall **catalog**.

## Key concepts

| Term | Meaning |
| --- | --- |
| **Family** (`family_id`) | Stable identifier of the kind of help: `gonow`, `skyspeed`, `skyfare`… |
| **Product** | Display name of the product: *GoNow*, *SkySpeed Reservation Manager*, *Fare Manager*… |
| **Collection** | One specific help file, identified by the hash of its content. If two installed versions ship exactly the same CHM, they share a collection. |
| **Installed version** | Version of the application the CHM is installed with (e.g. `9.1.0.200`). Comes from the registry or the executable. |
| **Version stated by the help** | Version mentioned inside the help text itself. Reported separately because it often differs from the installed one (the help may be older). |
| **Evidence** | Each piece of data used to classify or version (file name, internal title, registry entry…). Stored in `manifest.json` so the result can be audited. |

## Security and confidentiality

Navitaire documentation is Amadeus property. The tool is designed so it cannot leak:

- **Read-only** on installations: it never writes to `C:\Program Files (x86)\Navitaire` and rejects an output folder inside the search roots.
- **No network**: no Internet calls, no telemetry.
- **Output cannot end up in Git by accident**: `navhelp convert` refuses to write inside a Git repository unless the folder is git-ignored (for example `.\knowledge`, already in `.gitignore`).
- **Personal paths hidden**: the profile folder (`C:\Users\<user>`) is replaced with `~` in manifests and messages. With `--hide-roots` the roots are hidden too.
- **No internal e-mail addresses**: the `mailto:` "Send Feedback" links are removed from topics.
- **Automatic check before publishing**: `scripts/check_repo_safety.py` blocks CHM/HHC/HHK/SAZ files, executables, converted Markdown, profile paths, tokens and keys. It runs on every commit (hook) and in continuous integration.
- **Safe extraction**: 7-Zip is invoked without a shell, and no extracted file may land outside the temporary folder. Temporary files are deleted when done.
- **Pinned dependencies**: exact versions in `pyproject.toml`.

Rules for anyone using the repository:

1. Never commit `.chm` files, output folders or screenshots of the documentation.
2. Share converted documentation only through authorised internal channels.
3. Keep the repository **private** and grant access only to authorised Amadeus staff.

## Requirements

| Requirement | Details |
| --- | --- |
| Windows 10/11 | Version detection uses the Windows registry and version resources. On other systems conversion works, but versions will be *inferred* or *unknown*. |
| Python 3.11 or later | <https://www.python.org/downloads/> (tick *Add python.exe to PATH*). Check with `py --version`. |
| 7-Zip | <https://www.7-zip.org/>. Looked up in `C:\Program Files\7-Zip\7z.exe`, `C:\Program Files (x86)\7-Zip\7z.exe` and on `PATH`. |
| Git | To clone the repository. |
| Permissions | Read access to `C:\Program Files (x86)\Navitaire` is enough. Administrator rights are not needed. |
| Disk space | About 150 MB to convert all help files of a typical installation. |

## Step-by-step installation

Open **PowerShell** and run:

```powershell
# 1. Clone (you need access to the private repository)
git clone https://github.com/SergioG977/navitaire-help-exporter.git
Set-Location navitaire-help-exporter

# 2. Create an isolated virtual environment
py -m venv .venv
.\.venv\Scripts\Activate.ps1
# If PowerShell blocks the script:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 3. Install the tool
python -m pip install --upgrade pip
python -m pip install .

# 4. Check
navhelp --version
navhelp families
```

To query the help from an AI chat through the local MCP server (see [MCP server](#mcp-server)), install the optional extra:

```powershell
python -m pip install ".[mcp]"
```

To contribute code, also install the development tools and the safety hook:

```powershell
python -m pip install -e ".[dev]"
.\scripts\install-hooks.ps1
```

Each time you open a new PowerShell window, activate the environment with `.\.venv\Scripts\Activate.ps1` (or call `.\.venv\Scripts\navhelp.exe` directly).

## Quick start

```powershell
# Which help files are installed? (fast, extracts nothing)
navhelp scan

# Which product and version is each one?
navhelp inspect

# Convert everything to Markdown in %USERPROFILE%\NavitaireHelp and validate the result
navhelp convert --validate

# Open the generated catalog
notepad "$HOME\NavitaireHelp\catalog.md"
```

Illustrative output of `navhelp inspect` (fictitious versions):

```text
FAMILY                         CLASS      INSTALLED VERSIONS           VERSION     HELP STATES FILE
device-manager                 classified 9.2.0.10                     confirmed   -           DeviceManager.chm
gonow                          classified 9.1.0.100                    confirmed   9.1.0       GoNow.chm
skyspeed                       classified 9.3.0.200                    confirmed   9.3.0       SkySpeedHelp.chm
skyspeed                       classified 9.1.0.200, 9.2.0.200         confirmed   8.0.0       SkySpeedHelp.chm
```

The last row shows why collections and versions are kept apart: two installed versions can ship exactly the same help, and that help's text can mention an older version.

## Commands in detail

Every command accepts `--config FILE` and `-v/--verbose`. `navhelp <command> --help` shows the help for each one.

### `navhelp families`

Lists the recognised families, their product and their functional domain.

### `navhelp scan`

Finds `.chm` files without opening them and shows how many there are, how many are distinct, and where each copy is.

| Option | Effect |
| --- | --- |
| `--root DIR` | Root folder to walk (repeatable). Replaces the default root. |
| `--exclude PATH` | Extra folder to skip, relative to the root (repeatable). E.g. `--exclude NewSkies\R9.1`. |
| `--no-default-excludes` | Do not skip `ConfigCaptain` and `NavitaireTE`. |
| `--chm FILE` | Process a specific CHM instead of searching (repeatable). |
| `--hide-roots` | Show `<root>` instead of the root path. |
| `--json` | JSON output. |

### `navhelp inspect`

Besides searching, reads the internal metadata of each CHM (partial extraction into a temporary folder) and shows family, classification status, installed versions, version status and the version stated by the help. With `-v` it shows all the evidence; with `--json` it returns each collection's manifest.

### `navhelp convert`

Converts the help files found. Accepts the `scan` options plus:

| Option | Effect |
| --- | --- |
| `-o, --output DIR` | Output folder (default `%USERPROFILE%\NavitaireHelp`). |
| `--family ID` | Convert only this family (repeatable). E.g. `--family gonow --family skyspeed`. |
| `--include-unknown` | Also convert unrecognised CHM files (family `unknown`). |
| `--force` | Re-convert even if the collection is already up to date. |
| `--validate` | Run `validate` when finished. |
| `--seven-zip EXE` | Explicit path to `7z.exe`. |
| `--allow-unignored-output` | Allow output inside a Git repository folder that is not git-ignored. **Not recommended.** |

Conversion is **incremental**: if a collection already exists with the same tool version and the same installed versions, it is reported as `unchanged` and only its list of locations is refreshed. Each collection is first written to a temporary `.<hash>.partial` folder and published at the end, so an interruption never leaves a half-written collection.

### `navhelp validate [FOLDER]`

Checks an output folder: complete manifests, correct topic count, front matter present and consistent with its collection, consistent catalog, and no user profile paths. Broken links in the source and unconfirmed versions are reported as warnings.

### `navhelp mcp`

Runs the local MCP server over stdio (requires the `mcp` extra). It is started by the MCP client (Kiro, VS Code, etc.), not by hand. See [MCP server](#mcp-server).

| Option | Effect |
| --- | --- |
| `-k, --knowledge DIR` | Converted folder to serve (default: `conversion.output` from the configuration). |
| `--allow-convert` | Expose the `convert_help` tool, which writes into that folder. Off by default. |

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | A help file failed or validation found errors. |
| `2` | Usage or configuration error (7-Zip not found, unsafe output, missing file…). |

## Configuration

The defaults work on a standard installation. To change them, copy the example (`navhelp.toml` is git-ignored):

```powershell
Copy-Item config\navhelp.example.toml navhelp.toml
navhelp convert --config navhelp.toml
```

```toml
[discovery]
roots = ["C:\\Program Files (x86)\\Navitaire"]
exclude = ["ConfigCaptain", "NavitaireTE"]
follow_links = false

[conversion]
output = "~\\NavitaireHelp"
seven_zip = ""
include_unknown = false
```

Command-line options take precedence over the file. `~` and environment variables (`%USERPROFILE%`) are supported.

## Where it searches and what it excludes

- Default root: `C:\Program Files (x86)\Navitaire`.
- **All subfolders are walked recursively** (`GovernmentSecurity`, `NAV1`, `NewSkies` and any other that appears).
- `ConfigCaptain` and `NavitaireTE` are skipped entirely (case-insensitive comparison).
- Symbolic links and NTFS junctions are not followed, so the walk never leaves the root.
- Folders that cannot be read are reported as warnings and the walk continues.

No installation paths are hard-coded beyond this root: the tool finds CHM files wherever they are below it.

## Recognised products

| Family | Product | Domain | Typical file |
| --- | --- | --- | --- |
| `gonow` | GoNow | Check-in, boarding, baggage and departure control | `GoNow.chm` |
| `skyspeed` | SkySpeed Reservation Manager | Reservations, sales and passenger servicing | `SkySpeedHelp.chm` |
| `skyfare` | Fare Manager | Fares, fare rules, markets and pricing | `SkyFareHelp.chm` |
| `skyschedule` | Schedule Manager | Schedules, legs, routes and equipment | `SkyScheduleHelp.chm` |
| `newskies-management-console` | New Skies Management Console | System configuration, roles, permissions and reference data | `Navitaire.NewSkies.UI.Win.SkyManagerHelp.chm` |
| `gss-management-console` | GSS Management Console | Government Security Services: APIS/APPS, rules and government messaging | `Navitaire.GovernmentSecurity.GSSManagementConsole.Help.chm` |
| `device-manager` | Device Manager | Peripherals, scanners, printers, simulators and logs | `DeviceManager.chm` |
| `ncs-rules` | Rules Management | Management Console rules plug-in | `Rules.chm` |
| `ncs-currency` | Currency Management | Management Console currency plug-in | `Currency.chm` |
| `ncs-notification` | Notification Management | Management Console notification plug-in | `Notification.chm` |

To add a new family, add an entry in `src/navitaire_help/families.py` with its patterns, and a test in `tests/test_classification_versioning.py`.

## How the product is identified

Each family defines patterns (regular expressions) that are compared with several signals. Each matching signal adds a weight:

| Signal | Weight | Example |
| --- | --- | --- |
| Compiled CHM title (`#SYSTEM`) | 4 | "GoNow Agent Help" |
| File name | 3 | `SkyFareHelp.chm` |
| Welcome page title | 2 | "Welcome to Device Manager" |
| Contents file name (`.hhc`) | 2 | `SkyScheduleHelp.hhc` |
| Installation folder | 1 | `...\Client Suite\Fare Manager` |

- Below 3 points the help is `unknown` and is not converted (unless `--include-unknown`).
- If the second-best family is within 2 points, the status is `ambiguous` and the alternative is shown (`runner_up`).
- The full evidence is stored in `manifest.json → classification.evidence`.

## How the version is determined

The file name is never used as a version. Sources, from most to least reliable:

1. **Windows registry** (read-only): Navitaire/Amadeus *Uninstall* entries whose `InstallLocation` contains the CHM. `DisplayVersion` is used or, when empty, the version inside `DisplayName` (as with *NewSkies Client Suite*).
2. **Product executable** next to the CHM or in parent folders within the installation (`GoNow.exe`, `UI.Win.SkySpeed.exe`, `DeviceManager.exe`…), reading `ProductVersion`. The build suffix (`+commit`) is dropped and the vendor must be Navitaire or Amadeus.
3. **Version-like folder name** (`R9.1`, `9.1.0.100`): only as an *inferred* version.

| Status | Meaning |
| --- | --- |
| `confirmed` | Registry and/or executable agree. |
| `inferred` | Only path hints are available. |
| `conflicting` | Reliable sources disagree; none is chosen. |
| `unknown` | No evidence. |

The **version stated by the help** (`document_version`) is extracted separately from the contents file, the title or the welcome page. It is informational: a help file may mention an earlier version than the application it is installed with.

## Output structure

```text
NavitaireHelp/
├── catalog.md                      # table of all collections (start here)
├── catalog.json                    # the same, for tools
└── <family>/
    └── <hash-12>/                  # one collection = one distinct CHM
        ├── README.md               # summary: product, versions, entry points
        ├── manifest.json           # metadata, evidence, locations, statistics
        ├── toc.md / toc.json       # original table of contents
        ├── topics/                 # one .md per topic, mirroring the CHM's internal structure
        ├── assets/                 # referenced images and attachments
        ├── indexes/
        │   ├── topics.json         # title, path, breadcrumbs, headings, keywords
        │   ├── keywords.json       # original keyword index
        │   └── keywords.md
        └── diagnostics/
            ├── links.json          # broken links, unresolved IDs, links to other help files
            └── conversion.json     # name collisions, failed topics, orphan TOC entries
```

Each topic starts with YAML front matter:

```yaml
---
title: "<topic title>"
collection_id: "<family>-<12-character hash>"
family_id: "<family>"
product: "<product>"
installed_versions: ["<installed version>"]
document_version: "<version stated by the help>"
source_chm: "<file>.chm"
source_topic: "<internal path>.html"
toc_path: ["<chapter>", "<topic title>"]
keywords: ["<keyword from the original index>"]
---
```

Conversion details:

- The help viewer template is removed (header, "Send Feedback", repeated footers and copyright); collapsible sections with content are kept.
- Internal links are rewritten as relative paths between `.md` files, including anchors (`#section`). Differences in case, spaces, hyphens and underscores are tolerated.
- Links that cannot be resolved become plain text and are recorded in `diagnostics/links.json`. Most are defects in the original CHM (images not included, topic IDs the authoring tool never resolved).
- If two topics would produce the same file, the second is renamed (`__2`) and the collision is recorded.

## MCP server

`navhelp mcp` exposes the converted help, and the navhelp operations, as [Model Context Protocol](https://modelcontextprotocol.io) tools. That lets you search, read, compare and convert from an AI chat. It is a local stdio process. It opens no port and makes no network calls.

| Tool | Kind | What it does |
| --- | --- | --- |
| `list_collections` | read | Collections with family, product and installed versions. `version="latest"` keeps the highest per family. |
| `search_topics` | read | Ranked full-text search (SQLite FTS5) over titles, headings, keywords, breadcrumbs and body. Filters: `family`, `version` (prefix or `latest`), `collection_id`. Supports `"phrases"` and `prefix*`. |
| `get_topic` | read | One topic as Markdown with its metadata. Accepts a citation, `topics/x.md` or the original `x.html`. Can return one `section`. Long topics are paged (`next_offset`). |
| `get_toc` | read | Original table of contents, or the subtree `under` an entry (`"Tasks > Boarding"`). |
| `lookup_keyword` | read | Original CHM keyword index (F1 index). |
| `compare_topic` | read | Unified diff of the same topic across installed versions. |
| `get_asset` | read | Returns a referenced image so the model can see it. |
| `scan_installations` | read | Same as `navhelp scan`. |
| `inspect_installations` | read | Same as `navhelp inspect`; `evidence=true` adds the reasons. |
| `rebuild_search_index` | cache | Rebuilds the search cache. This is rarely needed because it rebuilds itself when the catalog changes. |
| `convert_help` | write | Same as `navhelp convert --validate`, into the served folder only. Only exposed with `--allow-convert`. |

Every result carries a `citation` (`<family>/<hash>/topics/...md`) and the collection's `installed_versions`.

### Setting it up

1. Install the extra: `python -m pip install ".[mcp]"`.
2. Convert the help: `navhelp convert --output .\knowledge --validate` (or later, `convert_help` from the chat).
3. The agents in `.kiro/agents/` already start the server themselves (see [docs/agents.md](docs/agents.md)). Nothing else is needed for them.
4. **Manual step: register the server for Kiro's default chat.** This is only needed if you want to use the tools outside the `navitaire-*` agents. Create `.kiro/settings/mcp.json` in the repository folder with the content below, or copy the example:

   ```powershell
   New-Item -ItemType Directory -Force .kiro\settings | Out-Null
   Copy-Item config\mcp.example.json .kiro\settings\mcp.json
   ```

   `.kiro/settings/mcp.json` must contain:

   ```json
   {
     "mcpServers": {
       "navhelp": {
         "command": ".venv\\Scripts\\navhelp.exe",
         "args": ["mcp", "--knowledge", "./knowledge", "--allow-convert"],
         "disabled": false,
         "autoApprove": [
           "list_collections",
           "search_topics",
           "get_topic",
           "get_toc",
           "lookup_keyword",
           "compare_topic",
           "get_asset",
           "scan_installations",
           "inspect_installations"
         ]
       }
     }
   }
   ```

   | Field | Value and why |
   | --- | --- |
   | `navhelp` | Server name. Keep it: the agents' permission rules match `navhelp/*`. |
   | `command` | `navhelp.exe` from the repository's virtual environment. JSON needs doubled backslashes. |
   | `args` | `mcp` subcommand, the folder to serve (`--knowledge`) and `--allow-convert` to expose `convert_help`. Remove `--allow-convert` for a strictly read-only server. |
   | `disabled` | `false` to start the server. Set `true` to turn it off without deleting the entry. |
   | `autoApprove` | Read-only tools that run without asking. `convert_help` and `rebuild_search_index` are left out on purpose, so Kiro asks before each call. Do not use `"*"`. |

   If the file already exists with other servers, add only the `"navhelp": { ... }` entry inside `mcpServers`; do not overwrite it.

5. Check it: open the **MCP Servers** view in the Kiro panel. `navhelp` should show as connected with 11 tools (10 without `--allow-convert`). Then ask in chat, for example: *"Use navhelp list_collections"*. If it fails, the view shows the server log. Kiro reloads the file when you save it.

**Absolute paths.** The relative paths above assume Kiro starts the server from the repository folder. If the server does not start, or reports that `catalog.json` is missing, use absolute paths:

```json
"command": "C:\\<path>\\navitaire-help-exporter\\.venv\\Scripts\\navhelp.exe",
"args": ["mcp", "--knowledge", "C:\\<path>\\navitaire-help-exporter\\knowledge", "--allow-convert"]
```

An `mcp.json` with absolute paths under your profile (`C:\Users\<you>\...`) is machine-specific. Do not commit it: the safety check blocks profile paths. Keep the relative version in Git, or put the absolute one in your user configuration (`~/.kiro/settings/mcp.json`), which applies to every workspace. The same change applies to the `mcpServers` block of each agent in `.kiro/agents/`.

For other MCP clients (VS Code, Claude Desktop…) use the same `command` and `args` with absolute paths, in the format that client expects.

### Security

- Every path argument is confined to its collection folder. Traversal (`..`), absolute paths and other folders are rejected. `get_asset` only serves files under `assets/`.
- Search queries are turned into quoted FTS5 terms, so the query language cannot be abused.
- `convert_help` is off unless `--allow-convert` is given. It can only write into the served folder and applies the same checks as `navhelp convert`: never inside an installation root, and never inside Git unless git-ignored.
- User profile paths are redacted from results.
- The search cache lives in `<knowledge>\.navhelp-index\`, inside the git-ignored folder. If the folder is read-only, the index is kept in memory.
- Whatever the tools return reaches the language model you use, exactly as with the agents' knowledge bases. Use only models and clients approved for this documentation.

## Using it with AI agents

The repository includes [Kiro](https://kiro.dev) agents in `.kiro/agents/`: one specialist per product and an orchestrator that delegates to them. Specialists research through the MCP server's read-only tools, with the knowledge base as a fallback. The orchestrator can also scan, inspect and, with confirmation, convert. To use them, convert the help into the git-ignored `knowledge` folder and install the `mcp` extra:

```powershell
python -m pip install ".[mcp]"
navhelp convert --output .\knowledge --validate
```

The complete guide to creating, adapting and testing them is in [docs/agents.md](docs/agents.md).

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `7-Zip not found` | Install 7-Zip or give its path with `--seven-zip "D:\Tools\7z.exe"`. |
| `Output folder ... is inside the Git repository` | Choose a folder outside the repository or use `.\knowledge`. |
| `Output must not be inside a discovery root` | Do not write inside `C:\Program Files (x86)\Navitaire`. |
| `Root not found` | The root does not exist on this machine: use `--root`. |
| `Access denied: ...` | Your user cannot read that folder; it is skipped and the walk continues. |
| Version `inferred` or `unknown` | No registry entry or recognisable executable. Check the evidence with `navhelp inspect -v`. |
| Family `unknown` | Unrecognised CHM. Check with `inspect -v`; convert it with `--include-unknown` or add the family. |
| Many broken links | See `diagnostics/links.json`; usually the target does not exist in the original CHM. |
| Converter changes not applied | The collection is `unchanged`: use `--force`. |
| `the MCP extra is not installed` | `python -m pip install ".[mcp]"`. |
| MCP server does not start in Kiro | Check the MCP panel logs. If the server was started from another folder, use absolute paths in `command` and `--knowledge`. |
| MCP search results look stale | Call `rebuild_search_index` or delete `knowledge\.navhelp-index`. |
| Garbled characters | Encoding not declared in the original HTML; open an issue with the topic name (without attaching its content). |

## Development

```powershell
python -m pip install -e ".[dev]"
.\scripts\install-hooks.ps1          # safety check before every commit
ruff check src tests scripts          # style and static analysis
pytest                                # tests (synthetic data only)
python scripts\check_repo_safety.py   # manual safety check
```

Code layout (`src/navitaire_help/`):

| Module | Responsibility |
| --- | --- |
| `cli.py` | Commands and options. |
| `config.py` | Defaults and TOML file. |
| `discovery.py` | Recursive search, exclusions and hashing. |
| `extraction.py` | Safe 7-Zip invocation. |
| `chm_metadata.py` | Reading `#SYSTEM`, `.hhc` and `.hhk`. |
| `families.py` / `classification.py` | Known families and evidence-based classification. |
| `versioning.py` | Registry, executable version resources and version resolution. |
| `markdown.py` | HTML → Markdown conversion and template cleanup. |
| `converter.py` | Building a collection: topics, assets, indexes, diagnostics. |
| `pipeline.py` | Orchestration, manifests and catalog. |
| `validate.py` | Output validation. |
| `knowledge.py` | Read-only query engine over a converted folder (catalog, FTS5 search, topics, TOC, keywords, diffs). |
| `mcp_server.py` | MCP server (`navhelp mcp`) exposing `knowledge.py` and the navhelp operations. |
| `safety.py` | Output folder protection and path redaction. |

Rules:

- Tests use **synthetic fixtures only**. Never add real Navitaire content, not even fragments.
- When reporting an issue, refer to the topic by its file name; do not paste its content.
- Pin exact versions when adding dependencies.

## Licence and attribution

Distributed under the MIT licence (see [LICENSE](LICENSE)). Part of the code derives from [DTDucas/chm-converter](https://github.com/DTDucas/chm-converter) (MIT); details are in [NOTICE](NOTICE).

The licence covers only the code of this tool. The Navitaire documentation it processes remains the property of its owners and is subject to their terms of use.
