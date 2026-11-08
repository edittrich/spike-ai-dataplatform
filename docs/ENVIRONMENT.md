# ENVIRONMENT

Template for the local development environment of a Python project with a Supabase database and Docker. Project-specific names are placeholders (`<PROJECT_NAME>`, `<package>`, …).

**How to read this document:** §2 describes the host. You set it up once per machine, and all projects share it. §3 to §9 describe a single project. §9 is the step-by-step checklist that Claude follows in a new project.

**Placeholders**

| Placeholder | Meaning | Example |
|---|---|---|
| `<PROJECT_NAME>` | Project and repository name, lower case with `-` | `my-project` |
| `<package>` | Python package name: `<PROJECT_NAME>` with `_` instead of `-` | `my_project` |
| `<module>` | Module inside the package, for example the entry point of a service | `api` |
| `<service>` | Service name in `docker-compose.yml` | `api` |
| `<port>` | Port of the project's own service | `8000` |
| `<OWNER>/<REPO>` | GitHub owner and repository | `edittrich/my-project` |
| `<X.Y>` | Latest stable Python minor version | `3.15` |
| `<PATH>` | Folder that holds the master copy of this file | `~/templates` |
| `<latest-…>`, `<current-…>` | Latest version when you write the file. Look it up with `gh api repos/<org>/<repo>/releases/latest -q .tag_name` | `v7` |

---

## 1. Purpose and scope

A fully local development environment:

- **Python package in src layout**, managed with **uv**. Code runs directly on the host (`uv run`) or as a service in a container.
- **PostgreSQL** through the **Supabase CLI**. It runs outside Docker Compose.
- **Docker Compose** for the project's own containerized services.
- **Ollama** as the local LLM backend on the host.
- **pytest + ruff** for testing, linting and formatting, **GitHub Actions** as CI that runs the same checks.
- **GitHub** as the remote with a pull-request workflow, driven by the **gh CLI** (create repo, PRs, CI status, merge).

All services are only reachable on `127.0.0.1`. The only exception is Ollama: it listens on `0.0.0.0` on purpose, so that containers can reach it (see §6). All configuration comes from environment variables and `.env`.

### Starting a new project with Claude Code

This file is the working basis for Claude Code. It lives in every new project as `docs/ENVIRONMENT.md`, and Claude sets up the project according to it.

**Requirement:** The host meets §2. `check-dev-tools.sh` reports `OK` for every tool, and you are logged in to `gh`, `claude` and `ctx7`.

1. Create the project folder and copy this file into its `docs` folder. You have to do this by hand, because Claude is started inside this folder afterwards:
   ```bash
   mkdir -p ~/Documents/workspaces/git/<PROJECT_NAME>/docs
   cp <PATH>/ENVIRONMENT.md ~/Documents/workspaces/git/<PROJECT_NAME>/docs/
   cd ~/Documents/workspaces/git/<PROJECT_NAME>
   ```
2. Start Claude Code in the project folder (`claude` in the terminal, or open the folder in VS Code). On the first start, Claude asks whether you trust the folder. Confirm it.
3. Ask Claude to set up the project and give it the placeholder values, for example:
   ```text
   Set up this project according to docs/ENVIRONMENT.md. Work through the
   bootstrap checklist in §9 from step 2 (including git init) up to and
   including step 10.
   Placeholders: <PROJECT_NAME>=my-project (package: src/my_project),
   <OWNER>/<REPO>=edittrich/my-project. Service: my_project.api on port
   8000 (or: no service yet). Write CLAUDE.md from the template in §8 and
   reference docs/ENVIRONMENT.md in it.
   Ask before you push anything or create a GitHub repository.
   ```
4. When the scaffold is in place, run `/init` in Claude Code. Because `CLAUDE.md` already exists, `/init` does not overwrite it. It suggests improvements based on the actual project. Accept the ones that fit.
5. Restart Claude Code so that it loads `.claude/settings.json` (permissions, hooks) and `.mcp.json`. On this start, approve the MCP server `supabase-local` once.
6. Let Claude create the GitHub repository and the first PR (§9, steps 11 to 13). Claude runs this with `gh` after you have confirmed it.

After that, `docs/ENVIRONMENT.md` is the reference for the environment, and `CLAUDE.md` holds the project-specific instructions. When the environment changes, update this file and copy it to the other projects.

---

## 2. Requirements

### Principles

- **Versions**: Every tool runs in its **current LTS version**. If there is no LTS line, use the **latest stable version**. This document does not record fixed version numbers.
- **Installed globally**: All CLIs are installed once on the host for all projects, not per project. Tools whose version each project pins itself (pytest, ruff, pre-commit) are also in the project's dev group and run there through `uv run`.
- **Checked regularly**: Every time Claude Code starts, a script checks automatically whether all global CLIs are at the latest (LTS) version (see "Version check" below).
- **CLI before MCP**: If a task can be done with a CLI or with an MCP server, use the CLI (`gh`, `supabase`, `psql`, `docker`, `uv`, `ctx7`, …). Use an MCP server only when there is no suitable CLI.

### Operating system and IDE

| Component | Version channel | Installation / update |
|---|---|---|
| Ubuntu | current LTS | `sudo do-release-upgrade` (`Prompt=lts` in `/etc/update-manager/release-upgrades`) |
| VS Code | latest stable version | Install the `.deb`, which also sets up the Microsoft APT repository: `echo "code code/add-microsoft-repo boolean true" \| sudo debconf-set-selections && wget -qO /tmp/code.deb 'https://go.microsoft.com/fwlink/?LinkID=760868' && sudo apt install /tmp/code.deb`. After that, updates come with `sudo apt upgrade`. No Snap or Flatpak installation in parallel |
| Claude Code extension (`anthropic.claude-code`) | latest version | VS Code Marketplace, automatic updates |
| Python extension (`ms-python.python`) | latest version | Python support, debugger, test explorer for pytest. `code --install-extension ms-python.python` |
| Ruff extension (`charliermarsh.ruff`) | latest version | Shows ruff findings directly in the editor. `code --install-extension charliermarsh.ruff` |

On Linux, containers need `extra_hosts: host-gateway` to reach services on the host (see §6).

### Globally installed CLIs

