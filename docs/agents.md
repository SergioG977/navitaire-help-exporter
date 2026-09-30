# Guide: specialist agents and orchestrator for Navitaire help

This guide explains how to use, adapt and create [Kiro](https://kiro.dev) agents that research the Navitaire help converted with `navhelp`. The repository already includes seven specialists and one orchestrator in `.kiro/agents/`.

## 1. How it works

```text
                  ┌──────────────────────────────┐
  question  ───▶  │ navitaire-help-orchestrator  │  reads knowledge/catalog.md, decides product and version
                  └──────────────┬───────────────┘
            delegates (in parallel when domains are independent)
   ┌──────────┬──────────┬───────┴──┬──────────┬──────────┬──────────┐
   ▼          ▼          ▼          ▼          ▼          ▼          ▼
 gonow    skyspeed   skyfare  skyschedule  newskies     gss    device-manager
   │          │          │          │          │          │          │
   └──── each searches only ./knowledge/<its family>/ and returns an answer + citations ────┘
                  ▼
     consolidated answer, by product and version, with evidence and gaps
```

Principles:

- **One corpus per specialist.** Each agent indexes only its own family, so products are never mixed.
- **Versions kept apart.** Each collection (`<family>/<hash>/`) is one distinct help file; `catalog.md` says which installed versions it covers. Agents must state which collection they used.
- **Evidence required.** Every statement carries the path of the cited topic; anything undocumented is reported as a gap.
- **Least privilege.** Specialists can only read and search: files, their knowledge base and the read-only tools of the `navhelp` MCP server. Writing, commands, web and every other MCP server are denied. The orchestrator reads the catalog, delegates to `navitaire-*` agents, and can scan and inspect installations. It can convert help only after you confirm.

## 2. Prerequisites

1. Kiro IDE installed.
2. `navhelp` installed in the repository's `.venv` **with the MCP extra** (`python -m pip install ".[mcp]"`, see the [README](../README.md)). The agents start `.venv\Scripts\navhelp.exe mcp` themselves.
3. The converted help **inside the git-ignored `knowledge` folder** of the repository:

   ```powershell
   navhelp convert --output .\knowledge --validate
   ```

   `knowledge/` is in `.gitignore`, and the safety check blocks any attempt to publish it.

## 3. Included agents

| Agent | Families indexed | Domain |
| --- | --- | --- |
| `navitaire-gonow` | `gonow` | Check-in, boarding, baggage, departure control |
| `navitaire-skyspeed` | `skyspeed` | Reservations, sales, payments, passenger servicing |
| `navitaire-skyfare` | `skyfare` | Fares, fare rules, markets, pricing |
| `navitaire-skyschedule` | `skyschedule` | Schedules, legs, seasons, routes, aircraft |
| `navitaire-newskies` | `newskies-management-console`, `ncs-rules`, `ncs-currency`, `ncs-notification` | Configuration, roles, permissions, reference data and plug-ins |
| `navitaire-gss` | `gss-management-console` | APIS/APPS, rules and government messaging |
| `navitaire-device-manager` | `device-manager` | Peripherals, scanners, printers, logs |
| `navitaire-help-orchestrator` | (none; reads `catalog.md` / `list_collections`) | Routing, consolidation, scan/inspect/convert |

### MCP tools per agent

| Agent | `navhelp` tools | Approval |
| --- | --- | --- |
| Specialists | `list_collections`, `search_topics`, `get_topic`, `get_toc`, `lookup_keyword`, `compare_topic`, `get_asset` | Pre-approved (read-only) |
| Orchestrator | `list_collections`, `scan_installations`, `inspect_installations` | Pre-approved (read-only) |
| Orchestrator | `convert_help`, `rebuild_search_index` | Asks every time |

Each agent declares its own server in `mcpServers` (with `includeMcpJson: false`), so it never inherits other MCP servers. Only the orchestrator's instance is started with `--allow-convert`. Its `requestTimeout` is 30 minutes because a full conversion takes a while.

## 4. Usage

1. Open the repository folder in Kiro. The agents in `.kiro/agents/` are loaded for that workspace.
2. Select the agent in chat (or mention it) and ask. Examples:
   - Orchestrator: *"In the latest New Skies version, which permission does an airport agent need for an operation in GoNow, and where is it configured?"*
   - Specialist: *"GoNow <version>: how do I perform <procedure>?"*
3. Check the citations: each path points to a file in `knowledge/` that you can open to verify.

After re-converting (new installation or new version), refresh the knowledge bases from the Kiro panel or restart the session: they are configured with `autoUpdate: false` so the index only changes when you decide.

### Installing the agents for every workspace (user level)

The agents in `.kiro/agents/` only exist in this repository. To use them from other workspaces, create a copy in `~/.kiro/agents/<name>.agent.md` and make two changes:

- Replace the relative paths (`.venv\Scripts\navhelp.exe`, `./knowledge`) with absolute paths to this repository.
- Remove the `knowledgeBase` resources, which are relative to the workspace. The MCP server takes their place.

Keep the name `Navitaire Help Orchestrator 🧭` for the user-level orchestrator if other agents delegate to it by that name. A user-level orchestrator may also keep a verified functional catalog outside the repository. If it does, allow `write` with `fs_write: ask`. The user-level copies contain profile paths, so never copy them back into the repository.

## 5. Anatomy of a specialist

Agents are Markdown files: YAML configuration in the front matter and the system prompt in the body. Fields used:

| Field | Use in this project |
| --- | --- |
| `name` | Identifier; must start with `navitaire-` so the orchestrator can invoke it. |
| `description` | What it covers and when to use it. Kiro and the orchestrator use it to choose the agent, so be specific. |
| `tools` | `read`, `knowledge` and the read-only `@navhelp/<tool>` MCP tools. |
| `allowedTools` | The same tools, pre-approved (they are read-only). |
| `includeMcpJson` / `includePowers` | `false`: the agent does not inherit the user's MCP servers or Powers. |
| `mcpServers` | The agent's own `navhelp` server: `.venv\Scripts\navhelp.exe mcp --knowledge ./knowledge`. |
| `resources` | `file://./knowledge/catalog.md` (loaded in full) and one `knowledgeBase` per family (indexed and searched on demand). |
| `permissions.rules` | `deny` for `fs_write`, `shell`, `web_fetch` and `web_search`. For MCP, a `deny` on `*` whose `exclude` lists only the read-only navhelp tools, so scan/inspect/convert and other servers stay blocked. In Kiro a `deny` always wins, which is why this uses `exclude` and not an `allow` on top of a blanket deny. |

Minimal example:

```markdown
---
name: navitaire-example
description: Documentation specialist for <Product> (<topics>). Researches only ./knowledge/<family> and cites every statement.
tools: ["read", "knowledge", "@navhelp/list_collections", "@navhelp/search_topics", "@navhelp/get_topic", "@navhelp/get_toc", "@navhelp/lookup_keyword", "@navhelp/compare_topic", "@navhelp/get_asset"]
allowedTools: ["read", "knowledge", "@navhelp/list_collections", "@navhelp/search_topics", "@navhelp/get_topic", "@navhelp/get_toc", "@navhelp/lookup_keyword", "@navhelp/compare_topic", "@navhelp/get_asset"]
includeMcpJson: false
includePowers: false
mcpServers:
  navhelp:
    command: ".venv\\Scripts\\navhelp.exe"
    args: ["mcp", "--knowledge", "./knowledge"]
resources:
  - file://./knowledge/catalog.md
  - type: knowledgeBase
    source: file://./knowledge/<family>
    name: ExampleHelp
    description: <family> help converted by navhelp
    indexType: best
    autoUpdate: false
permissions:
  rules:
    - capability: fs_write
      effect: deny
    - capability: shell
      effect: deny
    - capability: web_fetch
      effect: deny
    - capability: web_search
      effect: deny
    - capability: mcp
      match: ["*"]
      exclude: ["navhelp/list_*", "navhelp/search_*", "navhelp/get_*", "navhelp/lookup_*", "navhelp/compare_*"]
      effect: deny
---

You are the documentation specialist for <Product>. Your only source is ./knowledge/<family>/.
1. Identify the version with list_collections (family <family>); if none is given, use the highest and say so.
2. Search only that collection (search_topics / lookup_keyword with its collection_id) and read topics in full (get_topic).
3. Answer with: answer, evidence (path, title, section), version, inferences and gaps.
Do not invent behaviour, do not modify files, do not run commands.
```

Prompt best practices:

- Require separating **facts** (cited) from **inferences** (flagged) and **gaps**.
- State which topics belong to other products so the specialist hands them off instead of improvising.
- Ask for summaries with citations rather than long copies of documentation text.

## 6. Anatomy of the orchestrator

| Field | Value |
| --- | --- |
| `tools` | `read` (for the catalog) and `subagent` (to delegate). |
| `toolsSettings.subagent.availableAgents` | Explicit list of the seven specialists. The orchestrator cannot launch any other agent. |
| `permissions.rules` | `allow` for `subagent` with `match: ["navitaire-*"]` (specialists are read-only); `deny` for writing, commands, web and MCP. |

The prompt contains the routing table, the procedure (read catalog → decide product/version → split only when domains are independent → plan all delegations → consolidate) and the final format. Kiro runs subagents with isolated context and, when independent, in parallel.

If you prefer to approve each delegation manually, change `effect: allow` to `effect: ask` in the `subagent` rule.

## 7. Adding a new product

1. Add the family in `src/navitaire_help/families.py` (with its test) and re-convert.
2. Copy an existing specialist to `.kiro/agents/navitaire-<name>.md` and adjust `name`, `description`, the `knowledgeBase` and the prompt.
3. Add the agent to `availableAgents` and to the orchestrator's routing table.
4. Test it (section 8).

## 8. Testing the agents

Before relying on them, verify with read-only questions:

| Test | Expected result |
| --- | --- |
| Single-product question with a version | The orchestrator delegates to one specialist; the answer cites topics from that version's collection. |
| Two-product question | Delegation to two specialists; answer grouped by product. |
| Question without a version | The highest version in the catalog is used and stated. |
| Question about something undocumented | The answer says there is no evidence; nothing is invented. |
| Asking it to edit a file or run a command | It refuses (`deny` permissions). |
| Specialist question | The answer's citations come from `search_topics` / `get_topic` (visible in the tool calls). |
| Asking a specialist to convert or scan | It refuses: those tools are not in its `tools` list and are denied. |
| Asking the orchestrator to refresh GoNow help | It calls `convert_help` with `families: ["gonow"]` after you approve. |
| Comparing two versions | Each version is presented separately with its citations. |

Also check that no citation points outside `knowledge/` and that the cited paths exist.

## 9. Security

- The `knowledge/` folder contains proprietary documentation: do not commit it, do not share it outside authorised channels, and do not attach it to issues.
- Do not add `web`, `shell`, `write` or other MCP servers to these agents unless justified; if you do, use `ask` rules instead of `allow`.
- Do not start the specialists' `navhelp` server with `--allow-convert`; keep conversion in the orchestrator, behind `ask`.
- Avoid `tools: ["*"]` and `trustedAgents`.
- Carefully review any third-party skill or resource you add: it can influence the agent's behaviour.

## References

- Creating custom agents: <https://kiro.dev/docs/custom-agents/creating/>
- Configuration reference: <https://kiro.dev/docs/custom-agents/configuration-reference/>
- Subagents: <https://kiro.dev/docs/custom-agents/subagents/>
- Permissions: <https://kiro.dev/docs/permissions/>
