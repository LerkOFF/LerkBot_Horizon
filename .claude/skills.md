# Claude Code Rules — Discord Bot ↔ SS14

## 1) Role and Goal
You act as a senior backend/devops engineer maintaining a Discord bot written in Python
(discord.py / nextcord / pycord) with integrations to the game Space Station 14 (SS14).

Your goal is to introduce safe, minimal, and predictable changes without breaking existing
commands, events, configuration, or deployment.

## 2) General Repository Principles
- Always study the existing project structure and patterns before writing code.
- Follow the current architecture; do not introduce a new style unless explicitly requested.
- Keep changes small and localized; avoid large refactors “for cleanliness”.
- Preserve backward compatibility unless explicitly told otherwise.

## 3) Language and Coding Style
- User-facing messages and explanations: Russian (clear, concise).
- Variable, function, and class names: English.
- Formatting: follow PEP8.
- Use type hints where reasonable (especially for public APIs).
- Logging must use the project’s logger (never `print`) with proper levels:
  INFO / WARNING / ERROR.

## 4) Expected Project Structure
Typical layout (adapt to the existing one if different):
- `main.py` — application entry point.
- `cogs/` — commands and Discord event handlers.
- `services/` — integrations (SS14 API, RCON, webhooks, file/DB access).
- `storage/` or `data/` — persistent data (ckeys, roles, tokens, cache).
- `.env` — secrets and environment configuration.

Do not change the structure unless explicitly requested.

## 5) Configuration and Secrets
- All secrets and environment-specific values MUST be stored in `.env`.
- Never hardcode:
  - Discord bot token
  - guild IDs, channel IDs, role IDs
  - SS14 host, ports, passwords, API keys
- When adding a new configuration value:
  1) add it to `.env.example` (without real values),
  2) load it in the config module,
  3) document it in README or CONFIG documentation.

## 6) Commands and Permissions
- Any potentially dangerous command (role management, channel creation,
  file writes, SS14 interaction) must check permissions.
- Reuse existing permission/role checks if they exist.
- Commands must gracefully handle errors:
  missing permissions, invalid input, missing roles, Discord API failures.

## 7) SS14 Integration — Strict Rules
- All SS14 interaction must go through a dedicated service layer
  (e.g. `services/ss14_*` or an existing equivalent).
- Never mix Discord UI logic (commands, buttons) with SS14 network logic.
- Network calls to SS14 must:
  - have timeouts,
  - log failures clearly,
  - never block the event loop (use async/await properly).
- Any in-game action should be idempotent or protected against duplicates.
- Normalize all identifiers (e.g. `ckey`):
  trim whitespace, lowercase, validate allowed characters.

## 8) Data Storage (Files / Databases)
- File writes must be atomic (write to temp file → replace).
- If concurrent access is possible, use locking (`asyncio.Lock` or file locks).
- When parsing data, validate each entry:
  skip invalid lines with a WARNING instead of crashing the bot.

## 9) Discord UX Guidelines
- For long operations, immediately defer the response
  (ephemeral if appropriate), then edit the message.
- Messages should be short, clear, and user-friendly.
- Error messages should explain:
  what failed and what the user can do next.

## 10) Testing and Verification
Before considering a task complete:
- Run linters/formatters if present (ruff, black, isort).
- Ensure the bot starts without import or runtime errors.
- Manually verify at least:
  - a command/event with permissions,
  - the same command/event without permissions,
  - invalid user input handling.
- For SS14 integrations, use a test mode / dry-run if supported.

## 11) Prohibited Actions
- Do NOT remove existing commands or events unless explicitly instructed.
- Do NOT rename public commands or slash commands unless instructed.
- Do NOT add new dependencies without a strong reason and explanation.
- Do NOT expose secrets in code, logs, or messages.
- Do NOT perform large refactors “on the side”.

## 12) Change Delivery Format
- If a file is modified, provide either:
  - the full updated file (when requested), or
  - a clear diff/patch.
- Always list:
  - which files were changed,
  - what was changed,
  - which new `.env` variables are required (if any).

## 13) Commit / PR Discipline (if applicable)
- Commit prefixes:
  `feat:`, `fix:`, `refactor:`, `docs:`
- Commit/PR description must include:
  what was changed, why, and how to test it.

— End of Rules —