| CLI | Purpose | Version channel | Installation / update |
|---|---|---|---|
| `uv` | The only Python tool: installs Python, manages `.venv` and dependencies (`pyproject.toml` + `uv.lock`), runs commands (`uv run`) and installs global Python CLIs (`uv tool`). No pip, no pyenv | latest | Install with `curl -LsSf https://astral.sh/uv/install.sh \| sh`, update with `uv self update` |
| `ruff` | Linter and formatter for ad-hoc use outside projects. Inside a project, the version from the dev group runs (`uv run ruff`) | latest | `uv tool install ruff`, update with `uv tool upgrade ruff` (all uv tools: `uv tool upgrade --all`). The binaries go to `~/.local/bin` |
| `pre-commit` | Git hooks, for ad-hoc use. Inside a project, the version from the dev group runs (`uv run pre-commit`) | latest | `uv tool install pre-commit`, update with `uv tool upgrade pre-commit`. `pre-commit install` writes the path of the Python interpreter into `.git/hooks/pre-commit`. After the installation changes, run `pre-commit install` again in every repository |
| `nvm` | The only source for Node.js: installs Node per user in `~/.nvm` (applies to all projects, no `.nvmrc` in the project) | latest | Install and update with the official install script: `curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/<latest-version>/install.sh \| bash`. `~/.bashrc` loads nvm |
| `node` | JavaScript runtime for npm-based CLIs | **LTS** | Only through nvm: `nvm install --lts --reinstall-packages-from=current && nvm alias default 'lts/*'`. Remove old versions with `nvm uninstall <version>`. No other Node installation on the host (no apt package `nodejs`, no tarball in `/usr/local`). Otherwise hooks, cron or systemd may use a different version, depending on their PATH |
| `npm` | Package manager for global Node CLIs | latest | `npm install -g npm@latest`. With nvm, npm belongs to each Node version and comes with an older npm version. Run the command again after every `nvm install --lts`. Global npm packages are also stored per Node version (`npm ls -g --depth=0`). The current LTS no longer includes corepack, and it is not needed |
| `supabase` | Local Postgres instance, migrations | latest | `.deb` from the latest GitHub release: `gh release download -R supabase/cli -p 'supabase_*_linux_amd64.deb' -D /tmp --clobber && sudo apt install /tmp/supabase_*_linux_amd64.deb`. Supabase has no APT repository, so `apt upgrade` does not update the CLI. Update with the same command; the check script reports new versions. `supabase start` downloads the Docker images of the local instance on its first start |
| `psql` | SQL client for the local database (the Supabase CLI cannot run free SQL): `psql postgresql://postgres:postgres@127.0.0.1:54322/postgres -c '<sql>'` | latest | Official PostgreSQL repository (PGDG), because Ubuntu ships an older version: `sudo apt install -y postgresql-common && sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y && sudo apt install postgresql-client`. The meta package `postgresql-client` always pulls in the latest major version. A newer psql also works with older servers. Updates come with `sudo apt upgrade` |
| `docker` + `docker compose` + `docker buildx` | Containers, Compose, BuildKit builds (`RUN --mount` in the Dockerfile) | latest in the official Docker repository | Not the Ubuntu package `docker.io`. Set up the repository and install (see below), then add your user to the `docker` group: `sudo usermod -aG docker $USER` and log in again. Updates come with `sudo apt upgrade` |
| `git` | Version control | latest | git-core PPA (the Ubuntu repositories ship a much older version): `sudo add-apt-repository -y ppa:git-core/ppa && sudo apt update && sudo apt install git`. After that, updates come with `sudo apt upgrade` |
| `git-lfs` | Large File Storage for git (configured globally as a filter) | latest | Official packagecloud repository (Ubuntu ships an older version): `curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh \| sudo bash`. If Ubuntu Pro is active, apt prefers the older ESM package (priority 510 instead of 500). In that case, also pin packagecloud: `printf 'Package: git-lfs\nPin: origin "packagecloud.io"\nPin-Priority: 600\n' \| sudo tee /etc/apt/preferences.d/git-lfs`. Then run `sudo apt update && sudo apt install git-lfs` and, once, `git lfs install` |
| `gh` | GitHub CLI (repo, PRs, CI) and git credential helper for github.com | latest | Set up the official APT repository: `sudo mkdir -p -m 755 /etc/apt/keyrings && wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg \| sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \| sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null && sudo apt update && sudo apt install gh`. Once: `gh auth login` (GitHub.com, HTTPS) and `gh auth setup-git`, so that git uses the gh token for github.com. Updates come with `sudo apt upgrade` |
| `ollama` | Local LLM (systemd service `ollama`) | latest | Install and update: `curl -fsSL https://ollama.com/install.sh \| sh`. The script replaces `/usr/local/bin/ollama`, `/usr/local/lib/ollama` and `ollama.service`. So put your own settings only into `sudo systemctl edit ollama` (stored in `ollama.service.d/override.conf`, kept during updates). If ollama.com is not reachable, install directly from the GitHub release: `sudo systemctl stop ollama && gh release download -R ollama/ollama -p 'ollama-linux-amd64.tar.zst' -D /tmp --clobber && sudo rm -rf /usr/local/lib/ollama && zstd -dc /tmp/ollama-linux-amd64.tar.zst \| sudo tar -xf - -C /usr/local && sudo systemctl start ollama` |
| `claude` | Claude Code (terminal) | latest | Native installation: `curl -fsSL https://claude.ai/install.sh \| bash` (binary in `~/.local/share/claude/versions/`, link `~/.local/bin/claude`). The native installation updates itself in the background. `/config` → Auto-update channel sets the channel, here `latest` (setting `autoUpdatesChannel`). Check the status with `claude doctor` ("Auto-updates: enabled"), update immediately with `claude update`. No additional npm installation. The VS Code extension brings its own Claude Code version and updates through the Marketplace |
| `ctx7` | Context7 CLI: fetches current library documentation (`ctx7 library <name> <question>` → `ctx7 docs <libraryId> <question>`) | latest | `npm install -g ctx7@latest`, once `ctx7 login`. Update: `ctx7 upgrade -y` (or the same npm command). It is a global npm package of the current Node version, so reinstall it after a Node switch without `--reinstall-packages-from` |

Docker repository (official instructions):

```bash
sudo apt update && sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### Logins (once)

| Tool | Log in | Check status |
|---|---|---|
| `gh` | `gh auth login` (GitHub.com, HTTPS, browser login), then `gh auth setup-git` | `gh auth status` |
| `claude` | On the first start of `claude`, with your Claude account (browser login) | `claude auth status` |
| `ctx7` | `ctx7 login` | `ctx7 whoami` |

No login needed: Supabase CLI (local instance), Docker (public images), Ollama (local models), uv, npm.

### Project-bound runtimes

| Component | Version channel | Where it is set |
|---|---|---|
| Python | latest stable version | Installed through uv (`uv python install`), pinned in the project with `.python-version` and `requires-python` |
| PostgreSQL | latest major version supported by Supabase | `major_version` in `supabase/config.toml` (default from `supabase init`). Supabase supports only selected major versions |
| pytest, ruff, pre-commit | latest when the project is created, pinned in `uv.lock`, raised with `uv lock --upgrade` | Dev group of the project (`uv add --dev pytest ruff pre-commit`), run through `uv run` |

### MCP servers

| Server | Scope | Purpose | Note |
|---|---|---|---|
| `context7` (HTTP, `https://mcp.context7.com/mcp`) | User (`claude mcp add --scope user …`) | Library documentation | Fallback only; the CLI `ctx7` comes first |
| `claude-vscode` | Added automatically by the VS Code extension | Diagnostics and editor context from the IDE | No configuration needed |
| `supabase-local` (HTTP, `http://127.0.0.1:54321/mcp`) | Project (`.mcp.json`) | Schema, tables, migrations and SQL of the local Supabase instance (for example `list_tables`, `execute_sql`, `apply_migration`, `get_advisors`) | Fallback only; `psql` and `supabase` come first. Only available while `supabase start` is running. Must be approved once on the first start of `claude` in the project |

Other servers connected to the Claude account (claude.ai connectors, Vercel) are not part of the development environment. GitHub does not use an MCP server; use `gh`.

### Version check

Script `~/.local/bin/check-dev-tools.sh`: compares the installed version of each global CLI with the latest (LTS) version. It also reports Node installations outside nvm and Ubuntu LTS upgrades. Exit code `1` means that a tool is missing, outdated or installed twice. It needs a logged-in `gh`.

```bash
#!/usr/bin/env bash
# Checks whether all host-wide CLIs are installed in their latest (LTS) version.
# Requires: gh (logged in), curl, uv. Exit code 1 if a tool is missing, outdated or installed twice.
set -uo pipefail

# Hooks may run with a minimal PATH: add the usual install locations
export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"

# nvm is a shell function: load it so nvm and its default Node are available in hooks too
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
set +u; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1; set -u

gh_latest() { gh api "repos/$1/releases/latest" -q .tag_name 2>/dev/null; }
norm() { sed -E 's/^(docker-)?v//; s/[^0-9.].*$//' <<<"$1"; }
ver() { grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' <<<"$1" | head -1; }

node_lts() {
  curl -fsSL https://nodejs.org/dist/index.json |
    uv run --no-project python -c 'import json,sys;print(next(x["version"] for x in json.load(sys.stdin) if x["lts"]))'
}
# latest version in the configured APT repository (e.g. the official Docker repository)
apt_cand() { apt-cache policy "$1" 2>/dev/null | awk '/Candidate:/{print $2}' | sed -E 's/^[0-9]+://'; }
# psql: latest client version offered by the configured APT repository (PGDG)
pg_latest() { local m; m=$(apt_cand postgresql-client | sed -E 's/\+.*//'); [[ -n $m ]] && apt_cand "postgresql-client-$m"; }
git_latest() {
  gh api repos/git/git/tags --paginate -q '.[].name' 2>/dev/null |
    grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1
}

# name | installed version (command) | latest version (command)
checks=(
  "uv|uv --version|gh_latest astral-sh/uv"
  "nvm|nvm --version|gh_latest nvm-sh/nvm"
  "node (LTS)|node --version|node_lts"
  "npm|npm --version|npm view npm version"
  "docker|docker version --format '{{.Client.Version}}'|apt_cand docker-ce"
  "docker compose|docker compose version --short|apt_cand docker-compose-plugin"
  "docker buildx|docker buildx version|apt_cand docker-buildx-plugin"
  "git|git --version|git_latest"
  "git-lfs|git-lfs version|gh_latest git-lfs/git-lfs"
  "gh|gh --version|gh_latest cli/cli"
  "supabase|supabase --version|gh_latest supabase/cli"
  "psql|psql --version|pg_latest"
  "ollama|ollama --version|gh_latest ollama/ollama"
  "claude|claude --version|npm view @anthropic-ai/claude-code version"
  "code|code --version|gh_latest microsoft/vscode"
  "ruff|ruff --version|gh_latest astral-sh/ruff"
  "pre-commit|pre-commit --version|gh_latest pre-commit/pre-commit"
  "ctx7|ctx7 --version|npm view ctx7 version"
)

rc=0
printf '%-15s %-12s %-12s %s\n' TOOL INSTALLED LATEST STATUS
for c in "${checks[@]}"; do
  IFS='|' read -r name inst_cmd latest_cmd <<<"$c"
  bin=${inst_cmd%% *}
  if ! command -v "$bin" >/dev/null; then
    printf '%-15s %-12s %-12s %s\n' "$name" "-" "-" "MISSING"; rc=1; continue
  fi
  inst=$(ver "$(eval "$inst_cmd" 2>&1)")
  latest=$(norm "$(eval "$latest_cmd")")
  if [[ -z $latest ]]; then status="? (latest version unknown)"
  elif [[ $inst == "$latest" ]]; then status="OK"
  else status="UPDATE"; rc=1; fi
  printf '%-15s %-12s %-12s %s\n' "$name" "$inst" "$latest" "$status"
done
for extra in /usr/bin/node /usr/local/bin/node; do
  [[ -e $extra ]] && { printf '%-15s %-12s %-12s %s\n' "node (extra)" "$($extra --version 2>/dev/null)" "-" "REMOVE ($extra, use nvm only)"; rc=1; }
done
if command -v do-release-upgrade >/dev/null && do-release-upgrade -c >/dev/null 2>&1; then
  printf '%-15s %-12s %-12s %s\n' "ubuntu (LTS)" "$(lsb_release -rs)" "newer" "UPDATE (do-release-upgrade)"; rc=1
fi
exit $rc
```

```bash
chmod +x ~/.local/bin/check-dev-tools.sh
check-dev-tools.sh            # run manually
```

The check runs automatically every time Claude Code starts, as a hook in `~/.claude/settings.json` (user level, applies to all projects). The output goes into Claude's context, and Claude points out outdated tools:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "~/.local/bin/check-dev-tools.sh || true",
            "timeout": 60,
            "statusMessage": "Checking dev tool versions..."
          }
        ]
      }
    ]
  }
}
```

### Updating

Script `~/.local/bin/update-dev-tools.sh`: updates all global tools to the latest (LTS) version and runs `check-dev-tools.sh` at the end. APT covers docker, git, git-lfs, gh, psql and VS Code. The Supabase CLI, Ollama, nvm and Node are only updated when a newer version exists. With `DRY_RUN=1`, the script only shows what it would do.

```bash
#!/usr/bin/env bash
# Updates all host-wide tools to their latest (LTS) version.
# DRY_RUN=1 only shows what would be updated.
set -uo pipefail

run() { if [[ ${DRY_RUN:-0} == 1 ]]; then echo "  [dry-run] $*"; else eval "$@"; fi; }
latest() { gh api "repos/$1/releases/latest" -q .tag_name 2>/dev/null | sed -E 's/^v//'; }
installed() { "$@" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1; }
outdated() {  # outdated <name> <installed> <latest>
  if [[ -z $3 ]]; then echo "$1: latest version unknown, skipped"; return 1; fi
  if [[ $2 == "$3" ]]; then echo "$1 $2 is up to date"; return 1; fi
  echo "$1: ${2:-not installed} -> $3"
}

# Load nvm (it is a shell function and not available in scripts otherwise)
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
set +u; . "$NVM_DIR/nvm.sh"; set -u

# --- APT: docker, git (PPA), git-lfs, gh, psql (PGDG), code, system packages
run "sudo apt -y update && sudo apt -y upgrade && sudo apt -y autoremove && sudo apt -y autoclean"

if command -v flatpak >/dev/null; then run "sudo flatpak -y update"; fi
if command -v snap >/dev/null; then run "sudo snap refresh"; fi

# --- Supabase CLI (.deb from GitHub releases, no APT repository) -------------
v=$(latest supabase/cli)
if outdated supabase "$(installed supabase --version)" "$v"; then
  run "gh release download -R supabase/cli -p 'supabase_*_linux_amd64.deb' -D /tmp --clobber && sudo apt -y install /tmp/supabase_${v}_linux_amd64.deb"
fi

# --- Ollama (only if outdated; download first, run only on success) ---------
v=$(latest ollama/ollama)
if outdated ollama "$(installed ollama --version)" "$v"; then
  run "curl -fsSL https://ollama.com/install.sh -o /tmp/ollama-install.sh && sh /tmp/ollama-install.sh"
fi

# --- nvm, Node LTS, npm, global npm packages --------------------------------
v=$(latest nvm-sh/nvm)
if outdated nvm "$(installed nvm --version)" "$v"; then
  run "curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v${v}/install.sh | bash && . \"\$NVM_DIR/nvm.sh\""
fi
v=$(nvm version-remote --lts 2>/dev/null | sed 's/^v//')
if outdated "node (LTS)" "$(installed node --version)" "$v"; then
  old=$(node --version)
  run "nvm install --lts --reinstall-packages-from=current && nvm alias default 'lts/*' && nvm use default && nvm uninstall $old"
fi
run "npm install -g npm@latest ctx7@latest"

# --- Claude Code, uv, uv tools, uv-managed Pythons --------------------------
run "claude update"
run "uv self update"
run "uv tool upgrade --all"          # ruff, pre-commit
run "uv python upgrade"              # patch updates of uv-managed Python versions

# --- VS Code extensions -----------------------------------------------------
run "code --update-extensions"

# --- Verification -----------------------------------------------------------
if [[ -x ~/.local/bin/check-dev-tools.sh ]]; then ~/.local/bin/check-dev-tools.sh; fi
```

```bash
chmod +x ~/.local/bin/update-dev-tools.sh
DRY_RUN=1 update-dev-tools.sh   # show only
update-dev-tools.sh             # update
```

---

## 3. Project structure

```text
<PROJECT_ROOT>/
├── .claude/                # Claude Code configuration (settings, commands, agents, skills)
├── .vscode/                # recommended extensions and workspace settings for VS Code (versioned)
├── .github/                # GitHub configuration
│   ├── workflows/          # CI pipeline (one file, ci.yml)
│   └── pull_request_template.md   # optional PR template
├── docs/                   # project documentation, including this file (ENVIRONMENT.md)
├── src/
│   └── <package>/          # all Python code of the project as an installable package
│       ├── __init__.py
│       ├── config.py       # settings (pydantic-settings), reads the environment and .env
│       └── <module>.py     # modules, including the entry point of a service if there is one
├── scripts/                # thin entry scripts for one-off tasks, they import from <package>
├── supabase/               # Supabase CLI configuration (config.toml) and SQL migrations
│   └── migrations/         # SQL migrations with a timestamp prefix
├── tests/                  # all tests (pytest), integration tests with the marker `integration`
├── CLAUDE.md               # project instructions for Claude Code
├── Dockerfile              # image for the service from <package>
├── docker-compose.yml      # the project's own services (PostgreSQL runs separately through Supabase)
├── .pre-commit-config.yaml # git hooks (ruff check and ruff format)
├── pyproject.toml          # project metadata, dependencies, dev group, ruff and pytest configuration
├── uv.lock                 # uv lock file (versioned)
├── .python-version         # Python version for uv (versioned)
├── README.md               # created by uv init
├── .mcp.json               # optional: project-wide MCP servers (§8)
├── .gitignore
├── .dockerignore
├── .env.example            # template for .env (versioned)
└── .env                    # local values (not versioned)
```

The project uses the common **src layout**. `<package>` is the project name in lower case with `_` instead of `-` (`<PROJECT_NAME>` = `my-project` becomes `src/my_project/`). `uv sync` installs the package in editable mode into `.venv`. This makes it importable everywhere: in `tests/`, in `scripts/` and in the container, without changing `sys.path`.

- **`src/<package>/`** contains all code, including the code of a long-running service. You start a service with `python -m <package>.<module>`: locally through `uv run`, in the container through the `Dockerfile`.
- **`scripts/`** contains only thin entry scripts for tasks that run once and then end (for example, loading data). The logic lives in the package.
- **`tests/`** contains all tests. Tests that need the running stack have the marker `integration` (see §7).

---

## 4. Configuration files

**`pyproject.toml`**: the single source for dependencies and tool configuration. Manage dependencies with `uv add` / `uv remove`; the exact versions are in `uv.lock`.

```toml
[project]
name = "<PROJECT_NAME>"
version = "0.1.0"
requires-python = ">=<X.Y>"      # latest stable Python version
dependencies = [
    "psycopg[binary]",
    "pydantic-settings",
]

[dependency-groups]
dev = [
    "pre-commit",
    "pytest",
    "ruff",
]

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]   # pycodestyle, pyflakes, isort, pyupgrade, bugbear

[tool.pytest]
testpaths = ["tests"]
addopts = ["-m", "not integration"]
markers = ["integration: needs the local stack (supabase start, docker compose up)"]
```

`uv init --package` also adds a `[build-system]` table with the `uv_build` backend; keep it as generated. `[tool.pytest]` needs pytest 9 or newer (older versions read `[tool.pytest.ini_options]`).

`uv add` writes the current version as a lower bound (`>=`). Add an upper bound only when a new major version breaks compatibility. `uv lock --upgrade` raises all packages to the latest version. `uv sync` installs the `dev` group by default; `--no-dev` leaves it out (in the container). ruff is in the dev group, so the same version from `uv.lock` runs locally, in the Claude Code hook and in CI. The pre-commit hooks use the ruff version pinned in `.pre-commit-config.yaml` (`rev`). `uv lock --upgrade` and `uv run pre-commit autoupdate` keep both at the latest version.

**`.python-version`**: one line with the latest stable Python version (`<X.Y>`). `uv python pin` writes it; `uv sync`/`uv run` and `astral-sh/setup-uv` in CI read it. Without this file, uv picks the latest installable version that matches `requires-python`.

**`uv.lock`**: created by uv and versioned. Do not edit it by hand.

**`src/<package>/config.py`**: all settings in one place. pydantic-settings reads environment variables and `.env`, checks the types and stops at startup when a required value is missing. Field names are the variable names in lower case (`postgres_password` ↔ `POSTGRES_PASSWORD`).

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration, loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 54322
    postgres_user: str = "postgres"
    postgres_password: str  # required: no default
    postgres_db: str = "postgres"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Code reads settings only through `get_settings()`, never through `os.getenv`. Real environment variables take priority over `.env`. Docker Compose uses this to set the container values. `.env` is read from the current working directory, so run all commands from the project root.

**`.env.example`**: template for `.env` with all variables the project uses (see §5). It is versioned; `.env` is not.

```dotenv
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=54322
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=postgres
```

**`tests/`**: a unit test for the settings and an integration test for the database connection. The integration test only runs with `uv run pytest -m integration`.

```python
# tests/test_config.py
import pytest
from pydantic import ValidationError

from <package>.config import Settings


def test_database_url(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    settings = Settings(_env_file=None)
    assert settings.database_url.endswith("@127.0.0.1:54322/postgres")


def test_missing_password_fails(monkeypatch):
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

```python
# tests/test_database.py
import psycopg
import pytest

from <package>.config import get_settings


@pytest.mark.integration
def test_database_connection():
    with psycopg.connect(get_settings().database_url) as conn:
        assert conn.execute("select 1").fetchone() == (1,)
```

pytest ends with exit code 5 when no test runs. Keep at least one unit test and one integration test, so that both `uv run pytest` and `uv run pytest -m integration` succeed.

**`supabase/config.toml`**: created by `supabase init`. Relevant settings:

```toml
project_id = "<PROJECT_NAME>"    # default: name of the folder
[api]
port = 54321
schemas = ["public", "graphql_public"]
[db]
port = 54322
major_version = <N>              # keep the default of the current Supabase CLI
[studio]
port = 54323
[analytics]
enabled = false
```

`supabase init` also creates `supabase/.gitignore`.

**`docker-compose.yml`**: common patterns:

```yaml
services:
  <service>:
    build: .
    ports: ["127.0.0.1:<port>:<port>"]       # bind to localhost on the host only
    env_file: .env
    environment:
      POSTGRES_HOST: host.docker.internal     # set container values here, they take priority over .env
    extra_hosts: ["host.docker.internal:host-gateway"]   # reach Supabase Postgres and Ollama on the host (Linux)
    healthcheck: { test: ["CMD", "<check-command>"], interval: 10s, retries: 10 }
    restart: unless-stopped
    logging: { driver: json-file, options: { max-size: "10m", max-file: "3" } }
    volumes: ["<service>_data:/data"]       # only if the service stores data
volumes:
  <service>_data:
```

When you create the project, set third-party images to the latest (LTS) version and pin them exactly (`<image>:<version>`), so that builds stay reproducible. Raise the tags when you update the environment. Several services from the same package use the same image with a different `command:`. Compose puts all services into the default network of the project, where they reach each other by service name.

**`Dockerfile`** (official uv pattern):

```dockerfile
FROM python:<X.Y>-slim
COPY --from=ghcr.io/astral-sh/uv:<current-uv-version> /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Dependencies in their own layer (cache survives code changes)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

# Project itself
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE <port>
CMD ["python", "-m", "<package>.<module>"]
```

`<X.Y>` is the version from `.python-version`. The base image provides Python, and uv uses it.

**`.dockerignore`**: `.git`, `.venv`, `.env`, `.env.*`, `!.env.example`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/` and container data folders.

**`.pre-commit-config.yaml`**: the official ruff hooks. Set `rev` to the latest tag (`gh api repos/astral-sh/ruff-pre-commit/releases/latest -q .tag_name`). `uv run pre-commit install` activates the hooks; `uv run pre-commit autoupdate` raises `rev` to the latest version. Run `uv run pre-commit install` again after `.venv` has been recreated, because the git hook stores the path to the Python interpreter.

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v<latest-ruff-version>
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format
```

**`.github/workflows/ci.yml`**: one job on `ubuntu-latest`. uv comes from `astral-sh/setup-uv` (with cache), Python from `.python-version`, ruff and pytest from the dev group. Integration tests do not run in CI, because no stack runs there. `concurrency` cancels older runs. Set the actions to their latest major version.

```yaml
name: CI
on:
  push: { branches: [ main ] }
  pull_request: { branches: [ main ] }
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v<latest-major>
      - uses: astral-sh/setup-uv@v<latest-major>
        with: { enable-cache: true }
      - run: uv sync --locked
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest
```

**`.github/pull_request_template.md`** (optional):

```markdown
<One paragraph: what and why.>

## Root cause / Motivation

## Change

## Verification
| Case | Expected | Result |
|---|---|---|
```

**GitHub repository settings** (with the gh CLI, for the PR workflow):

```bash
gh repo edit <OWNER>/<REPO> \
  --default-branch main \
  --enable-squash-merge \
  --enable-merge-commit=false \
  --enable-rebase-merge=false \
  --delete-branch-on-merge \
  --enable-wiki=false
```

Optionally, add a branch rule for `main` that requires a green CI check before merging.

**`.vscode/extensions.json`**: VS Code suggests these extensions when you open the project.

```json
{
  "recommendations": [
    "anthropic.claude-code",
    "ms-python.python",
    "charliermarsh.ruff"
  ]
}
```

**`.vscode/settings.json`**: connects VS Code with the uv venv, pytest and ruff as formatter.

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["tests"],
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true
  }
}
```

**`.gitignore`** (relevant patterns): `.env`, `.env.*`, `!.env.example`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.venv`, `dist/`, `.supabase/`, `supabase/.temp/`, `supabase/seed.sql` (if generated) and the bind-mount data folders of the containers.

Not used on purpose: type checking (`mypy`/`pyright`), `.editorconfig`, `.nvmrc`.

---

## 5. Environment variables and ports

All variables come from the environment or from `.env` (template `.env.example`). The code reads them through `Settings` in `src/<package>/config.py` (§4). Each new variable gets a field there. Only the `POSTGRES_*` variables are needed from the start; add the others when the project uses them.

| Variable | Purpose | Local example value |
|---|---|---|
| `POSTGRES_HOST` / `POSTGRES_PORT` | PostgreSQL (Supabase) | `127.0.0.1` / `54322` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Admin connection | `postgres` / `postgres` (CLI default) / `postgres` |
| `<APP>_PG_USER` / `<APP>_PG_PASSWORD` | Separate database role for the service (optional) | `<app>_user` / `<local-pw>` |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Local LLM | `http://127.0.0.1:11434` / `<model>:latest` |
| `LLM_TIMEOUT_SECONDS` | LLM timeout | `120` |
| `<SERVICE>_HOST` / `<SERVICE>_PORT` | Host interface and port of the service | `127.0.0.1` / `<port>` |

Ports (bound to `127.0.0.1`, except Ollama):

| Port | Service |
|---|---|
| 54321 | Supabase API |
| 54322 | PostgreSQL |
| 54323 | Supabase Studio |
| 54324 | Mailpit (Supabase, test mailbox) |
| `<port>` | the project's own service |
| 11434 | Ollama (`0.0.0.0` on purpose, so that containers can reach it) |

---

## 6. Local services

**PostgreSQL (Supabase CLI)** does not run in Compose:

```bash
supabase start                  # start the Supabase CLI containers, apply migrations on the first start
supabase status                 # URLs, ports and default credentials (DB_URL, STUDIO_URL, …)
supabase db reset               # rebuild the database: migrations + supabase/seed.sql
supabase migration new <name>   # new migration supabase/migrations/<timestamp>_<name>.sql
supabase stop                   # stop (--no-backup discards the local data)
psql postgresql://postgres:postgres@127.0.0.1:54322/postgres   # SQL console
```

The default connection is `postgresql://postgres:postgres@127.0.0.1:54322/postgres`. If you use a different `postgres` password in `.env`, you must set it again after every `db reset` (connect as `supabase_admin`, because `postgres` is not a real superuser in Supabase). It is easier to use the CLI default password locally all the time.

Containers reach the database at `host.docker.internal:54322`. This only works with `extra_hosts: ["host.docker.internal:host-gateway"]` (required on Linux).

**Docker Compose** (`docker compose up -d`): the project's own services in the default network that Compose creates for the project. They address each other by service name (`http://<service>:<port>`), not by `127.0.0.1`. Persistent data lives in named volumes (`<service>_data`) or in bind mounts that git ignores. Configuration files are mounted read-only (`:ro`).

**Ollama** runs natively on the host as the systemd service `ollama`; `ollama pull <model>` downloads models. Ollama listens on all interfaces (`0.0.0.0:11434`) on purpose, so that containers can reach it at `http://host.docker.internal:11434` (with `extra_hosts: ["host.docker.internal:host-gateway"]`). By default, Ollama only binds to `127.0.0.1`, so set this with `sudo systemctl edit ollama`. The setting is stored in `ollama.service.d/override.conf` and survives updates:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

Then run `sudo systemctl restart ollama`. Processes on the host still use `http://127.0.0.1:11434` (`OLLAMA_BASE_URL` in `.env`), containers use `http://host.docker.internal:11434`.

---

## 7. Conventions

- **Tools**: CLI before MCP (see §2). All CLIs are installed globally and kept at the latest (LTS) version. Project tools (pytest, ruff, pre-commit) run through `uv run` from the dev group.
- **Code style**: ruff with the rule groups `E`, `F`, `I`, `UP`, `B` and `ruff format` as formatter, line length 100 (§4). pre-commit checks and formats before every commit; CI checks both again. No type checking.
- **Project layout**: src layout, all code in the package `src/<package>/`. Entry points are modules with `main()` and `if __name__ == "__main__": main()`, started with `uv run python -m <package>.<module>`. `scripts/` only contains thin entry scripts that import from the package.
- **Configuration**: only through `get_settings()` from `src/<package>/config.py` (pydantic-settings). No `os.getenv` in the rest of the code. Required values have no default, so a missing value shows up at startup.
- **Naming**: Files and modules in `snake_case`. Migrations are named `YYYYMMDDHHMMSS_<description>.sql` (created by `supabase migration new`). Recommended: group tables and related files by an area prefix (`<area>_*`).
- **Commits**: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`), imperative mood, lower case. On a squash merge, GitHub adds the PR number (`(#<nr>)`).
- **Branching**: No direct commits to `main`. Every change goes through a feature branch `<type>/<short-name>` (`feat/…`, `fix/…`, `docs/…`, `chore/…`) created from `main`.
- **Pull requests**: One PR per branch, created with `gh pr create`. The PR title uses the Conventional Commits format, because it becomes the commit message on a squash merge. The body describes motivation, change and verification (template in §4). Merge only when CI is green (`gh pr checks --watch`), then run `gh pr merge --squash --delete-branch`. After that, update the local `main` with a fast-forward.
- **CI**: GitHub Actions runs on every push to `main` and every PR against `main`. Newer runs on the same branch cancel older ones (`concurrency`).
- **Testing**: All tests are in `tests/` and run with pytest. Tests that need the running stack (database, containers, Ollama) have `@pytest.mark.integration`. `uv run pytest` skips them by default (also in CI); `uv run pytest -m integration` runs them while the stack is up. Keep at least one test of each kind (§4). Optional: drift tests that check configuration files against the SQL migrations.
- **Dependencies**: Only through `uv add`/`uv remove`, never edit the lock file by hand. Lower bounds in `pyproject.toml`, an upper bound only for a known breaking change. Run `uv lock --upgrade` regularly. `uv.lock` and `.python-version` are versioned. Python commands always run through `uv run`.

---

## 8. Claude Code setup

### Components

| Element | Location | Purpose |
|---|---|---|
| `CLAUDE.md` | Root | Project instructions (template below) |
| `.claude/settings.json` | Project | Permissions and hooks, versioned |
| `.claude/settings.local.json` | Project | Personal overrides, not versioned |
| `.claude/commands/*.md` | Project | Slash commands |
| `.claude/agents/*.md` | Project | Subagents |
| `.mcp.json` | Root | Project-wide MCP servers (fallbacks, see "MCP servers" below) |
| `.claude/skills/<name>/` | Project | Project skills (folder or symlink) |
| `~/.claude/settings.json` | User | Global hooks, for example the version check at startup (§2) |
| `~/.claude/rules/*.md` | User | Global rules for all projects |
| `~/.claude/skills/<name>/` | User | Global skills |

### Structure of `CLAUDE.md` (template)

````markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
The development environment is described in docs/ENVIRONMENT.md.

## Project overview
<One paragraph: purpose of the project and its main components.>

## Tooling
- Prefer CLIs over MCP servers: use `gh`, `supabase`, `psql`, `docker`, `uv`, `ctx7` directly.
  Use an MCP server only when no CLI covers the task.
- All CLIs are installed globally on the host and kept at the latest (LTS) version.
- Run project tools through uv: `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`.
- Run all commands from the project root.
- Open PRs yourself with `gh pr create`; never hand over a compare link.

## Commands
```bash
uv sync                          # install dependencies and the package
cp .env.example .env             # then fill in the required values
supabase start                   # local database
docker compose up -d --build     # own services (if any)
uv run ruff check . && uv run ruff format --check .
uv run pytest                    # unit tests
uv run pytest -m integration     # needs the running stack
```

## Architecture
<Components with paths and ports. Code in src/<package>/, entry points as python -m <package>.<module>.>

## Configuration
All settings come from `get_settings()` in src/<package>/config.py (pydantic-settings). Never use os.getenv elsewhere.

## Beware
<Pitfalls that are not obvious>

## Further reading
- docs/ENVIRONMENT.md
````

Principles: every command can be copied and pasted. "Beware" sections record pitfalls that are not obvious. References point to files instead of repeating their content.

### `.claude/settings.json` (template)

```json
{
  "permissions": {
    "allow": [
      "Bash(uv sync *)",
      "Bash(uv run pytest *)",
      "Bash(uv run ruff *)",
      "Bash(uv run python -m <package>.*)",
      "Bash(ctx7 library *)",
      "Bash(ctx7 docs *)",
      "Bash(docker compose ps *)",
      "Bash(docker compose logs *)",
      "Bash(supabase start)",
      "Bash(supabase status *)",
      "Bash(git status *)",
      "Bash(git diff *)",
      "Bash(git log *)",
      "Bash(git fetch *)",
      "Bash(gh pr view *)",
      "Bash(gh pr list *)",
      "Bash(gh pr checks *)",
      "Bash(gh run list *)",
      "Bash(gh run view *)"
    ],
    "ask": [
      "Bash(git push *)",
      "Bash(gh pr create *)",
      "Bash(gh pr merge *)",
      "Bash(uv add *)",
      "Bash(uv remove *)",
      "Bash(uv lock *)",
      "Bash(psql *)",
      "Bash(supabase db reset *)",
      "Bash(supabase stop *)",
      "Bash(docker compose down *)"
    ]
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "cd \"$CLAUDE_PROJECT_DIR\" && uv run ruff format --quiet . && uv run ruff check --quiet . 1>&2 || exit 2"
          }
        ]
      }
    ]
  }
}
```

Permission rules use the form `Bash(<command> *)`: the trailing ` *` matches the command with any arguments. The hook formats the code after every edit. If ruff still finds problems, the hook exits with code 2, so Claude sees the findings (stderr) and fixes them. When the code is clean, the hook is silent.

### Slash command (template, `.claude/commands/verify.md`)

```markdown
---
description: Run the full local verification (same as CI, plus integration tests)
---
Run, in order, and report pass/fail per step with the failing output:
1. uv run ruff check .
2. uv run ruff format --check .
3. uv run pytest
4. If `supabase status` shows the stack running: uv run pytest -m integration
```

### Slash command (template, `.claude/commands/ship.md`)

```markdown
---
description: Commit, open a PR, wait for CI, merge and clean up
---
1. If on `main`, create a branch `<type>/<short-name>` first.
2. Stage and commit all changes with a Conventional Commits message.
3. `git push -u origin HEAD`.
4. If no PR exists for this branch (`gh pr view` fails), run `gh pr create --base main`
   with a Conventional-Commit title and a body following `.github/pull_request_template.md`.
5. `gh pr checks --watch`. If a check fails, show `gh run view <id> --log-failed` and stop.
6. `gh pr merge --squash --delete-branch`, then `git switch main && git pull --ff-only`.
```

### Slash command (template, `~/.claude/commands/update-tools.md`, user level)

```markdown
---
description: Check all global CLIs for the latest (LTS) version and show update commands
---
Run `~/.local/bin/check-dev-tools.sh`. If any tool is marked UPDATE, run
`DRY_RUN=1 ~/.local/bin/update-dev-tools.sh` and show the result; the user runs the real update
(it needs sudo). For tools marked MISSING or REMOVE, show the install/removal command from the
environment documentation.
```

Other useful commands: `/sync` (requires a clean working tree: `git fetch --prune`, then `git merge --ff-only`, otherwise stop), `/health` (`uv run pytest -m integration` + `docker compose ps` + `supabase status`), `/deps` (`uv lock --upgrade`, `uv run pre-commit autoupdate`, then `/verify`).

### Subagent (template, `.claude/agents/stack-checker.md`)

```markdown
---
name: stack-checker
description: Checks whether the local Docker Compose + Supabase stack is healthy. Use after starting or changing services.
tools: Bash, Read
---
Run `docker compose ps` and `supabase status`. Report every service that is not running/healthy,
then show the last 50 log lines of each unhealthy service via `docker compose logs --tail 50 <service>`.
Do not restart or modify anything.
```

### MCP servers

Principle CLI before MCP: create project-wide MCP servers (`.mcp.json`) only when no CLI covers the task. The user-level server `context7` (§2) stays as a fallback for the CLI `ctx7`:

```bash
claude mcp add --scope user --transport http context7 https://mcp.context7.com/mcp
```

As a fallback for `psql`/`supabase`, add the MCP server of the local Supabase instance (`.mcp.json`, versioned). It offers structured tools (for example `list_tables`, `get_advisors`) that the CLIs do not provide directly. `supabase start` provides it and reports it as `MCP_URL`:

```json
{
  "mcpServers": {
    "supabase-local": {
      "type": "http",
      "url": "http://127.0.0.1:54321/mcp"
    }
  }
}
```

On the first start of `claude` in the project, Claude Code asks whether to approve the server. Check the status with `claude mcp get supabase-local`.

### Skills

```bash
# Make a skill from an installed Python package available as a project skill via symlink
mkdir -p .claude/skills
ln -s "../../.venv/lib/python<X.Y>/site-packages/<installed-package>/<path-to-skill>" .claude/skills/<skill-name>
```

Note: the symlink points into the project's `.venv`. It breaks when the Python version changes, or when `.venv` is recreated and `uv sync` has not run yet.

Global rule `~/.claude/rules/context7.md` (user level, applies to all projects). It makes Claude use the `ctx7` CLI first and the context7 MCP server only as a fallback:

````markdown
Use Context7 to fetch current documentation whenever the user asks about a library, framework, SDK, API, CLI tool, or cloud service — even well-known ones like React, Next.js, Prisma, Express, Tailwind, Django, or Spring Boot. This includes API syntax, configuration, version migration, porting code between libraries, platforms, or SQL dialects, library-specific debugging, setup instructions, and CLI tool usage. Use it even when you think you know the answer — your training data may not reflect recent changes. Prefer this over web search for library docs.

Do not use for: refactoring, debugging, or reviewing code that does not depend on a library or platform API, or general programming concepts.

## CLI first, MCP as fallback

Use the `ctx7` CLI through the Bash tool. Use the Context7 MCP tools (`resolve-library-id`, `query-docs`) only when `ctx7` is not available or fails (for example: not installed, not logged in, network error).

If `ctx7` is not found, the shell may still have an old Node path from nvm. Retry with `source ~/.nvm/nvm.sh && nvm use default >/dev/null && ctx7 …` before falling back to MCP.

## Steps

1. Resolve the library ID, unless the user provides an exact ID in `/org/project` format:
   `ctx7 library <name> "<what to look up>"`
2. Pick the best match (ID format: `/org/project`) by: exact name match, description relevance, code snippet count, source reputation (High/Medium preferred), and benchmark score (higher is better). If results don't look right, try alternate names or queries (e.g., "next.js" not "nextjs", or rephrase the question). Use version-specific IDs (`/org/project/<version>`) when the user mentions a version.
3. Query the docs with the selected ID and a specific question (not single words), scoped to a single concept:
   `ctx7 docs <libraryId> "<question>"` (add `--language <name>` to rank examples in that language first)
   If the question spans multiple distinct concepts (e.g. routing and auth and caching), run a separate `ctx7 docs` call per concept with the same library ID, unless the question is about how the concepts interact — combined queries dilute ranking and return shallow results for each topic.
4. Answer using the fetched docs.

Fallback with MCP: the same steps with `resolve-library-id` (step 1) and `query-docs` (step 3).
````

The user-level skill `~/.claude/skills/context7-mcp/SKILL.md` follows the same order: `ctx7` first, the MCP tools only as a fallback. `ctx7 setup` can overwrite the rule and the skill (mode `--mcp` sets up the MCP server, mode `--cli` sets up CLI and skills without MCP). After running `ctx7 setup`, check that both still put the CLI first.

---

## 9. Bootstrap checklist for a new project

1. Once per host (skip if already done): install all CLIs from §2 globally, set up `check-dev-tools.sh` and the SessionStart hook, then run `check-dev-tools.sh`. Every tool must report `OK`.
2. Run `git init -b main` and create the folders `scripts/`, `tests/`, `docs/`, `.github/workflows/`, `.claude/` and `.vscode/`. Create `.vscode/extensions.json` and `.vscode/settings.json` as described in §4.
3. Create the Python project with uv:
   ```bash
   uv python install                                   # latest stable Python version
   uv init --package --name <PROJECT_NAME> --python <X.Y>
   uv python pin <X.Y>
   uv add pydantic-settings "psycopg[binary]"
   uv add --dev pytest ruff pre-commit
   ```
   `<X.Y>` is the newest stable CPython minor version (see `uv python list`; ignore pre-releases). `uv init --package` creates `src/<package>/__init__.py` with a sample `main()`, a `[project.scripts]` entry, the build backend, `.python-version` and a `README.md`. `uv python pin` makes sure that `.python-version` contains `<X.Y>`. Then add `[tool.ruff]` and `[tool.pytest]` to `pyproject.toml` as described in §4. Remove `[project.scripts]` and the sample `main()` if you do not need them.
4. Run `supabase init`. Keep the default `major_version` and check the ports against §4.
5. Create `.env.example` with the variables from §5. Create `.gitignore` and `.dockerignore` as described in §4.
6. Create `src/<package>/config.py` and the two tests `tests/test_config.py` and `tests/test_database.py` as described in §4.
7. If the project has its own service: create `src/<package>/<module>.py` as entry point, then `Dockerfile` and `docker-compose.yml` as described in §4, and set the image tags to the latest version. Without a service, skip this step and the `docker compose` command in step 10.
8. Create `.pre-commit-config.yaml` as described in §4, then run `uv run pre-commit autoupdate` and `uv run pre-commit install`. Create the CI workflow and, optionally, the PR template in `.github/`, and set the actions to their latest major version.
9. Write `CLAUDE.md` from the template in §8. Optionally create `.claude/settings.json`, commands, agents and `.mcp.json`.
10. Start and check the environment:
    ```bash
    uv sync --locked
    cp .env.example .env
    supabase start
    docker compose up -d --build     # only with a service (step 7)
    uv run ruff check . && uv run ruff format --check .
    uv run pytest
    uv run pytest -m integration
    ```
11. Create the GitHub repository and push the first commit:
    ```bash
    git add -A && git commit -m "chore: initial project setup"
    gh repo create <OWNER>/<REPO> --private --source=. --remote=origin --push
    ```
12. Apply the repository settings with `gh repo edit` from §4; optionally add a branch rule for `main` that requires the CI check.
13. Create the first feature branch and open a PR. Check that CI runs (`gh pr checks --watch`).

**Places to adapt**

| What | File(s) |
|---|---|
| Project name `<PROJECT_NAME>` | `pyproject.toml` (`name`), CI workflow `name`, `supabase/config.toml` (`project_id`) |
| Package name `<package>` (derived from the project name) | `src/<package>/`, imports, `Dockerfile` (`CMD`), `docker-compose.yml` (`command:`), `.claude/settings.json` |
| Ports | `supabase/config.toml`, `docker-compose.yml` (`ports:`), `.env.example` |
| Volume names | `docker-compose.yml` (`volumes:`) |
| Bind-mount paths | `docker-compose.yml`, `.gitignore`, `.dockerignore` |
| Python version `<X.Y>` | `.python-version`, `pyproject.toml` (`requires-python`), Dockerfile base image, skill symlinks |
| uv version | `Dockerfile` (`ghcr.io/astral-sh/uv:<version>`) |
| Image tags, action versions, hook versions | `docker-compose.yml`, `Dockerfile`, `.github/workflows/ci.yml`, `.pre-commit-config.yaml` (`uv run pre-commit autoupdate`) |
| LLM model | `OLLAMA_MODEL` in `.env.example` |
| Skill symlinks | `.claude/skills/*` (set new paths) |
| GitHub owner/repository `<OWNER>/<REPO>` | `gh repo create`, `gh repo clone`, `gh repo edit` |
| Default branch | CI trigger (`branches: [ main ]`), `gh repo edit --default-branch`, `gh pr create --base` |
| CI workflow name | `name:` in `.github/workflows/ci.yml` (shown as the check name in the PR) |
