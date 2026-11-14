# ENVIRONMENT

How to set up the development environment for local spikes: a fresh Ubuntu 26.04 LTS workstation, its tools, and the spike projects on it in Python, Node or Java. The setup is **built on one central version manager (mise) for all user CLIs and runtimes**: APT keeps the system services and drivers, and a few tools keep their own installers. Project-specific names are placeholders (`<PROJECT_NAME>`, `<package>`, …).

**Version:** 1.0.0 (2026-11-14). The [change log](#change-log) at the end lists all versions.

**How to read this document:** §1 states the purpose and the principles, and §2 assigns every tool to exactly one manager. §3 sets up the host step by step, once per machine, in the order APT, own installers, mise; §4 holds the check and update scripts, the final check of the host and the disk cleanup. All projects share this host. §5 describes spike projects, the light variant for local, often short-lived projects, in Python (§5.1), Node (§5.2) and Java (§5.3). The three subchapters have the same sections: §5.1.9, §5.2.9 and §5.3.9 are the step-by-step checklists that Claude follows in a new project, and §5.1.10 records the decisions behind the light variant and describes the extended variant for projects that grow. §5.4 creates a new spike from a template repository with one command, and §5.5 ends a spike. §6 explains which shell sees which tools, and §7 lists the pitfalls. The contents list below links every chapter.

**Contents**

- [1. Purpose and scope](#1-purpose-and-scope): Principles
- [2. Which tool manages what](#2-which-tool-manages-what): Tools in scope
- [3. Host setup](#3-host-setup): APT (base, tools, login) · Own installers (tools, login) · mise (base, tools, login)
- [4. Check and update scripts](#4-check-and-update-scripts): `check-dev-tools.sh` · `update-dev-tools.sh` · SessionStart hook for Claude Code · Skill `/update-tools` · Final check of the host · Disk space and cleanup
- [5. Spike projects](#5-spike-projects): Python (starting a spike with Claude Code · project structure · configuration files · environment variables and ports · local services · secrets with 1Password · conventions · Claude Code setup · bootstrap checklist · decisions and the extended variant) · Node · Java (the same sections) · New spike from a template · Ending a spike
- [6. Claude Code and non-interactive shells](#6-claude-code-and-non-interactive-shells)
- [7. Pitfalls](#7-pitfalls)
- [Change log](#change-log)

**Placeholders**

| Placeholder | Meaning | Example |
|---|---|---|
| `<PROJECT_NAME>` | Project and repository name, lower case with `-` | `my-spike` |
| `<package>` | Python package name: `<PROJECT_NAME>` with `_` instead of `-` | `my_spike` |
| `<module>` | Module inside the package, for example the entry point of a service | `api` |
| `<service>` | Name of the project's own service; with containers also its name in `docker-compose.yml` (§5.1.10) | `api` |
| `<SERVICE>` | `<service>` in upper case, the prefix of its environment variables | `API` |
| `<port>` | Port of the project's own service | `8000` |
| `<OWNER>/<REPO>` | GitHub owner and repository | `my-org/my-spike` |
| `<NAME>`, `<EMAIL>` | Your name and e-mail address for git commits | `Jane Doe`, `jane@example.com` |
| `<item>` | Name of a 1Password item | `openai` |
| `<X.Y>` | Latest stable Python minor version | the newest minor version without pre-releases (`uv python list`) |
| `<PATH>` | Folder that holds the master copy of this file | `~/templates` |
| `<latest-…>`, `<current-…>` | Latest version when you write the file. Look it up with `gh api repos/<org>/<repo>/releases/latest -q .tag_name` | `v<N>` |
| `<node-lts-major>`, `<java-lts-major>` | Major version of the Node or Java LTS that mise installs | the first number of `node --version` or `java -version` |

---

## 1. Purpose and scope

A workstation for one person who builds local spikes with Claude Code, and the spike projects on it:

- **Ubuntu 26.04 LTS** as the baseline, set up from a fresh installation (§3).
- **mise** as the one manager for user CLIs and language runtimes. One command checks them, one command updates them (§4).
- **APT** for system services and drivers such as Docker and NVIDIA; **own installers** for tools that update themselves or run as a service, such as Claude Code, Ollama and uv.
- **uv** for Python, **Ollama** as the local LLM backend, and the **Supabase CLI** for PostgreSQL in Docker.
- **1Password** for SSH keys, commit signing and secrets.
- **Spike projects** in Python, Node or Java, which Claude Code sets up according to this file (§5).

### Principles

- **Versions:** Every tool runs at its current LTS version, or at the latest stable version if there is no LTS line. This document records no fixed version numbers. Exact versions live only in the lock files of a project, such as `mise.lock`, `uv.lock` or `pnpm-lock.yaml`, and for Maven in the version properties of `pom.xml`.
- **One manager per tool:** Every tool has exactly one source (§2). A second copy hides the first one in `PATH` (§7).
- **Installed once:** All CLIs are installed once on the host for all projects, not per project. Tools whose version each project pins itself (pytest, ruff, pre-commit) are also in the project's dev group and run there through `uv run`.
- **CLI before MCP:** If a task can be done with a CLI or with an MCP server, use the CLI (`gh`, `supabase`, `psql`, `docker`, `uv`, `ctx7`, …). Use an MCP server only when there is no suitable CLI.
- **Commands, not prose:** Every step of the host setup is a block to copy. Files in the home directory are written with `cat << "EOF"` blocks; a block that appends to a file first looks for its first line there, so that a second run adds nothing. System files are written with `sudo tee`, and JSON settings are merged with `jq`, so that other settings stay. Placeholders in command blocks are quoted, so that the shell does not read `<` and `>` as redirections. The project files in §5 are templates: Claude Code, or you, writes them into the project with the placeholders replaced.
- **Checked regularly:** A script checks all host tools at every start of Claude Code (§4).
- **sudo stays manual:** Commands with `sudo` are listed for you to run yourself.

---

## 2. Which tool manages what

| Manager | Use for | Reason |
|---|---|---|
| **APT** (official vendor repositories) | System services, drivers, the version manager itself, and tools that other system packages depend on | They are part of the operating system. APT updates them together with the system, and they do not belong in a user version manager. |
| **Own installer** | Tools that update themselves, run as a system service, or form the base of another manager | Their vendor's installer handles updates or service setup better than a generic manager. |
| **mise** (user level) | All other user CLIs and language runtimes | One command checks them, one command updates them, and a project can pin its own versions. |

### Tools in scope

| Tool | Command | Purpose | Manager | Source / mise backend |
|---|---|---|---|---|
| mise | `mise` | Version manager for user CLIs and runtimes | APT | PPA `ppa:jdxcode/mise` |
| git | `git` | Version control | APT | PPA `ppa:git-core/ppa` |
| git-lfs | `git-lfs` | Large files in git | APT | packagecloud repository of git-lfs |
| GitHub CLI | `gh` | GitHub from the terminal; token source for mise | APT | `cli.github.com/packages` |
| Docker | `docker` | Containers (also runs Supabase's Postgres) | APT | `download.docker.com/linux/ubuntu` |
| VS Code | `code` | IDE | APT | `packages.microsoft.com/repos/code` |
| PostgreSQL client | `psql` | Database client | APT | PGDG `apt.postgresql.org` |
| NVIDIA driver, CUDA, Container Toolkit, GDS | `nvidia-smi`, `nvcc`, `nvidia-ctk` | GPU support (only on hosts with an NVIDIA GPU) | APT | NVIDIA's CUDA repository, `nvidia.github.io` (Container Toolkit) |
| nvtop | `nvtop` | GPU load and GPU memory, for example while Ollama runs (only on hosts with an NVIDIA GPU) | APT | Ubuntu repository |
| System JDK | `java` (system) | Java for system packages (only if one needs it) | APT | Ubuntu repository |
| 1Password | `1password`, `op` | Password manager, SSH agent, commit signing, secrets for `.env` | APT | `downloads.1password.com` |
| Google Chrome | `google-chrome` | Browser for UI tests and Claude in Chrome | APT | `dl.google.com` |
| Google Cloud CLI | `gcloud` | Google Cloud from the terminal (only if you use it) | APT | `packages.cloud.google.com` |
| Claude Desktop | `claude-desktop` | Claude desktop app | APT | `downloads.claude.ai` |
| ufw | `ufw` | Firewall: blocks incoming connections except the allowed ports | APT | Ubuntu repository (installed by default) |
| Claude Code | `claude` | AI coding agent; updates itself | Own installer | `claude.ai/install.sh` |
| Ollama | `ollama` | Local LLM backend, systemd service | Own installer | `ollama.com/install.sh` |
| uv | `uv`, `uvx` | Python projects and Python itself; base of mise's PyPI backend | Own installer | `astral.sh/uv/install.sh` |
| JetBrains Toolbox | `jetbrains-toolbox` | Installs and updates JetBrains IDEs; updates itself | Own installer | `data.services.jetbrains.com` |
| Node.js (LTS) | `node`, `npm`, `npx` | JavaScript runtime | mise | `node` (core) |
| pnpm | `pnpm` | Node package manager | mise | `pnpm` (aqua) |
| Context7 CLI | `ctx7` | Current library documentation | mise | `npm:ctx7` |
| Vercel CLI | `vc`, `vercel` | Vercel deployments | mise | `npm:vercel` |
| Gemini CLI | `gemini` | Google's AI coding agent | mise | `gemini` (`npm:@google/gemini-cli`) |
| Java (LTS) | `java`, `javac` | JDK for development (Eclipse Temurin) | mise | `java` (core) |
| Maven | `mvn` | Java build tool | mise | `maven` (aqua) |
| Gradle (optional) | `gradle` | Java build tool | mise | `gradle` (aqua) |
| Supabase CLI | `supabase` | Local Supabase stack, migrations | mise | `supabase` (aqua) |
| Hugging Face CLI | `hf` | Models and datasets from the Hugging Face Hub | mise | `pypi:huggingface_hub` |
| ruff | `ruff` | Python linter and formatter | mise | `ruff` (aqua) |
| pre-commit | `pre-commit` | Git hook framework | mise | `pypi:pre-commit` |
| gitleaks | `gitleaks` | Secret scan before every commit | mise | `gitleaks` (aqua) |
| shellcheck | `shellcheck` | Checks Bash scripts, also the scripts in §4 | mise | `shellcheck` (aqua) |

Rules:

- Install user CLIs only through mise: no `npm i -g`, no `uv tool install`, no manually downloaded binaries. Only the own installers (§3.2) and the scripts in §4 and §5.4 write to `~/.local/bin`.
- Python comes from uv (§3.2); Node and Java come from mise.
- mise also loads environment variables per project (§5.1.3), so no separate tool such as direnv is needed.

---

## 3. Host setup

The baseline is a fresh **Ubuntu 26.04 LTS** installation. Work through the three managers in this order: APT (3.1), own installers (3.2), mise (3.3). Reboot once at the end of the APT tools (3.1.2), and log out and in again at the end of §3 (3.3.3).

Each step is a block to copy. To run the APT tools (3.1.1 and 3.1.2) in one go, extract their blocks into a script, read it, and run it. On hosts without an NVIDIA GPU, delete the NVIDIA lines first. The reboot and the logins stay manual. Set `github_repo` to the GitHub repository that holds this file; the URL works once the file is there:

```bash
sudo apt update && sudo apt install -y curl     # a fresh desktop installation may lack curl
github_repo="<OWNER>/<REPO>"                    # GitHub repository that holds this file
curl -fsSL "https://raw.githubusercontent.com/$github_repo/main/docs/ENVIRONMENT.md" \
  | awk '/^### 3.1 APT/,/^##### Reboot and check/' \
  | awk '/^```bash/{f=1; next} /^```/{f=0} f' > ~/bootstrap-apt.sh
less ~/bootstrap-apt.sh             # read it; delete what this host does not need
bash -e ~/bootstrap-apt.sh
```

### 3.1 APT

#### 3.1.1 Base

The commands follow the vendors' official install guides. Every repository is added in the deb822 format (`.sources`) or as the vendor ships it, with its key in `/etc/apt/keyrings` or `/usr/share/keyrings`. The release codename is read from the system, never typed by hand.

All vendor repositories below publish packages for Ubuntu 26.04 (checked on 2026-11-13). If `sudo apt update` later reports `Release file not found` for one of them, check the vendor's install guide for changes.

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y build-essential curl wget ca-certificates gnupg unzip jq \
  software-properties-common
sudo install -m 0755 -d /etc/apt/keyrings
```

Ubuntu offers only LTS releases as upgrades when `Prompt=lts` is set, the default on an LTS installation. The check script in §4 reports a new LTS release; upgrade with `sudo do-release-upgrade`.

```bash
grep '^Prompt=' /etc/update-manager/release-upgrades   # expected: Prompt=lts
```

#### 3.1.2 Tools

##### git (PPA git-core)

```bash
sudo add-apt-repository -y ppa:git-core/ppa
sudo apt update
sudo apt install -y git
```

##### git-lfs (packagecloud)

The pin makes apt prefer packagecloud. Without it, an active Ubuntu Pro would install the older git-lfs from Ubuntu's ESM repository (priority 510 instead of 500).

```bash
curl -fsSL https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | sudo bash
sudo tee /etc/apt/preferences.d/git-lfs > /dev/null << "EOF"
Package: git-lfs
Pin: origin "packagecloud.io"
Pin-Priority: 600
EOF
sudo apt install -y git-lfs
git lfs install
```

##### gh (GitHub CLI)

```bash
wget -nv -O- https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null
sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install -y gh
```

##### Docker

```bash
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"     # takes effect after the reboot at the end of 3.1.2
```

Membership in the `docker` group gives root rights on the host, so add only your own user.

Limit the size of container logs; without a limit they grow until the disk is full. The setting applies to new containers. `nvidia-ctk` (below) adds its runtime to the same file and keeps these settings.

```bash
sudo mkdir -p /etc/docker
[ -f /etc/docker/daemon.json ] || echo '{}' | sudo tee /etc/docker/daemon.json > /dev/null
sudo jq '. + {"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "3"}}' /etc/docker/daemon.json \
  | sudo tee /etc/docker/daemon.json.tmp > /dev/null \
  && sudo mv /etc/docker/daemon.json.tmp /etc/docker/daemon.json
sudo systemctl restart docker
```

##### VS Code

```bash
wget -qO- https://packages.microsoft.com/keys/microsoft.asc \
  | gpg --dearmor | sudo tee /usr/share/keyrings/microsoft.gpg > /dev/null
sudo chmod 644 /usr/share/keyrings/microsoft.gpg
sudo tee /etc/apt/sources.list.d/vscode.sources > /dev/null <<EOF
Types: deb
URIs: https://packages.microsoft.com/repos/code
Suites: stable
Components: main
Architectures: amd64,arm64,armhf
Signed-By: /usr/share/keyrings/microsoft.gpg
EOF
sudo apt update
sudo apt install -y code
```

Extensions for Claude Code and Python:

```bash
for ext in anthropic.claude-code charliermarsh.ruff ms-python.python ms-python.vscode-pylance \
           ms-python.debugpy ms-python.vscode-python-envs; do
  code --install-extension "$ext"
done
```

##### psql (PGDG)

Only the client: Supabase runs the Postgres server in Docker.

```bash
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
  https://www.postgresql.org/media/keys/ACCC4CF8.asc
sudo tee /etc/apt/sources.list.d/pgdg.sources > /dev/null <<EOF
Types: deb
URIs: https://apt.postgresql.org/pub/repos/apt
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg
Components: main
Signed-By: /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
EOF
sudo apt update
sudo apt install -y postgresql-client
```

Connect to the local database with `psql -h 127.0.0.1 -p 54322 -U postgres postgres`. The password of the local Supabase instance, its default `postgres`, goes into `~/.pgpass`, so that it does not end up in commands, URLs or the shell history:

```bash
grep -qsFx '127.0.0.1:54322:*:postgres:postgres' ~/.pgpass || cat >> ~/.pgpass << "EOF"
127.0.0.1:54322:*:postgres:postgres
EOF
chmod 600 ~/.pgpass
```

##### NVIDIA driver, CUDA, Container Toolkit, GDS (only on hosts with an NVIDIA GPU)

All NVIDIA packages come from NVIDIA's CUDA network repository, the driver included. Do not also install a driver with `ubuntu-drivers`: two sources for the same driver conflict on updates. The Ubuntu installer installs Ubuntu's driver too if you tick *Install third-party software for graphics and Wi-Fi hardware*; leave that box empty. If Ubuntu's driver is there anyway, the first block removes it:

```bash
ubuntu_driver="$(dpkg-query -W -f='${db:Status-Abbrev} ${Package}\n' 'linux-modules-nvidia-*' 'nvidia-driver-[0-9]*' 2>/dev/null \
  | awk '$1 == "ii" {print $2}')"
if [[ -n "$ubuntu_driver" ]]; then
  sudo apt purge -y $ubuntu_driver               # unquoted on purpose: one argument per package
  sudo apt autoremove -y
fi
```

The repository path contains the Ubuntu version without the dot (`ubuntu2604`). The name of the keyring package is read from the repository.

```bash
distro="ubuntu$(. /etc/os-release && echo "${VERSION_ID//./}")"
arch="$(uname -m)"; [ "$arch" = aarch64 ] && arch=sbsa
cuda_repo="https://developer.download.nvidia.com/compute/cuda/repos/${distro}/${arch}"
keyring="$(curl -fsSL "$cuda_repo/" | grep -oE 'cuda-keyring_[0-9.]+-[0-9]+_all\.deb' | sort -uV | tail -1)"
wget -nv "$cuda_repo/$keyring"
sudo dpkg -i "$keyring" && rm "$keyring"
sudo apt update
```

Kernel headers for the running kernel, so that DKMS can build the driver and `nvidia-fs`. The headers of later kernels come with the kernel meta package of a standard installation (`linux-generic`, or `linux-generic-hwe-…` with an HWE kernel). Then the driver with the open GPU kernel modules, latest driver branch:

```bash
sudo apt install -y "linux-headers-$(uname -r)"
sudo apt install -y nvidia-open
```

The kernel modules are built with DKMS. With Secure Boot on, apt asks for a password to enroll a signing key (MOK). At the next boot, choose *Enroll MOK* in the blue MOK manager and enter that password; otherwise the modules do not load.

CUDA Toolkit, for `nvcc` and the CUDA libraries:

```bash
sudo apt install -y cuda-toolkit
grep -qsFx '# cuda' ~/.profile || cat >> ~/.profile << "EOF"
# cuda
export PATH="/usr/local/cuda/bin:$PATH"

EOF
```

NVIDIA Container Toolkit, so that Docker containers can use the GPU:

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

NVIDIA GPUDirect Storage (GDS), so that programs using the cuFile API (for example RAPIDS cuDF/KvikIO or DALI) can read data from local NVMe storage directly into GPU memory. The package includes the `nvidia-fs` kernel module, which is also built with DKMS. Full GDS mode needs the open GPU kernel modules from `nvidia-open` and is supported on Ubuntu 26.04. On GPUs or file systems without full support, cuFile falls back to compatibility mode and still works, without the direct data path.

```bash
sudo apt install -y nvidia-gds
```

nvtop shows the load and the memory of the GPU, for example while Ollama runs a model:

```bash
sudo apt install -y nvtop
```

##### System JDK (only if a system package needs Java)

The development JDK comes from mise (§3.3). Install a system JDK only when an APT package or a desktop program needs one:

```bash
sudo apt install -y default-jre-headless
```

##### 1Password

The desktop app holds passwords, SSH keys and secrets; `op` is its CLI. Install `op` with APT, not with mise: the connection to the desktop app needs the permissions that the package sets.

```bash
curl -sS https://downloads.1password.com/linux/keys/1password.asc \
  | sudo gpg --dearmor --output /usr/share/keyrings/1password-archive-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/amd64 stable main" \
  | sudo tee /etc/apt/sources.list.d/1password.list > /dev/null
sudo mkdir -p /etc/debsig/policies/AC2D62742012EA22 /usr/share/debsig/keyrings/AC2D62742012EA22
curl -sS https://downloads.1password.com/linux/debian/debsig/1password.pol \
  | sudo tee /etc/debsig/policies/AC2D62742012EA22/1password.pol > /dev/null
curl -sS https://downloads.1password.com/linux/keys/1password.asc \
  | sudo gpg --dearmor --output /usr/share/debsig/keyrings/AC2D62742012EA22/debsig.gpg
sudo apt update
sudo apt install -y 1password 1password-cli
```

##### Google Chrome

Browser for UI tests and for Claude in Chrome. The package adds Google's APT repository itself, so updates come with APT.

```bash
wget -nv -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y /tmp/google-chrome.deb
rm /tmp/google-chrome.deb
```

##### Google Cloud CLI (only if you use Google Cloud)

```bash
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
  | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list > /dev/null
sudo apt update
sudo apt install -y google-cloud-cli
```

##### Claude Desktop

Anthropic's repository for amd64 and arm64. The block adds the repository only if the key has the fingerprint that Anthropic publishes:

```bash
keyfile=/usr/share/keyrings/claude-desktop-archive-keyring.asc
sudo curl -fsSLo "$keyfile" https://downloads.claude.ai/claude-desktop/key.asc
if gpg --show-keys --with-colons "$keyfile" | grep -q ':31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE:'; then
  echo "deb [arch=amd64,arm64 signed-by=$keyfile] https://downloads.claude.ai/claude-desktop/apt/stable stable main" \
    | sudo tee /etc/apt/sources.list.d/claude-desktop.list > /dev/null
  sudo apt update
  sudo apt install -y claude-desktop
else
  echo "Unexpected key for Claude Desktop; repository not added" >&2
  sudo rm -f "$keyfile"
fi
```

##### mise (PPA jdxcode)

Install mise from its PPA, so that APT also keeps mise itself up to date. On Ubuntu 26.04 and later, the PPA is the recommended way; the `extrepo` method is meant for older releases and Debian.

```bash
sudo add-apt-repository -y ppa:jdxcode/mise
sudo apt update
sudo apt install -y mise
```

##### Firewall (ufw)

ufw is installed on Ubuntu but turned off. Turn it on: it blocks incoming connections, except port 11434 of Ollama (3.2) from the LAN and from the Docker networks. Adapt the LAN subnet. ufw does not filter ports that Docker publishes (§7).

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
# sudo ufw allow OpenSSH                                         # only if you log in over SSH
sudo ufw allow from 192.168.0.0/16 to any port 11434 proto tcp   # Ollama from the LAN
sudo ufw allow from 172.16.0.0/12 to any port 11434 proto tcp    # Ollama from the Docker networks
sudo ufw enable                                                  # asks for confirmation
sudo ufw status verbose
```

##### Reboot and check

One reboot loads the NVIDIA driver and activates the `docker` group:

```bash
sudo reboot
```

After the reboot:

```bash
docker run --rm hello-world                                     # Docker works without sudo
nvidia-smi                                                      # NVIDIA hosts: GPU and driver version
docker run --rm --runtime=nvidia --gpus all ubuntu nvidia-smi   # NVIDIA hosts: containers see the GPU
/usr/local/cuda/gds/tools/gdscheck -p                           # NVIDIA hosts: GDS in full or compatibility mode
```

#### 3.1.3 Login

Log in to `gh` before you install the mise tools: mise gets its GitHub token from `gh` (`credential_command` in 3.3.1). Without a token, the GitHub rate limit can make `mise install` and `mise outdated` fail. Replace `<NAME>` and `<EMAIL>` before you run the block. For GitHub, the private no-reply address from the account settings keeps your real address out of the history.

```bash
gh auth login
gh auth setup-git                    # git over HTTPS uses the token of gh
gh auth status                       # check the login
git config --global user.name "<NAME>"           # your name
git config --global user.email "<EMAIL>"         # your e-mail address
git config --global init.defaultBranch main
git config --global core.excludesFile ~/.gitignore_global
cat > ~/.gitignore_global << "EOF"
.env
.venv/
__pycache__/
node_modules/
mise.local.toml
.idea/
EOF
```

Open the 1Password app and sign in. Under *Settings > Developer*, turn on *Use the SSH agent* and *Integrate with 1Password CLI*. Create an SSH key in 1Password (*New Item > SSH Key*) if you have none. Then use the agent for SSH and sign commits with that key:

```bash
grep -qsFx '# 1password' ~/.bashrc || cat >> ~/.bashrc << "EOF"
# 1password
export SSH_AUTH_SOCK=~/.1password/agent.sock

EOF

export SSH_AUTH_SOCK=~/.1password/agent.sock
op whoami                                           # the CLI is connected to the app
key="$(ssh-add -L | grep -E '^(ssh|ecdsa|sk)-' | head -1)"   # first SSH key in 1Password, empty if none
if [[ -n "$key" ]]; then
  git config --global gpg.format ssh
  git config --global gpg.ssh.program /opt/1Password/op-ssh-sign
  git config --global user.signingkey "key::$key"
  git config --global commit.gpgsign true
  gh auth refresh -h github.com -s admin:ssh_signing_key
  echo "$key" > /tmp/signing-key.pub
  gh ssh-key add /tmp/signing-key.pub --type signing --title "$(hostname)"
  rm /tmp/signing-key.pub
else
  echo "No SSH key from 1Password: turn on the SSH agent, create a key, then run this block again" >&2
fi
```

Only if you use Google Cloud:

```bash
gcloud init                                   # login, default project and region
gcloud auth application-default login         # credentials for the Google client libraries in code
```

Sign in to Claude Desktop and Google Chrome when you start them the first time.

### 3.2 Own installers

#### 3.2.1 Tools

Install `uv` **before** the mise tools (3.3), because mise installs PyPI tools with uv.

##### uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh          # installs to ~/.local/bin
source "$HOME/.local/bin/env"                            # puts ~/.local/bin on PATH in this shell
uv python install --preview-features python-install-default --default   # latest Python, also as python and python3
```

`--default` is a preview feature of uv; `--preview-features python-install-default` turns it on on purpose and hides the warning. The scripts in §4 keep this Python up to date.

##### claude

```bash
curl -fsSL https://claude.ai/install.sh | bash           # updates itself afterwards
```

Global rules apply in every project. Context7 provides current library documentation as an MCP server; the `ctx7` CLI (3.3) is the first choice, the MCP server the fallback. The permission rule stops Claude Code's file tools and file commands such as `cat` from reading `.env` files at any depth of a project. It does not stop programs that open files themselves; therefore real secrets stay in 1Password, and `.env` holds only local values (§5.1.6):

```bash
mkdir -p ~/.claude/rules
cat > ~/.claude/rules/working-preferences.md << "EOF"
# Working preferences

- Reply to the user in German. Write files (docs, scripts, comments) in English, language level B2.
- Use a CLI before an MCP server: gh, supabase, psql, docker, uv, ctx7.
- Every tool runs at its latest (LTS) version. Do not write fixed version numbers into documentation.
- User CLIs come from mise, Python from uv, system tools from APT.
- Suggest commands that need sudo; do not run them.
EOF

claude mcp add --scope user --transport http context7 https://mcp.context7.com/mcp

[ -f ~/.claude/settings.json ] || echo '{}' > ~/.claude/settings.json
jq '.permissions.deny = ((.permissions.deny // []) + ["Read(.env)"] | unique)' \
  ~/.claude/settings.json > ~/.claude/settings.json.tmp \
  && mv ~/.claude/settings.json.tmp ~/.claude/settings.json
```

A second global rule makes Claude use the `ctx7` CLI first and the context7 MCP server only as a fallback:

```bash
cat > ~/.claude/rules/context7.md << "EOF"
Use Context7 to fetch current documentation whenever the user asks about a library, framework, SDK, API, CLI tool, or cloud service — even well-known ones like React, Next.js, Prisma, Express, Tailwind, Django, or Spring Boot. This includes API syntax, configuration, version migration, porting code between libraries, platforms, or SQL dialects, library-specific debugging, setup instructions, and CLI tool usage. Use it even when you think you know the answer — your training data may not reflect recent changes. Prefer this over web search for library docs.

Do not use for: refactoring, debugging, or reviewing code that does not depend on a library or platform API, or general programming concepts.

## CLI first, MCP as fallback

Use the `ctx7` CLI through the Bash tool. Use the Context7 MCP tools (`resolve-library-id`, `query-docs`) only when `ctx7` is not available or fails (for example: not installed, not logged in, network error).

## Steps

1. Resolve the library ID, unless the user provides an exact ID in `/org/project` format:
   `ctx7 library <name> "<what to look up>"`
2. Pick the best match (ID format: `/org/project`) by: exact name match, description relevance, code snippet count, source reputation (High/Medium preferred), and benchmark score (higher is better). If results don't look right, try alternate names or queries (e.g., "next.js" not "nextjs", or rephrase the question). Use version-specific IDs (`/org/project/<version>`) when the user mentions a version.
3. Query the docs with the selected ID and a specific question (not single words), scoped to a single concept:
   `ctx7 docs <libraryId> "<question>"` (add `--language <name>` to rank examples in that language first)
   If the question spans multiple distinct concepts (e.g. routing and auth and caching), run a separate `ctx7 docs` call per concept with the same library ID, unless the question is about how the concepts interact — combined queries dilute ranking and return shallow results for each topic.
4. Answer using the fetched docs.

Fallback with MCP: the same steps with `resolve-library-id` (step 1) and `query-docs` (step 3).
EOF
```

The rule is enough; no Context7 skill is needed. `ctx7 setup` can install a skill and overwrite the rule (mode `--mcp` sets up the MCP server, mode `--cli` sets up CLI and skills without MCP). If you run it, check afterwards that the rule and a new skill still put the CLI first.

MCP servers: `context7` (user scope, above) is only the fallback for `ctx7`, and `claude-vscode` comes with the VS Code extension and needs no configuration. Other servers connected to the Claude account (claude.ai connectors, Vercel) are not part of the development environment. GitHub does not use an MCP server; use `gh`.

The native installation updates itself in the background. Set the update channel to `latest` in Claude Code (`/config` → *Auto-update channel*, setting `autoUpdatesChannel`). The VS Code extension brings its own Claude Code version and updates through the Marketplace.

##### ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh            # runs as a systemd service
```

The script replaces `/usr/local/bin/ollama`, `/usr/local/lib/ollama` and `ollama.service`, so own settings belong only in the override file below. If ollama.com is not reachable, install from the GitHub release instead (needs `gh`, 3.1.3):

```bash
sudo systemctl stop ollama
gh release download -R ollama/ollama -p 'ollama-linux-amd64.tar.zst' -D /tmp --clobber
sudo rm -rf /usr/local/lib/ollama
zstd -dc /tmp/ollama-linux-amd64.tar.zst | sudo tar -xf - -C /usr/local
sudo systemctl start ollama
```

Ollama binds to `127.0.0.1` by default. Let it listen on all interfaces, so that Docker containers and other devices in the LAN can reach it. Containers reach it at `http://host.docker.internal:11434`; on Linux, their service in `docker-compose.yml` needs `extra_hosts: ["host.docker.internal:host-gateway"]`.

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null << "EOF"
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
ss -ltn 'sport = :11434'      # expected: *:11434
```

The override file survives updates with `install.sh`.

The Ollama API has no authentication. The firewall (3.1.2) allows port 11434 only from the LAN and from the Docker networks.

Pull the models the spikes need; the spike templates use `gemma4` (`OLLAMA_MODEL=gemma4:latest`, §5.1.4). The service stores models in `/usr/share/ollama/.ollama/models`, and each model needs several GB. To use another disk, add `Environment="OLLAMA_MODELS=<dir>"` to the override file above; the directory must belong to the user `ollama`. Models from Hugging Face land in `~/.cache/huggingface`; `HF_HOME` moves them.

```bash
ollama pull gemma4
ollama list
df -h / /home                                                     # free space
sudo du -sh /usr/share/ollama/.ollama/models ~/.cache/huggingface 2>/dev/null
```

##### JetBrains Toolbox

The Toolbox installs and updates the JetBrains IDEs and updates itself in place. The download link comes from JetBrains' release API. The program goes into `~/.local/share/JetBrains/Toolbox/bin`: next to the Toolbox's own data and IDEs, in the user's data directory (XDG), and writable for self-updates. `--strip-components=1` drops the version from the path, so the desktop entry stays valid after updates. The first start adds the desktop entry.

```bash
url="$(curl -fsSL 'https://data.services.jetbrains.com/products/releases?code=TBA&latest=true&type=release' \
  | jq -r '.TBA[0].downloads.linux.link')"
mkdir -p ~/.local/share/JetBrains/Toolbox
curl -fsSL "$url" | tar -xz --strip-components=1 -C ~/.local/share/JetBrains/Toolbox
~/.local/share/JetBrains/Toolbox/bin/jetbrains-toolbox &
```

Settings in the Toolbox (*Settings*): *Update Toolbox App automatically* and *Update all tools automatically* on; *Launch Toolbox App at system startup* off. Keep the default locations: the IDEs go to `~/.local/share/JetBrains/Toolbox/apps`, the shell scripts (`pycharm`, `idea`, …) to `~/.local/share/JetBrains/Toolbox/scripts`. Put the scripts on `PATH`, so that `pycharm .` opens a project from the terminal:

```bash
grep -qsFx '# JetBrains Toolbox' ~/.profile || cat >> ~/.profile << "EOF"
# JetBrains Toolbox
export PATH="$HOME/.local/share/JetBrains/Toolbox/scripts:$PATH"

EOF
```

#### 3.2.2 Login

```bash
claude                  # log in on first start
claude auth status      # check the login
claude doctor           # "Auto-updates: enabled"
```

### 3.3 mise

#### 3.3.1 Base

Activate mise in the shell. Interactive shells use the full activation; login shells and non-interactive shells (scripts, hooks, Claude Code) use the shims (see §6):

```bash
grep -qsFx '# mise (interactive shells)' ~/.bashrc || cat >> ~/.bashrc << "EOF"
# mise (interactive shells)
eval "$(mise activate bash)"

EOF

grep -qsFx '# mise (login and non-interactive shells)' ~/.profile || cat >> ~/.profile << "EOF"
# mise (login and non-interactive shells)
eval "$(mise activate bash --shims)"

EOF
```

```bash
exec bash -l                  # reload the shell with the new activation
mise doctor                   # must report no problems
```

Create `~/.config/mise/config.toml`. It defines the personal default versions that apply in every directory. A project's `mise.toml` overrides them (§5.1.3).

```bash
mkdir -p ~/.config/mise
cat > ~/.config/mise/config.toml << "EOF"
[settings.github]
# gh usually keeps its token in the system keyring, where mise cannot read it: mise asks gh instead
credential_command = 'gh auth token --hostname "$MISE_CREDENTIAL_HOST"'

[tools]
# --- Runtimes
node = "lts"
java = "lts"                         # Eclipse Temurin (mise's default vendor)

# --- Node-based CLIs (installed through the npm backend)
pnpm = "latest"
"npm:ctx7" = "latest"
"npm:vercel" = "latest"              # provides vc and vercel
gemini = "latest"                    # npm:@google/gemini-cli

# --- Java build tools
maven = "latest"
# gradle = "latest"                  # only if needed

# --- Standalone CLIs (GitHub releases via aqua)
supabase = "latest"
ruff = "latest"
gitleaks = "latest"
shellcheck = "latest"

# --- Python-based CLIs (PyPI backend, installed with uv in their own venv)
"pypi:huggingface_hub" = "latest"    # provides hf
"pypi:pre-commit" = "latest"
EOF
```

#### 3.3.2 Tools

Install everything and check the result:

```bash
mise install
mise ls                  # every tool with its version and the config file that requests it
mise token github        # must show a masked token from gh, not "(none)"
node --version && java -version && mvn -v && supabase --version && hf version
```

Add or remove a tool later, and update the table in §2:

```bash
tool=ripgrep                         # example
mise registry "$tool"                # shows the backend, for example aqua:… or npm:…
mise use -g "$tool@latest"           # adds it to ~/.config/mise/config.toml and installs it
mise unuse -g "$tool"                # removes it from the config and its unused versions
```

#### 3.3.3 Login

```bash
ctx7 login
ctx7 whoami             # check the login
supabase login          # only if you use Supabase cloud
hf auth login           # only if you need private models or uploads
```

Finally, log out and in again once. Programs started from the desktop, such as VS Code, then see the `PATH` changes from 3.2 and 3.3: the mise shims and the scripts of the JetBrains Toolbox (§6).

---

## 4. Check and update scripts

Two small scripts cover the whole host: APT, the tools with their own installer, and mise.

### `~/.local/bin/check-dev-tools.sh`

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/check-dev-tools.sh << "EOF"
#!/usr/bin/env bash
# Checks whether all host-wide tools are up to date. Exit code 1 if something can be updated.
# --cached: print the last result if it is younger than 12 hours (used by the SessionStart hook).
set -uo pipefail
export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"   # hooks may start with a minimal PATH

cache="${XDG_CACHE_HOME:-$HOME/.cache}/check-dev-tools"
if [[ ${1:-} == --cached && -n $(find "$cache.txt" -mmin -720 2>/dev/null) ]]; then
  echo "(result from $(date -r "$cache.txt" '+%Y-%m-%d %H:%M'); run check-dev-tools.sh for a fresh check)"
  cat "$cache.txt"; exit "$(cat "$cache.rc" 2>/dev/null || echo 1)"
fi

checks() {
  local rc=0 upgradable latest_ollama current_ollama latest_python current_python outdated

  echo "== System (APT)"
  upgradable=$(apt list --upgradable 2>/dev/null | grep -v '^Listing' || true)
  if [[ -n "$upgradable" ]]; then echo "$upgradable"; rc=1; else echo "OK"; fi

  echo "== Ubuntu release"
  if do-release-upgrade -c >/dev/null 2>&1; then echo "ubuntu  UPDATE (new LTS release: sudo do-release-upgrade)"; rc=1
  else echo "ubuntu  OK ($(lsb_release -rs 2>/dev/null))"; fi

  echo "== Standalone installers"
  latest_ollama=$(gh api repos/ollama/ollama/releases/latest -q .tag_name | sed 's/^v//')
  current_ollama=$(ollama --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  if [[ "$current_ollama" == "$latest_ollama" ]]; then echo "ollama  OK ($current_ollama)"
  else echo "ollama  UPDATE ($current_ollama -> $latest_ollama)"; rc=1; fi
  if uv self update --dry-run 2>&1 | grep -q 'already on'; then echo "uv      OK ($(uv --version | cut -d' ' -f2))"
  else echo "uv      UPDATE"; rc=1; fi
  latest_python=$(uv python list --only-downloads --output-format json \
    | jq -r '.[] | select(.implementation == "cpython" and .variant == "default") | .version' \
    | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1)
  current_python=$("$HOME/.local/bin/python" --version 2>/dev/null | cut -d' ' -f2)
  if [[ "$current_python" == "$latest_python" ]]; then echo "python  OK ($current_python)"
  else echo "python  UPDATE ($current_python -> $latest_python)"; rc=1; fi
  echo "claude  updates itself ($(claude --version 2>/dev/null | cut -d' ' -f1))"

  echo "== mise (user CLIs and runtimes)"
  outdated=$(mise outdated --global)
  if [[ -n "$outdated" ]]; then echo "$outdated"; rc=1; else echo "OK"; fi

  return "$rc"
}

mkdir -p "${cache%/*}"
checks | tee "$cache.txt"
rc=${PIPESTATUS[0]}
echo "$rc" > "$cache.rc"
exit "$rc"
EOF
chmod +x ~/.local/bin/check-dev-tools.sh
```

### `~/.local/bin/update-dev-tools.sh`

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/update-dev-tools.sh << "EOF"
#!/usr/bin/env bash
# Updates all host-wide tools. DRY_RUN=1 only shows what would be updated.
set -euo pipefail
run() { if [[ "${DRY_RUN:-0}" == 1 ]]; then echo "+ $*"; else "$@"; fi; }
cd "$HOME"                      # mise upgrade then sees the global config, not the mise.toml of a project

echo "== System (APT, includes mise itself)"
run sudo apt update
run sudo apt full-upgrade -y
run sudo apt autoremove -y      # old kernels and packages that nothing needs any more
if command -v snap >/dev/null; then run sudo snap refresh; fi
if command -v flatpak >/dev/null; then run sudo flatpak update -y; fi

echo "== Standalone installers"
run uv self update
latest_python=$(uv python list --only-downloads --output-format json \
  | jq -r '.[] | select(.implementation == "cpython" and .variant == "default") | .version' \
  | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1 || true)
if [[ -n "$latest_python" ]]; then
  run uv python install --preview-features python-install-default --default "${latest_python%.*}"
fi
run uv python upgrade
run claude update
latest_ollama=$(gh api repos/ollama/ollama/releases/latest -q .tag_name | sed 's/^v//' || true)
current_ollama=$(ollama --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
if [[ -n "$latest_ollama" && "$current_ollama" != "$latest_ollama" ]]; then
  run bash -c 'set -o pipefail; curl -fsSL https://ollama.com/install.sh | sh'
fi

echo "== mise (user CLIs and runtimes)"
run mise upgrade
run mise prune --yes          # remove versions that no config requests any more

echo "== Editor (VS Code extensions)"
if command -v code >/dev/null; then run code --update-extensions; fi

if [[ -f /var/run/reboot-required ]]; then echo "== Reboot required (kernel or driver update)"; fi

echo "== Verification"
bash ~/.local/bin/check-dev-tools.sh
EOF
chmod +x ~/.local/bin/update-dev-tools.sh
```

Notes:

- Python: the check compares the default Python of uv with the newest stable CPython that uv offers. The update makes a new minor version the default and raises every installed version to its newest patch (`uv python upgrade`).
- `mise outdated --global` checks only the global config. Without `--global`, it also checks the `mise.toml` of the current directory.
- `node = "lts"` and `java = "lts"` follow the current LTS line. `mise upgrade` installs new patch releases. When a new LTS major appears, the alias resolves to it and `mise upgrade` installs it.
- `mise upgrade --bump` rewrites a pinned major version in a config file to the newest one. Use it in projects only on purpose (§5.1.3).

### SessionStart hook for Claude Code

Claude Code runs the check at every start. The output goes into Claude's context, and Claude points out outdated tools; a fresh check takes about ten seconds. `--cached` keeps the start fast: it prints the stored result while it is younger than 12 hours. The command merges the hook into `~/.claude/settings.json` and replaces other `SessionStart` hooks there.

```bash
mkdir -p ~/.claude
[ -f ~/.claude/settings.json ] || echo '{}' > ~/.claude/settings.json
jq '.hooks.SessionStart = [{"matcher": "startup", "hooks": [{"type": "command",
      "command": "~/.local/bin/check-dev-tools.sh --cached || true", "timeout": 60,
      "statusMessage": "Checking dev tool versions..."}]}]' \
  ~/.claude/settings.json > ~/.claude/settings.json.tmp \
  && mv ~/.claude/settings.json.tmp ~/.claude/settings.json
```

### Skill `/update-tools` (optional)

A user-level skill: on request, Claude Code runs the check and shows the update commands. The update itself stays with you, because it needs sudo.

```bash
mkdir -p ~/.claude/skills/update-tools
cat > ~/.claude/skills/update-tools/SKILL.md << "EOF"
---
name: update-tools
description: Check all global CLIs for the latest (LTS) version and show update commands
---
Run `~/.local/bin/check-dev-tools.sh`. If a line is marked UPDATE or a mise tool [MISSING], run
`DRY_RUN=1 ~/.local/bin/update-dev-tools.sh` and show the result; the user runs the real update
(it needs sudo). For a missing tool outside mise, show its install command from §3 of the
environment documentation.
EOF
```

### Final check of the host

After chapter 3 and the scripts above, check the whole host once. The Supabase test pulls several GB of images, the PyTorch test downloads several GB of packages into the uv cache.

```bash
~/.local/bin/check-dev-tools.sh                       # all host tools up to date
shellcheck ~/.local/bin/*-dev-tools.sh                # both scripts pass without findings
mise doctor                                           # no problems
curl -s http://127.0.0.1:11434/api/version            # Ollama answers
ollama run gemma4 "Answer with OK"                    # a model loads and answers
gh auth status && claude auth status && ctx7 whoami   # all logins are valid
mkdir -p ~/tmp/supabase-check && cd ~/tmp/supabase-check
supabase init
docker network create -o com.docker.network.bridge.host_binding_ipv4=127.0.0.1 supabase_network_supabase-check
supabase start                                        # the local Supabase stack runs in Docker (§5.1.5)
docker port supabase_db_supabase-check                # must show 127.0.0.1:54322 only
supabase stop --no-backup && docker network rm supabase_network_supabase-check
cd ~ && rm -rf ~/tmp/supabase-check
uv run --no-project --with torch python -c \
  "import torch; print(torch.cuda.is_available(), torch.version.cuda)"   # NVIDIA hosts: True and the CUDA version
```

### Disk space and cleanup

Docker images, caches and models grow with every spike. Check the space about once a month, or when less than 20 % of the disk is free. The commands below do not touch the data of a spike: Supabase keeps the databases in Docker volumes, and §5.5 removes them per spike.

```bash
df -h / /home                                   # free space
docker system df                                # images, containers, volumes and build cache
docker ps -a --filter name=supabase_db_ --format '{{.Names}}\t{{.Status}}'   # the Supabase stacks of the spikes
du -sh ~/.cache/uv ~/.local/share/pnpm ~/.m2/repository ~/.cache/huggingface 2> /dev/null
sudo du -sh /usr/share/ollama/.ollama/models    # Ollama models
```

Free space:

```bash
docker image prune -a --filter "until=720h"     # images older than 30 days that no container uses; asks first
docker builder prune --filter "until=720h"      # build cache older than 30 days; asks first
uv cache prune                                  # cache entries that nothing uses
pnpm store prune                                # packages that no project uses any more
ollama list                                     # then remove the models you no longer need: ollama rm <model>
```

`docker image prune -a` also removes the images of stopped Supabase stacks; the next `supabase start` downloads them again. `~/.m2/repository` has no prune command: delete it when it is large, and Maven downloads again what a project needs. Do not run `docker volume prune -a`: it deletes the databases of stopped spikes.

---

## 5. Spike projects

How to set up a spike project on the host from §3: in Python (§5.1), in Node with TypeScript (§5.2) or in Java (§5.3). The three language subchapters have the same ten sections. §5.4 turns each of them into a template repository, so that a new spike takes one command, and §5.5 ends a spike. Supabase, Ollama, the secrets and the extended variant work the same in all three, so §5.2 and §5.3 describe what differs and refer to §5.1 for the rest. Code in another language inside a spike requests its runtime in the project's `mise.toml` (§5.1.3), for example `node = "lts"` or `java = "lts"`.

### 5.1 Python

A spike is a local, often short-lived Python project of one person:

- **Python package in src layout**, managed with **uv**. Code runs directly on the host (`uv run`); containers for the project's own code belong to the extended variant (§5.1.10).
- **PostgreSQL** through the **Supabase CLI**, which runs it in Docker.
- **Ollama** as the local LLM backend on the host (§3.2.1).
- **pytest + ruff** for testing, linting and formatting. The pre-commit hooks run ruff and gitleaks before every commit; `/verify` runs all checks (§5.1.8).
- **GitHub** as the remote: a private repository, created with the **gh CLI**. Commits go directly to `main`.
- **gitleaks** as secret scan before every commit. Before a repository is shared or made public, the full history is scanned as well (§5.1.10).
- **mise** loads the project's CLIs and `.env` (`mise.toml`), and **1Password** holds the secrets (§5.1.6).

Supabase stays on `127.0.0.1`: a prepared Docker network keeps its ports there (§5.1.5). Ollama listens on all interfaces, and the firewall allows its port only from the LAN and from the Docker networks (§3.1.2, §3.2.1). All configuration comes from environment variables and `.env`.

This is the **light variant**: it suits local, often short-lived projects such as spikes. §5.1.10 records why it leaves out the pull-request workflow, CI, containers and some Claude Code extras, and how to add them when a project grows.

#### 5.1.1 Starting a spike with Claude Code

This file is the working basis for Claude Code. It lives in every new project as `docs/ENVIRONMENT.md`, and Claude sets up the project according to it.

When the template repositories exist (§5.4), `new-spike` creates a new spike with one command. The steps below then apply only to the templates themselves and to spikes without a template.

**Requirement:** The host meets §3 and §4: `check-dev-tools.sh` reports no missing tool (`[MISSING]`), you are logged in to `gh`, `claude` and `ctx7`, and git knows your name and e-mail address (§3.1.3).

1. Create the project folder and copy this file into its `docs` folder. You have to do this by hand, because Claude is started inside this folder afterwards:
   ```bash
   name=my-spike                    # <PROJECT_NAME>: lower case, words joined with -
   mkdir -p ~/Documents/workspaces/git/"$name"/docs
   cp "<PATH>/ENVIRONMENT.md" ~/Documents/workspaces/git/"$name"/docs/
   cd ~/Documents/workspaces/git/"$name"
   ```
2. Start Claude Code in the project folder (`claude` in the terminal, or open the folder in VS Code). On the first start, Claude asks whether you trust the folder. Confirm it.
3. Ask Claude to set up the project and give it the placeholder values, for example:
   ```text
   Set up this project according to docs/ENVIRONMENT.md. Work through the
   bootstrap checklist in §5.1.9 from step 2 up to and including step 10.
   Placeholders: <PROJECT_NAME>=my-spike (package: src/my_spike).
   Service: my_spike.api on port 8000 (or: no service yet). Write CLAUDE.md
   from the template in §5.1.8 and reference docs/ENVIRONMENT.md in it.
   Ask before you push anything or create a GitHub repository.
   ```
4. When the scaffold is in place, run `/init` in Claude Code. Because `CLAUDE.md` already exists, `/init` does not overwrite it. It suggests improvements based on the actual project. Accept the ones that fit.
5. Restart Claude Code so that it loads `.claude/settings.json` (permissions, hooks) and the skills.
6. Let Claude create the private GitHub repository and push the first commit (§5.1.9, step 11). Claude runs this with `gh` after you have confirmed it.

After that, `docs/ENVIRONMENT.md` is the reference for the environment, and `CLAUDE.md` holds the project-specific instructions. When the environment changes, update the master copy, raise its version and add a row to the change log, then copy it to the other projects. The version line at the top shows which version a project follows.

#### 5.1.2 Project structure

```text
<PROJECT_ROOT>/
├── .claude/                # Claude Code configuration (settings, commands, skills)
├── .vscode/                # recommended extensions and workspace settings for VS Code (versioned)
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
├── .pre-commit-config.yaml # git hooks (ruff, gitleaks secret scan, large-file check)
├── mise.toml               # CLIs of the project and the loading of .env (mise)
├── .gitleaksignore         # optional: fingerprints of accepted gitleaks findings (§5.1.3)
├── pyproject.toml          # project metadata, dependencies, dev group, ruff and pytest configuration
├── uv.lock                 # uv lock file (versioned)
├── .python-version         # Python version for uv (versioned)
├── README.md               # created by uv init
├── .gitignore
├── .env.example            # template for .env (versioned)
├── .env                    # local values (not versioned)
└── secrets.env             # 1Password references for op run, no secrets (versioned, §5.1.6)
```

The project uses the common **src layout**. `<package>` is the project name in lower case with `_` instead of `-` (`<PROJECT_NAME>` = `my-spike` becomes `src/my_spike/`). `uv sync` installs the package in editable mode into `.venv`. This makes it importable everywhere, in `tests/` and in `scripts/`, without changing `sys.path`.

- **`src/<package>/`** contains all code, including the code of a long-running service. You start a service with `uv run python -m <package>.<module>`; the default entry point from `[project.scripts]` runs with `uv run <PROJECT_NAME>`.
- **`scripts/`** contains only thin entry scripts for tasks that run once and then end (for example, loading data). The logic lives in the package.
- **`tests/`** contains all tests. Tests that need the running stack have the marker `integration` (see §5.1.7).

#### 5.1.3 Configuration files

Runtimes and tools of the project:

| Component | Version channel | Where it is set |
|---|---|---|
| Python | latest stable version | Installed through uv (§3.2.1), pinned in the project with `.python-version` and `requires-python` |
| PostgreSQL | latest major version supported by Supabase | `major_version` in `supabase/config.toml` (default from `supabase init`). Supabase supports only selected major versions |
| pytest, ruff, pre-commit | latest when the project is created, pinned in `uv.lock`, raised with `uv lock --upgrade` | Dev group of the project (`uv add --dev pytest ruff pre-commit`), run through `uv run`. The global ruff and pre-commit from mise are only a convenience outside projects |
| Other CLIs of the project (Supabase CLI, gitleaks) | latest | `mise.toml` (below); `mise.lock` records the exact versions if you use it |

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
markers = ["integration: needs the local stack (supabase start)"]
strict = true                    # unknown markers and options are errors
```

`uv init --package` also adds a `[build-system]` table with the `uv_build` backend; keep it as generated. `[tool.pytest]` and `strict` need pytest 9 or newer (older versions read `[tool.pytest.ini_options]`). With `strict = true`, a misspelled marker such as `@pytest.mark.integraton` stops the test run; otherwise the test would quietly run with the unit tests. New pytest versions can add strict checks; they show up when `/deps` raises pytest and runs the tests.

`uv add` writes the current version as a lower bound (`>=`). Add an upper bound only when a new major version breaks compatibility. `uv lock --upgrade` raises all packages to the latest version. `uv sync` installs the `dev` group by default; `--no-dev` leaves it out. ruff is in the dev group, so the same version from `uv.lock` runs locally, in the Claude Code hook, in the pre-commit hooks and in CI; `uv lock --upgrade` raises it.

**`.python-version`**: one line with the latest stable Python version (`<X.Y>`). `uv init` writes it with the minor version of the default Python (§3.2.1), `uv python pin <X.Y>` changes it; `uv sync` and `uv run` read it. Without this file, uv picks the latest installable version that matches `requires-python`.

**`uv.lock`**: created by uv and versioned. Do not edit it by hand.

**`mise.toml`**: the CLIs the project needs and the loading of `.env`. Commit it; `.env` stays in `.gitignore`. Python is not listed here, because uv provides it; list it only if the project needs a Python that uv cannot provide.

```toml
[tools]
supabase = "latest"
gitleaks = "latest"                  # the secret scan in the pre-commit hook and in CI (§5.1.10)

[env]
_.file = { path = ".env", redact = true }   # loads .env if it exists; keeps the values out of mise's output
# _.path = "bin"                             # optional: put the project's bin/ on PATH

[settings]
python.uv_venv_auto = "source"       # activates the .venv that uv created next to uv.lock

[tasks.check]
description = "Lint and format check"
run = "uv run ruff check . && uv run ruff format --check ."

[tasks.test]
description = "Unit tests"
run = "uv run pytest"

[tasks.integration]
description = "Integration tests; they need the running stack"
run = "uv run pytest -m integration"

[tasks.start]
description = "The entry point from [project.scripts]"
run = "uv run <PROJECT_NAME>"
```

The tasks give the same commands in every language: `mise run check`, `mise run test`, `mise run integration` and `mise run start`. `CLAUDE.md`, the skill `/verify` and `op run` use them (§5.1.6, §5.1.8). Tasks always run with the variables from `.env`. `[env]` and `python.uv_venv_auto` take effect in interactive terminals; §6 describes the other cases. Every process started in the project directory receives the values from `.env`, so keep only what the project needs there. The first time you enter the project, mise asks you to trust the file; `mise trust` does it at once, and `mise install` installs the CLIs. Optionally, `mise lock` writes `mise.lock` with the exact versions and checksums. Commit it if every machine and CI must use exactly the same builds; then `mise install --locked` installs from it.

**`src/<package>/config.py`**: all settings in one place. pydantic-settings reads environment variables and `.env`, checks the types and stops at startup when a required value is missing. Field names are the variable names in lower case (`postgres_password` ↔ `POSTGRES_PASSWORD`). Secrets are `SecretStr` fields: logs and error messages show `**********`, and only `get_secret_value()` returns the value. `database_url` encodes user, password and database name, so that characters such as `@`, `:`, `/` or `#` in a password do not break the URL.

```python
from functools import lru_cache
from urllib.parse import quote

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration, loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 54322
    postgres_user: str = "postgres"
    postgres_password: SecretStr  # required: no default; hidden in logs and error messages
    postgres_db: str = "postgres"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma4:latest"

    @property
    def database_url(self) -> str:
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password.get_secret_value(), safe="")
        database = quote(self.postgres_db, safe="")
        return (
            f"postgresql://{user}:{password}@{self.postgres_host}:{self.postgres_port}/{database}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Code reads settings only through `get_settings()`, never through `os.getenv`. Real environment variables take priority over `.env`. Docker Compose uses this to set the container values. `.env` is read from the current working directory, so run all commands from the project root.

**`.env.example`**: template for `.env` with all variables the project uses (see §5.1.4). It is versioned; `.env` is not. Local defaults such as the Supabase password `postgres` are no secrets; real secrets do not belong in `.env`: their 1Password references go into `secrets.env` (§5.1.6).

```dotenv
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=54322
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=postgres
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=gemma4:latest
```

**`tests/`**: unit tests for the settings and integration tests for the database connection and for Ollama. The integration tests only run with `uv run pytest -m integration` (`mise run integration`).

```python
# tests/test_config.py
from urllib.parse import unquote, urlsplit

import pytest
from pydantic import ValidationError

from <package>.config import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Test the defaults, not the values of the shell."""
    names = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_database_url(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    settings = Settings(_env_file=None)
    assert settings.database_url.endswith("@127.0.0.1:54322/postgres")
    assert "secret" not in repr(settings)  # SecretStr hides the password


def test_password_with_special_characters(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:w/rd#1")
    url = urlsplit(Settings(_env_file=None).database_url)
    assert (url.hostname, url.port) == ("127.0.0.1", 54322)
    assert unquote(url.password) == "p@ss:w/rd#1"


def test_missing_password_fails():
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

```python
# tests/test_llm.py
import json
from urllib.request import urlopen

import pytest

from <package>.config import get_settings


@pytest.mark.integration
def test_model_is_available():
    settings = get_settings()
    with urlopen(f"{settings.ollama_base_url}/api/tags", timeout=10) as response:
        names = [model["name"] for model in json.load(response)["models"]]
    assert settings.ollama_model in names, "model not pulled"
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
enabled = false                  # no log containers (Logflare, Vector); Studio shows no logs
```

`supabase init` also creates `supabase/.gitignore`.

**`.pre-commit-config.yaml`**: ruff and gitleaks as local hooks, and a check for large files. The ruff hooks run through `uv run`, so pre-commit uses the same ruff version as `uv.lock`, the Claude Code hook and CI. The gitleaks hook runs gitleaks from mise (`mise.toml`), the same version as in CI. `language: unsupported` needs pre-commit 4.4 or newer (older versions call it `system`). `uv run pre-commit autoupdate` sets the `rev` of the other hooks to the latest tag, also in a new file; `uv run pre-commit install` activates the hooks. Run `uv run pre-commit install` again after `.venv` has been recreated, because the git hook stores the path to the Python interpreter.

```yaml
repos:
  - repo: local                    # ruff from the dev group, gitleaks from mise
    hooks:
      - id: ruff-check
        name: ruff check
        entry: uv run ruff check --fix --force-exclude
        language: unsupported
        types_or: [python, pyi]
        require_serial: true
      - id: ruff-format
        name: ruff format
        entry: uv run ruff format --force-exclude
        language: unsupported
        types_or: [python, pyi]
        require_serial: true
      - id: gitleaks
        name: gitleaks
        entry: gitleaks git --pre-commit --redact --staged --verbose
        language: unsupported
        pass_filenames: false
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v<latest-pre-commit-hooks-version>
    hooks:
      - id: check-added-large-files
```

The `gitleaks` hook scans the staged changes of every commit and blocks the commit if it finds a secret. It runs gitleaks from mise; in CI, `jdx/mise-action` installs the same version (§5.1.10). A false positive is accepted only explicitly: with a `gitleaks:allow` comment on the line, or with the fingerprint of the finding in `.gitleaksignore`; the commit message states the reason. Never bypass the hooks with `git commit --no-verify`: in the light variant, the hook is the only scan until the full history is checked before sharing or publishing (§5.1.10).

The hook `check-added-large-files` blocks a new file larger than 500 KB, for example a data dump or a model file: once pushed, it stays in the git history. A large file that belongs in the repository goes through git-lfs (`git lfs track '<pattern>'`); the hook skips such files.

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

**`.gitignore`** (relevant patterns): `.env`, `.env.*`, `!.env.example`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.venv`, `mise.local.toml`, `dist/`, `.supabase/`, `supabase/.temp/` and `supabase/seed.sql` (if generated).

Decisions about what this template leaves out on purpose (type checking, `.editorconfig`, `.nvmrc`, update bots, CI, the pull-request workflow, containers) are recorded with their reasons in §5.1.10.

#### 5.1.4 Environment variables and ports

All variables come from the environment or from `.env` (template `.env.example`). The code reads them through `Settings` in `src/<package>/config.py` (§5.1.3). Each new variable gets a field there. The `POSTGRES_*` and `OLLAMA_*` variables are in the templates from the start; add the others when the project uses them.

| Variable | Purpose | Local example value |
|---|---|---|
| `POSTGRES_HOST` / `POSTGRES_PORT` | PostgreSQL (Supabase) | `127.0.0.1` / `54322` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Admin connection | `postgres` / `postgres` (CLI default) / `postgres` |
| `<SERVICE>_PG_USER` / `<SERVICE>_PG_PASSWORD` | Separate database role for the service (optional) | `<package>_<service>` / `<local-pw>` |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Local LLM | `http://127.0.0.1:11434` / `gemma4:latest` (pulled in §3.2.1) |
| `LLM_TIMEOUT_SECONDS` | LLM timeout | `120` |
| `<SERVICE>_HOST` / `<SERVICE>_PORT` | Host interface and port of the service | `127.0.0.1` / `<port>` |

The admin connection (`POSTGRES_*`) is for migrations, tests and administration. A service connects with its own database role (`<SERVICE>_PG_*`) as soon as the project defines one.

Ports (bound to `127.0.0.1`, for Supabase through the prepared network, §5.1.5; only Ollama listens on all interfaces, §3.2.1):

| Port | Service |
|---|---|
| 54321 | Supabase API |
| 54322 | PostgreSQL |
| 54323 | Supabase Studio |
| 54324 | Mailpit (Supabase, test mailbox) |
| `<port>` | the project's own service |
| 11434 | Ollama (all interfaces; the firewall allows the LAN and the Docker networks, §3.1.2) |

#### 5.1.5 Local services

**PostgreSQL (Supabase CLI)** runs in containers that the Supabase CLI manages:

```bash
# once per project, before the first supabase start (see below)
docker network create -o com.docker.network.bridge.host_binding_ipv4=127.0.0.1 "supabase_network_<PROJECT_NAME>"

docker ps --filter name=supabase_db_ --format '{{.Names}}'   # which spike's stack runs now
supabase stop --all             # stop the stacks of all spikes (see below); their data stays
supabase start                  # start the Supabase CLI containers, apply migrations on the first start
docker port "supabase_db_<PROJECT_NAME>"   # check: must show 127.0.0.1:54322 only
supabase status                 # URLs, ports and default credentials (DB_URL, STUDIO_URL, …)
supabase db reset               # rebuild the database: migrations + supabase/seed.sql
supabase migration new "<name>"   # new migration supabase/migrations/<timestamp>_<name>.sql
supabase db query '<sql>'       # run one SQL statement (--read-only for reading, -f for a file)
supabase db lint --fail-on error   # check the database functions for errors
supabase db advisors            # Supabase's security and performance checks (--fail-on warn to fail on warnings)
supabase stop                   # stop (--no-backup discards the local data)
psql -h 127.0.0.1 -p 54322 -U postgres postgres   # SQL console (password from ~/.pgpass)
```

**Keep Supabase on localhost.** The Supabase CLI publishes all its ports on all network interfaces, and it has no setting to change this; `supabase start` says so in its security notice. On a shared network, the database with its default password and Studio without a login would then be reachable by others. The CLI creates its Docker network `supabase_network_<project_id>` only if it does not exist yet. If you create this network first, with `127.0.0.1` as its default host address, `supabase start` uses it, and all Supabase ports stay on `127.0.0.1`. `<project_id>` is `project_id` in `supabase/config.toml`, by default the folder name `<PROJECT_NAME>`. The network stays when Supabase stops. If Supabase was already started before the network existed, run `supabase stop` first (it removes its own network) and then create the network.

**One Supabase stack at a time.** All spikes use the same ports (54321 to 54324 from `supabase init`), so only one stack can run. While the stack of another spike runs, `supabase start` fails because the ports are taken. Stop it first with `supabase stop --all`; the data of every spike stays in its Docker volumes. To run two stacks at the same time, give one spike its own ports: every `port` setting in `supabase/config.toml`, `POSTGRES_PORT` in `.env.example` and `.env`, and a line for the new port in `~/.pgpass`.

The default connection is `postgresql://postgres:postgres@127.0.0.1:54322/postgres`. For console access, `~/.pgpass` holds the password (§3.1.2), so that it does not end up in URLs or the shell history. If you use a different `postgres` password in `.env`, you must set it again after every `db reset` (connect as `supabase_admin`, because `postgres` is not a real superuser in Supabase). It is easier to use the CLI default password locally all the time. The same applies to the project's own login roles: after every `db reset`, a small idempotent script sets their passwords again from `.env`.

**Ollama** runs natively on the host as the systemd service `ollama` (§3.2.1); `ollama pull <model>` downloads models. It listens on all interfaces: host processes use `http://127.0.0.1:11434` (`OLLAMA_BASE_URL` in `.env`), containers `http://host.docker.internal:11434` (§5.1.10).

#### 5.1.6 Secrets with 1Password

`.env` holds only local values, such as the Supabase password `postgres`. Real secrets stay in 1Password: `secrets.env` lists them as `op://` references, and `op run` resolves the references for one command and masks the values in its output. Environment variables take priority over `.env` in pydantic-settings (§5.1.3), so the program gets the resolved values. A variable is in `.env` or in `secrets.env`, never in both: `mise run` loads `.env` after `op run` has set the resolved value, and mise's `[env]` replaces variables that already exist, so the local value would win.

`secrets.env` holds no secret and is versioned, so the project works after a fresh clone; gitleaks still checks it. mise does not load it on purpose: mise sets the variables from its `[env]` again whenever a mise tool starts through its shim, for example `pnpm` or `mvn`, and would replace the resolved values with the references.

```bash
cat >> secrets.env << "EOF"
API_KEY=op://Private/<item>/credential
EOF
op run --env-file secrets.env -- mise run start    # the same command in every language
```

#### 5.1.7 Conventions

- **Tools**: CLI before MCP (see §1). All CLIs are installed once on the host (§2, §3) and kept at the latest (LTS) version. Project tools (pytest, ruff, pre-commit) run through `uv run` from the dev group.
- **Code style**: ruff with the rule groups `E`, `F`, `I`, `UP`, `B` and `ruff format` as formatter, line length 100 (§5.1.3). pre-commit checks and formats before every commit. No type checking (§5.1.10).
- **Project layout**: src layout, all code in the package `src/<package>/`. Entry points are modules with `main()` and `if __name__ == "__main__": main()`, started with `uv run python -m <package>.<module>`; the default entry point from `[project.scripts]` runs with `uv run <PROJECT_NAME>`. `scripts/` only contains thin entry scripts that import from the package.
- **Configuration**: only through `get_settings()` from `src/<package>/config.py` (pydantic-settings). No `os.getenv` in the rest of the code. Required values have no default, so a missing value shows up at startup. Secrets are `SecretStr` fields, so they do not show up in logs.
- **Secrets**: Real secrets only in 1Password; `secrets.env` holds their `op://` references, and `op run` resolves them (§5.1.6). `.env` (ignored by git, mode `600`) holds only local values. Secrets never go into the repository, not even in tests or examples. gitleaks checks every commit (§5.1.3); before a repository is shared or made public, the full history is checked as well (§5.1.10). Accepted false positives are recorded explicitly, with the reason in the commit message. Git hooks are never bypassed (`--no-verify`).
- **Naming**: Files and modules in `snake_case`. Migrations are named `YYYYMMDDHHMMSS_<description>.sql` (created by `supabase migration new`). Recommended: group tables and related files by an area prefix (`<area>_*`).
- **Commits**: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`), imperative mood, lower case.
- **Branching**: Commits go directly to `main`. A local branch can hold an experiment that might be dropped; it is merged locally or deleted. Pull requests belong to the extended variant (§5.1.10).
- **Testing**: All tests are in `tests/` and run with pytest. Tests that need the running stack (database, containers, Ollama) have `@pytest.mark.integration`. `uv run pytest` skips them by default; `uv run pytest -m integration` runs them while the stack is up. Keep at least one test of each kind (§5.1.3). Optional: drift tests that check configuration files against the SQL migrations.
- **Dependencies**: Only through `uv add`/`uv remove`, never edit the lock file by hand. Lower bounds in `pyproject.toml`, an upper bound only for a known breaking change. Updates are made on demand with `/deps` (`uv lock --upgrade` and more); there is no update bot (§5.1.10). `uv.lock` and `.python-version` are versioned. Python commands always run through `uv run`.

#### 5.1.8 Claude Code setup

##### Components

| Element | Location | Purpose |
|---|---|---|
| `CLAUDE.md` | Root | Project instructions (template below) |
| `.claude/settings.json` | Project | Permissions and hooks, versioned |
| `.claude/settings.local.json` | Project | Personal overrides, not versioned |
| `.claude/skills/<name>/SKILL.md` | Project | Project skills; each skill is also a slash command (`/verify`, `/deps`). A skill folder can be a symlink |
| `~/.claude/settings.json` | User | Global hooks and permissions: the version check at startup (§4) and the deny rule for `.env` (§3.2.1) |
| `~/.claude/rules/*.md` | User | Global rules for all projects (§3.2.1) |
| `~/.claude/skills/<name>/` | User | Global skills |

Skills replace the older slash commands in `.claude/commands/`, which still work. A skill is a folder with a `SKILL.md`; its `name` is the slash command. With `disable-model-invocation: true`, only you start the skill, not Claude; use it for skills with side effects (`/deps`, `/ship`).

##### Structure of `CLAUDE.md` (template)

````markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
The development environment is described in docs/ENVIRONMENT.md: §5.1 for this Python spike, §6 and §7.
Read the host chapters (§2 to §4) only when a host tool is involved.

## Project overview
<One paragraph: purpose of the project and its main components.>

## Tooling
- Prefer CLIs over MCP servers: use `gh`, `supabase`, `psql`, `docker`, `uv`, `ctx7` directly.
  Use an MCP server only when no CLI covers the task.
- All CLIs are installed globally on the host and kept at the latest (LTS) version.
- Run project tools through uv: `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`.
- Common commands are mise tasks: `mise run check`, `mise run test`, `mise run integration`, `mise run start`.
- Run all commands from the project root.
- Never bypass git hooks (`--no-verify`). A secret found by gitleaks is removed, not skipped.
- Commit directly to `main` with Conventional Commits; ask before every push.

## Commands
```bash
mise trust && mise install       # CLIs of the project and the loading of .env
uv sync                          # install dependencies and the package
cp .env.example .env && chmod 600 .env   # then fill in the required values
supabase stop --all              # stops the stacks of other spikes, which use the same ports
supabase start                   # local database
mise run start                   # entry point from [project.scripts]
op run --env-file secrets.env -- mise run start   # the same, with the secrets from 1Password
uv run python -m <package>.<module>   # own service (if any)
mise run check                   # ruff: lint and format check
mise run test                    # unit tests
mise run integration             # database and Ollama; needs the running stack
```

## Architecture
<Components with paths and ports. Code in src/<package>/, entry points as python -m <package>.<module>.>

## Configuration
All settings come from `get_settings()` in src/<package>/config.py (pydantic-settings). Never use os.getenv elsewhere.
Real secrets are 1Password references (op://) in secrets.env; commands that need them run with `op run --env-file secrets.env -- …`.

## Beware
<Pitfalls that are not obvious>

## Further reading
- docs/ENVIRONMENT.md (§5.1, §6, §7)
````

Principles: every command can be copied and pasted. "Beware" sections record pitfalls that are not obvious. References point to files instead of repeating their content.

##### `.claude/settings.json` (template)

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": [
      "Bash(uv sync *)",
      "Bash(mise run check *)",
      "Bash(mise run test *)",
      "Bash(mise run integration *)",
      "Bash(mise run start *)",
      "Bash(uv run pytest *)",
      "Bash(uv run ruff *)",
      "Bash(uv run python -m <package>.*)",
      "Bash(uv run <PROJECT_NAME> *)",
      "Bash(ctx7 library *)",
      "Bash(ctx7 docs *)",
      "Bash(ctx7 search *)",
      "Bash(docker port *)",
      "Bash(supabase start)",
      "Bash(supabase status *)",
      "Bash(supabase db lint *)",
      "Bash(supabase db advisors *)",
      "Bash(git status *)",
      "Bash(git diff *)",
      "Bash(git log *)",
      "Bash(git fetch *)"
    ],
    "ask": [
      "Bash(git push *)",
      "Bash(uv add *)",
      "Bash(uv remove *)",
      "Bash(uv lock *)",
      "Bash(psql *)",
      "Bash(supabase db query *)",
      "Bash(supabase db reset *)",
      "Bash(supabase stop *)",
      "Bash(op run *)"
    ],
    "deny": [
      "Read(.env)"
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

`$schema` gives completion and validation in VS Code. Permission rules use the form `Bash(<command> *)`: the trailing ` *` matches the command with or without arguments. `deny` keeps `.env` out of Claude's file tools, file commands such as `cat` and search results, so values do not reach the conversation by accident; when Claude needs a value, it asks. Programs that open files themselves are not covered (§3.2.1). The hook formats the code after every edit. If ruff still finds problems, the hook exits with code 2, so Claude sees the findings (stderr) and fixes them. When the code is clean, the hook is silent.

##### Skill `/verify` (template, `.claude/skills/verify/SKILL.md`)

```markdown
---
name: verify
description: Run the local verification (the mise tasks check, test and integration, and the database checks)
---
Run, in order, and report pass/fail per step with the failing output:
1. mise run check
2. mise run test
3. If `supabase status` shows the stack running: mise run integration
4. If the stack is running and the project has migrations: supabase db lint --fail-on error, then supabase db advisors
```

The git hooks (ruff, secret scan, large files) are not part of `/verify`; they run on every commit, and `/deps` runs them once after it raises their versions.

##### Skill `/deps` (template, `.claude/skills/deps/SKILL.md`)

```markdown
---
name: deps
description: Update the project dependencies and hook versions, then verify
disable-model-invocation: true
---
Run, in order, and report what changed (git diff --stat):
1. uv lock --upgrade, then uv sync
2. uv run pre-commit autoupdate, then uv run pre-commit run --all-files
   (runs the new hook versions once; the ruff hooks may fix files)
3. Run /verify (.claude/skills/verify/SKILL.md)
```

Updates are made on demand with this skill; there is no update bot (§5.1.10).

##### MCP servers

Principle CLI before MCP: create project-wide MCP servers (`.mcp.json`) only when no CLI covers the task; the template for the local Supabase instance belongs to the extended variant (§5.1.10). The user-level server `context7` (§3.2.1) stays as a fallback for the CLI `ctx7`.

##### Skills

```bash
# Make a skill from an installed Python package available as a project skill via symlink
mkdir -p .claude/skills
ln -s "../../.venv/lib/python<X.Y>/site-packages/<installed-package>/<path-to-skill>" ".claude/skills/<skill-name>"
```

Note: the symlink points into the project's `.venv`. It breaks when the Python version changes, or when `.venv` is recreated and `uv sync` has not run yet.

#### 5.1.9 Bootstrap checklist for a new spike

The steps that Claude follows in a new project (§5.1.1), or that you run yourself. The command blocks use the shell variable `name` for `<PROJECT_NAME>`.

1. Once per host (skip if already done): set up the host as described in §3 and §4. `check-dev-tools.sh` must report no missing tool (`[MISSING]`); a pending update or a new Ubuntu release does not block a new spike.
2. Create the project with uv, its dependencies and the folders. `uv init` creates `pyproject.toml`, the src layout with a sample `main()` and its `[project.scripts]` entry, the build backend, `.python-version` with the minor version of the default Python (§3.2.1), `README.md`, `.gitignore` and the git repository on the branch `main` (§3.1.3):
   ```bash
   name=my-spike                        # <PROJECT_NAME>: lower case, words joined with -
   mkdir -p ~/Documents/workspaces/git/"$name" && cd ~/Documents/workspaces/git/"$name"
   uv init --package --name "$name"
   uv add pydantic-settings "psycopg[binary]"
   uv add --dev pytest ruff pre-commit
   mkdir -p scripts tests docs .claude .vscode
   ```
   Then add `[tool.ruff]` and `[tool.pytest]` to `pyproject.toml`, and create `.vscode/extensions.json` and `.vscode/settings.json` (§5.1.3).
3. Create `mise.toml` (§5.1.3), then trust it and install its CLIs:
   ```bash
   mise trust && mise install
   ```
4. Run `supabase init`. Keep the default `major_version` and check the settings against §5.1.3 (ports, `[analytics]`). Then create the Supabase network (§5.1.5) before the first `supabase start`:
   ```bash
   supabase init
   docker network create -o com.docker.network.bridge.host_binding_ipv4=127.0.0.1 "supabase_network_$name"
   ```
5. Create `.env.example` with the variables from §5.1.4 and complete `.gitignore` (§5.1.3). If the spike needs secrets, list their references in `secrets.env` (§5.1.6). Then create `.env` from the template:
   ```bash
   cp .env.example .env && chmod 600 .env
   ```
6. Create `src/<package>/config.py` and the test files `tests/test_config.py`, `tests/test_database.py` and `tests/test_llm.py` (§5.1.3).
7. If the project has its own service: create `src/<package>/<module>.py` as entry point; it runs with `uv run python -m <package>.<module>`. Containers belong to the extended variant (§5.1.10).
8. Create `.pre-commit-config.yaml` with the hooks from §5.1.3, then set the versions of the remote hooks and activate all hooks:
   ```bash
   uv run pre-commit autoupdate
   uv run pre-commit install
   ```
9. Write `CLAUDE.md` from the template in §5.1.8. Create `.claude/settings.json` and the skills `/verify` and `/deps` from their templates in §5.1.8.
10. Start and check the environment:
    ```bash
    uv sync --locked
    supabase stop --all                  # the stack of another spike would block the ports (§5.1.5)
    supabase start
    docker port "supabase_db_$name"      # must show 127.0.0.1:54322 only
    mise run check
    mise run test
    mise run integration                 # database and Ollama
    mise run start                       # the entry point from [project.scripts]
    ```
11. Create the private GitHub repository and push the first commit:
    ```bash
    git add -A && git commit -m "chore: initial project setup"
    gh repo create "$name" --private --source . --push
    ```

Later commits go directly to `main` and are pushed after confirmation. When the project grows, add the parts of the extended variant (§5.1.10).

**Places to adapt**

| What | File(s) |
|---|---|
| Project name `<PROJECT_NAME>` | `pyproject.toml` (`name`), `mise.toml` (task `start`), `supabase/config.toml` (`project_id`), Supabase network and database container names (§5.1.5) |
| Package name `<package>` (derived from the project name) | `src/<package>/`, imports, `.claude/settings.json` |
| Ports | `supabase/config.toml`, `.env.example` |
| Python version `<X.Y>` | `.python-version`, `pyproject.toml` (`requires-python`), skill symlinks |
| Hook versions | `.pre-commit-config.yaml` (`uv run pre-commit autoupdate`) |
| CLIs of the project | `mise.toml` (and `mise.lock`, if present) |
| LLM model | `OLLAMA_MODEL` in `.env.example` |
| Skill symlinks | `.claude/skills/*` (set new paths) |
| Repository name | `gh repo create "$name"`; the owner is the account logged in to `gh` |

#### 5.1.10 Decisions and the extended variant

This template uses the **light variant** wherever a local, often short-lived project needs no more. The decisions below are settled. Each one has its reason and the signal for switching, so that a justified question does not have to be discussed again, and the knowledge behind it is not lost. When a project grows, the sections after the table describe the **extended variant**, topic by topic.

##### Decisions

| # | Topic | Decision (light variant) | Reason | Switch when … |
|---|---|---|---|---|
| D1 | Change workflow | Commits go directly to `main` | A single developer on a short-lived project gains nothing from pull requests | others review or contribute ("Pull-request workflow") |
| D2 | CI | No GitHub Actions; pre-commit checks every commit, and `/verify` runs the tests | The same checks already run locally | the repository is shared or made public, or several people commit ("CI") |
| D3 | Containers for the project's own code | Code runs on the host with `uv run`; Docker only runs Supabase | Containers add a Dockerfile, Compose and networks | a service must run isolated, needs another runtime, or several services work together ("Containers") |
| D4 | Claude Code extras | `CLAUDE.md`, `.claude/settings.json` with the ruff hook, `/verify` and `/deps` | The CLIs cover the rest; the Supabase CLI runs SQL, the linter and the advisors itself | the project uses pull requests, containers or many sessions ("Claude Code extras") |
| D5 | Branch protection | Not used | For private repositories, it needs a paid GitHub plan (GitHub Pro for personal accounts, GitHub Team for organizations); without pull requests (D1), it has nothing to protect | the repository is public or the plan allows it, and pull requests are used ("Pull-request workflow") |
| D6 | Update bots (Dependabot, Renovate) | Not used; updates on demand with `/deps` | A bot opens pull requests every week; they do not fit direct commits (D1) and cost time in a project that may soon be dropped | the project becomes long-lived or public ("Update bot") |
| D7 | Type checking (`mypy`, `pyright`) | Not used | ruff finds style problems and many bugs; type checking pays off for larger, longer-lived code | the code base grows or becomes a library |
| D8 | `.editorconfig` | Not used | `ruff format` and the VS Code settings already define the formatting | other editors join the project |
| D9 | `.nvmrc` | Not used | Node comes from mise (§3.3); a project that needs Node requests it in its `mise.toml` | — (`node = "lts"` in `mise.toml` instead) |
| D10 | Secret scan | Kept: gitleaks before every commit; the full history before a repository is shared or made public | A secret that ever reaches GitHub counts as leaked, also in a private repository that becomes public later | — (always) |
| D11 | Supabase on localhost | Kept: a prepared Docker network keeps Supabase on `127.0.0.1` (§5.1.5) | The Supabase CLI binds to all interfaces; the database has a default password, and Studio has no login | — (always; it costs one command) |
| D12 | Ollama binding | All interfaces (`0.0.0.0`); the firewall allows only the LAN and the Docker networks (§3.1.2, §3.2.1) | Containers and other devices in the LAN use the local models; the API has no authentication, so the firewall limits who reaches it | the LAN is not trusted: allow only the Docker networks |

The parts of the extended variant are added one by one. When several apply, follow the order of the sections below: CI comes first, because the pull-request workflow and publishing rely on its checks.

##### CI

Add the folder `.github/workflows/` with one workflow. GitHub Actions then runs on every push to `main` and on every PR against `main`; newer runs on the same branch cancel older ones (`concurrency`).

**`.github/workflows/ci.yml`**: two jobs on `ubuntu-latest`. The job `test` gets uv from `astral-sh/setup-uv` (with cache), Python from `.python-version`, ruff and pytest from the dev group, and runs the same mise tasks as `/verify`; `jdx/mise-action` installs mise and the CLIs from `mise.toml`. Integration tests do not run in CI, because no stack runs there. The job `secrets` scans the full git history with gitleaks: `jdx/mise-action` installs it from `mise.toml` (and `mise.lock`, if present), so CI uses the same version as the host and the pre-commit hook. If you add the optional branch protection, both job names are its required checks. `permissions` gives the workflow token read access only. Set the actions to their latest major version.

```yaml
name: CI
on:
  push: { branches: [ main ] }
  pull_request: { branches: [ main ] }
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v<latest-major>
      - uses: astral-sh/setup-uv@v<latest-major>
        with: { enable-cache: true }
      - uses: jdx/mise-action@v<latest-major>  # mise for the tasks, and the CLIs from mise.toml
      - run: uv sync --locked
      - run: mise run check
      - run: mise run test
  secrets:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v<latest-major>
        with: { fetch-depth: 0 }            # full history for the secret scan
      - uses: jdx/mise-action@v<latest-major>  # installs gitleaks from mise.toml
      - name: Scan the full history for secrets
        run: gitleaks git --redact --verbose .
```

##### Pull-request workflow

- **Branching**: No direct commits to `main`. Every change goes through a feature branch `<type>/<short-name>` (`feat/…`, `fix/…`, `docs/…`, `chore/…`) created from `main`.
- **Pull requests**: One PR per branch, created with `gh pr create`. The PR title uses the Conventional Commits format, because it becomes the commit message on a squash merge. The body describes motivation, change and verification (template below). Merge only when CI is green (`gh pr checks --watch`); if the branch is behind `main`, update it first (`gh pr update-branch`). Then run `gh pr merge --squash --delete-branch` and update the local `main` with a fast-forward.
- **Commits**: On a squash merge, GitHub adds the PR number (`(#<nr>)`). The reason for an accepted gitleaks false positive is stated in the PR.

In `CLAUDE.md`, replace the bullet about direct commits with: "Every change goes through a PR with a Conventional Commits title. Open PRs yourself with `gh pr create`; never hand over a compare link. Ask before every push." In `.claude/settings.json`, add `Bash(gh pr view *)`, `Bash(gh pr list *)`, `Bash(gh pr checks *)`, `Bash(gh run list *)` and `Bash(gh run view *)` to `allow`, and `Bash(gh pr create *)` and `Bash(gh pr merge *)` to `ask`.

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
gh repo edit "<OWNER>/<REPO>" \
  --default-branch main \
  --enable-squash-merge \
  --enable-merge-commit=false \
  --enable-rebase-merge=false \
  --delete-branch-on-merge \
  --enable-wiki=false
```

**Branch protection (optional):** GitHub can enforce the PR workflow for `main` with branch protection or a ruleset: only pull requests, only with the green checks `test` and `secrets`, no force pushes. For private repositories, this needs a paid GitHub plan (GitHub Pro for personal accounts, GitHub Team for organizations); for public repositories, it is free. Because this template creates private repositories, branch protection is optional. Without it, the PR workflow is a convention that `CLAUDE.md` and the `/ship` skill follow.

###### Skill `/ship` (template, `.claude/skills/ship/SKILL.md`)

```markdown
---
name: ship
description: Commit, open a PR, wait for CI, merge and clean up
disable-model-invocation: true
---
1. If on `main`, create a branch `<type>/<short-name>` first.
2. Stage and commit all changes with a Conventional Commits message.
3. `git push -u origin HEAD`.
4. If no PR exists for this branch (`gh pr view` fails), run `gh pr create --base main`
   with a Conventional-Commit title and a body following `.github/pull_request_template.md`.
5. `gh pr checks --watch`. If a check fails, show `gh run view <id> --log-failed` and stop.
6. If the branch is behind `main`, run `gh pr update-branch` and go back to step 5.
7. `gh pr merge --squash --delete-branch`, then `git switch main && git pull --ff-only`.
```

##### Containers

For services that run in containers. Add `Dockerfile`, `docker-compose.yml` and `.dockerignore` to the project root, and the bind-mount data folders of the containers to `.gitignore`. On Linux, containers need `extra_hosts: ["host.docker.internal:host-gateway"]` to reach services on the host.

**`docker-compose.yml`**: common patterns:

```yaml
services:
  <service>:
    build: .
    ports: ["127.0.0.1:<port>:<port>"]       # bind to localhost on the host only
    env_file: .env
    environment:                             # container values, they take priority over .env
      POSTGRES_HOST: supabase_db_<PROJECT_NAME>        # database container in the Supabase network (§5.1.5)
      POSTGRES_PORT: "5432"
      OLLAMA_BASE_URL: http://host.docker.internal:11434
    extra_hosts: ["host.docker.internal:host-gateway"]   # reach Ollama on the host (Linux)
    networks: [default, supabase]            # only if the service needs the database
    healthcheck: { test: ["CMD", "<check-command>"], interval: 10s, retries: 10 }
    restart: unless-stopped
    logging: { driver: json-file, options: { max-size: "10m", max-file: "3" } }
    volumes: ["<service>_data:/data"]       # only if the service stores data
networks:
  supabase:
    external: true
    name: supabase_network_<PROJECT_NAME>    # created once, used by supabase start (§5.1.5)
volumes:
  <service>_data:
```

When you create the project, set third-party images to the latest (LTS) version and pin them exactly (`<image>:<version>`), so that builds stay reproducible. Raise the tags when you update the environment. Several services from the same package use the same image with a different `command:`.

**Docker Compose** (`docker compose up -d`): the project's own services in the default network that Compose creates for the project. They address each other by service name (`http://<service>:<port>`), not by `127.0.0.1`. Persistent data lives in named volumes (`<service>_data`) or in bind mounts that git ignores. Configuration files are mounted read-only (`:ro`).

Containers of the project reach the database through the Supabase network: they join `supabase_network_<PROJECT_NAME>` and connect to `supabase_db_<PROJECT_NAME>:5432` (see `docker-compose.yml` above). `host.docker.internal:54322` does not work, because the port is published on `127.0.0.1` only.

**`Dockerfile`** (official uv pattern):

```dockerfile
FROM python:<X.Y>-slim
COPY --from=ghcr.io/astral-sh/uv:<current-uv-version> /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
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

`<X.Y>` is the version from `.python-version`. The base image provides Python, and uv uses it. `UV_PYTHON_DOWNLOADS=never` makes the build fail instead of downloading a second Python when the base image does not match `.python-version`.

**`.dockerignore`**: `.git`, `.venv`, `.env`, `.env.*`, `!.env.example`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/` and container data folders.

**Ollama for containers:** containers reach Ollama at `http://host.docker.internal:11434`. Ollama already listens on all interfaces, and the firewall allows the Docker networks (§3.1.2, §3.2.1); processes on the host still use `http://127.0.0.1:11434`. The firewall does not protect ports that Docker publishes, because Docker bypasses ufw; that is why all container ports are published on `127.0.0.1` only. If a container cannot reach Ollama, check the subnet of its network (`docker network inspect <network>`): Docker takes networks from `172.16.0.0/12` and then from `192.168.0.0/16`, and the firewall allows both.

Commands and permissions: `docker compose up -d --build` starts the services; `docker compose ps` and `docker compose logs <service>` check them. Add `docker compose up -d --build` to the commands in `CLAUDE.md`, `Bash(docker compose ps *)` and `Bash(docker compose logs *)` to `allow`, and `Bash(docker compose down *)` to `ask` in `.claude/settings.json`.

##### Claude Code extras

For projects with pull requests, containers or many sessions:

- the skills `/ship` (see "Pull-request workflow"), `/sync` (requires a clean working tree: `git fetch --prune`, then `git merge --ff-only`, otherwise stop) and `/health` (`mise run integration` + `docker compose ps` + `supabase status`);
- the subagent `stack-checker` (template below); the user-level skill `/update-tools` belongs to the host (§4);
- the MCP server of the local Supabase instance as a fallback for the CLI (template below).

###### Subagent (template, `.claude/agents/stack-checker.md`)

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

###### MCP server `supabase-local` (template, `.mcp.json`)

As a fallback for `psql`/`supabase`, add the MCP server of the local Supabase instance (`.mcp.json`, versioned). It offers structured tools (for example `list_tables`) that the CLIs do not provide in this form; SQL, linting and the advisors are available in the CLI (`supabase db query`, `supabase db lint`, `supabase db advisors`). `supabase start` provides it and reports it as `MCP_URL`:

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

##### Sharing or publishing a repository

Before a repository is shared with others or made public, add CI with the job `secrets` (see "CI"): it scans the full history.

**Secret scanning by GitHub:** for a public repository (and for a private one with GitHub Secret Protection), also switch on GitHub's secret scanning and push protection. Push protection rejects a push that contains a known type of secret:

```bash
gh api -X PATCH "repos/<OWNER>/<REPO>" \
  -f 'security_and_analysis[secret_scanning][status]=enabled' \
  -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'
```

**Making a repository public:** first check that the `secrets` job is green on `main`, because it scans the full history. Then change the visibility (`gh repo edit <OWNER>/<REPO> --visibility public --accept-visibility-change-consequences`) and switch on GitHub's secret scanning as above. For a public repository, branch protection is free and can be added as well. A secret that ever reached the history counts as leaked: revoke it where it was issued and replace it; removing it from the history afterwards is not enough.

##### Update bot

When a project becomes long-lived or public, switch on Dependabot first: it is built into GitHub, free for private repositories, and covers GitHub Actions, `uv.lock`, pre-commit hooks and Docker images. A starting point for `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: weekly }
    groups: { actions: { patterns: ["*"] } }
    commit-message: { prefix: chore, include: scope }
  - package-ecosystem: uv
    directory: /
    schedule: { interval: weekly }
    groups: { python: { patterns: ["*"], update-types: [minor, patch] } }
    commit-message: { prefix: chore, include: scope }
  - package-ecosystem: pre-commit
    directory: /
    schedule: { interval: weekly }
    commit-message: { prefix: chore, include: scope }
  - package-ecosystem: docker
    directory: /
    schedule: { interval: weekly }
    commit-message: { prefix: chore, include: scope }
```

Dependabot does not update `mise.toml` or `mise.lock`. CLIs requested as `latest` follow `mise upgrade` on the host; with a `mise.lock`, run `mise lock` afterwards and commit it. Renovate is the alternative when you want automatic merges, a dashboard of open updates or updates of `.python-version`; it runs as a third-party GitHub app or self-hosted.

##### Places to adapt in the extended variant

| What | File(s) |
|---|---|
| Project name `<PROJECT_NAME>` | `docker-compose.yml` (Supabase network and database container) |
| Package name `<package>` | `Dockerfile` (`CMD`), `docker-compose.yml` (`command:`) |
| Ports | `docker-compose.yml` (`ports:`) |
| Volume names | `docker-compose.yml` (`volumes:`) |
| Bind-mount paths | `docker-compose.yml`, `.gitignore`, `.dockerignore` |
| Python version `<X.Y>` | Dockerfile base image |
| uv version | `Dockerfile` (`ghcr.io/astral-sh/uv:<version>`) |
| Image tags, action versions | `docker-compose.yml`, `Dockerfile`, `.github/workflows/ci.yml` |
| gitleaks version | `mise.toml` (or `mise.lock`); the pre-commit hook and CI use the same version |
| GitHub owner/repository `<OWNER>/<REPO>` | `gh repo edit`, `gh api` (secret scanning) |
| Default branch | CI trigger (`branches: [ main ]`), `gh repo edit --default-branch`, `gh pr create --base` |
| CI workflow name | `name:` in `.github/workflows/ci.yml` (shown as the check name in the PR) |

### 5.2 Node

A Node spike uses **TypeScript**, which Node runs directly without a build step, and the same services as a Python spike:

- **Node (LTS) and pnpm** from mise; the dependencies are in `package.json` and `pnpm-lock.yaml`.
- **TypeScript**, checked with `tsc` (`pnpm typecheck`). Node itself only strips the types and runs the code; it checks nothing.
- **Biome** for linting and formatting, **Vitest** for tests, **zod** to check the settings, **pg** as database driver.
- **Supabase, Ollama, GitHub, gitleaks, mise and 1Password** as in §5.1.

#### 5.2.1 Starting a spike with Claude Code

As in §5.1.1, with this prompt in step 3:

```text
Set up this project according to docs/ENVIRONMENT.md as a Node spike. Work
through the bootstrap checklist in §5.2.9 from step 2 up to and including
step 10. Placeholders: <PROJECT_NAME>=my-spike. Write CLAUDE.md as described
in §5.2.8 and reference docs/ENVIRONMENT.md in it.
Ask before you push anything or create a GitHub repository.
```

#### 5.2.2 Project structure

```text
<PROJECT_ROOT>/
├── .claude/                # Claude Code configuration (settings, skills)
├── .vscode/                # recommended extensions and workspace settings for VS Code (versioned)
├── docs/                   # project documentation, including this file (ENVIRONMENT.md)
├── src/
│   ├── config.ts           # settings from the environment and .env, checked with zod
│   └── main.ts             # entry point (pnpm start)
├── test/
│   ├── unit/               # unit tests (pnpm test)
│   └── integration/        # tests that need the running stack (pnpm run test:integration)
├── scripts/                # thin entry scripts for one-off tasks, they import from src/
├── supabase/               # Supabase CLI configuration (config.toml) and SQL migrations
├── CLAUDE.md               # project instructions for Claude Code
├── .pre-commit-config.yaml # git hooks (Biome, gitleaks secret scan, large-file check)
├── mise.toml               # Node, pnpm and the other CLIs of the project, the loading of .env
├── package.json            # dependencies and scripts
├── pnpm-lock.yaml          # pnpm lock file (versioned)
├── tsconfig.json           # TypeScript settings for tsc and the editor
├── biome.json              # Biome settings
├── .gitignore
├── .env.example            # template for .env (versioned)
├── .env                    # local values (not versioned)
└── secrets.env             # 1Password references for op run, no secrets (versioned, §5.1.6)
```

The code is made of ES modules (`"type": "module"`). Imports of own files name the file with its `.ts` extension (`./config.ts`). Other modules start with `node src/<module>.ts`.

#### 5.2.3 Configuration files

Runtimes and tools of the project:

| Component | Version channel | Where it is set |
|---|---|---|
| Node | LTS | `mise.toml` (`node = "lts"`); `mise.lock` records the exact version if you use it |
| pnpm | latest | `mise.toml`. `pnpm init` also pins pnpm in `package.json` (`packageManager`, `devEngines`); the checklist removes these entries, so that pnpm comes only from mise |
| Dependencies (`pg`, `zod`) and dev tools (TypeScript, Biome, Vitest, the `@types` packages) | latest when the project is created, pinned in `pnpm-lock.yaml`, raised by `/deps` with `pnpm update --latest` | `package.json`, through `pnpm add` |
| `@types/node` | major version of the Node LTS | `/deps` keeps the major version; when mise moves to a new Node LTS, raise it with `pnpm add -D "@types/node@<node-lts-major>"` |
| PostgreSQL | as in §5.1.3 | `supabase/config.toml` |
| Supabase CLI, gitleaks | latest | `mise.toml` (below) |

**`package.json`**: written by `pnpm init` and adapted by the checklist (§5.2.9); `pnpm add` adds the dependencies with `^` ranges. The relevant part:

```json
{
  "name": "<PROJECT_NAME>",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "start": "node src/main.ts",
    "test": "vitest run test/unit",
    "test:integration": "vitest run test/integration",
    "typecheck": "tsc",
    "check": "biome check .",
    "fix": "biome check --write ."
  }
}
```

**`tsconfig.json`**: the settings that Node's type stripping needs, plus `strict`. `erasableSyntaxOnly` forbids TypeScript syntax that Node cannot strip, such as `enum`; `rewriteRelativeImportExtensions` allows imports with `.ts`. `tsc` only checks (`noEmit`).

```json
{
  "compilerOptions": {
    "noEmit": true,
    "target": "esnext",
    "module": "nodenext",
    "rewriteRelativeImportExtensions": true,
    "erasableSyntaxOnly": true,
    "verbatimModuleSyntax": true,
    "strict": true,
    "skipLibCheck": true,
    "types": ["node"]
  },
  "include": ["src", "test", "scripts"]
}
```

**`biome.json`**: created by `pnpm exec biome init`; the checklist sets spaces and a line width of 100, as for ruff in §5.1.3. Biome uses `.gitignore` and skips `node_modules`.

**`mise.toml`**: as in §5.1.3, with Node and pnpm, without the uv setting, and with tasks for pnpm:

```toml
[tools]
node = "lts"
pnpm = "latest"
supabase = "latest"
gitleaks = "latest"                  # the secret scan in the pre-commit hook and in CI (§5.2.10)

[env]
_.file = { path = ".env", redact = true }   # loads .env if it exists; keeps the values out of mise's output

[tasks.check]
description = "Biome and TypeScript"
run = "pnpm check && pnpm typecheck"

[tasks.test]
description = "Unit tests"
run = "pnpm test"

[tasks.integration]
description = "Integration tests; they need the running stack"
run = "pnpm run test:integration"

[tasks.start]
description = "The entry point src/main.ts"
run = "pnpm start"
```

**`src/config.ts`**: all settings in one place. zod checks the types and stops at startup when a required value is missing. `getSettings()` reads `.env` itself, so the program and the tests work without mise as well; variables that already exist in the environment win, so `op run` works (§5.2.6). Tests call `loadSettings()` with their own variables. The settings hold the password: never log them.

```ts
import { z } from "zod";

const schema = z.object({
  POSTGRES_HOST: z.string().default("127.0.0.1"),
  POSTGRES_PORT: z.coerce.number().int().default(54322),
  POSTGRES_USER: z.string().default("postgres"),
  POSTGRES_PASSWORD: z.string().min(1), // required: no default
  POSTGRES_DB: z.string().default("postgres"),
  OLLAMA_BASE_URL: z.string().default("http://127.0.0.1:11434"),
  OLLAMA_MODEL: z.string().default("gemma4:latest"),
});

export type Settings = z.infer<typeof schema> & { databaseUrl: string };

/** Checks the variables and builds the database URL; tests pass their own variables. */
export function loadSettings(env: Record<string, string | undefined>): Settings {
  const s = schema.parse(env);
  const user = encodeURIComponent(s.POSTGRES_USER);
  const password = encodeURIComponent(s.POSTGRES_PASSWORD);
  const database = encodeURIComponent(s.POSTGRES_DB);
  const databaseUrl = `postgresql://${user}:${password}@${s.POSTGRES_HOST}:${s.POSTGRES_PORT}/${database}`;
  return { ...s, databaseUrl };
}

let cached: Settings | undefined;

/** All settings, from the environment and `.env`; real environment variables take priority. */
export function getSettings(): Settings {
  if (!cached) {
    try {
      process.loadEnvFile(".env");
    } catch {
      // no .env: the environment alone
    }
    cached = loadSettings(process.env);
  }
  return cached;
}
```

**`src/main.ts`**:

```ts
import { getSettings } from "./config.ts";

const settings = getSettings();
console.log(`Hello from <PROJECT_NAME> (database ${settings.POSTGRES_HOST}:${settings.POSTGRES_PORT})`);
```

**`.env.example`**: as in §5.1.3.

**`test/`**: unit tests for the settings and integration tests for the database connection and for Ollama. `pnpm test` runs `test/unit`; `pnpm run test:integration` runs `test/integration` and needs the running stack.

```ts
// test/unit/config.test.ts
import { expect, test } from "vitest";
import { loadSettings } from "../../src/config.ts";

test("database URL", () => {
  const settings = loadSettings({ POSTGRES_PASSWORD: "secret" });
  expect(settings.databaseUrl.endsWith("@127.0.0.1:54322/postgres")).toBe(true);
});

test("password with special characters", () => {
  const url = new URL(loadSettings({ POSTGRES_PASSWORD: "p@ss:w/rd#1" }).databaseUrl);
  expect([url.hostname, url.port]).toEqual(["127.0.0.1", "54322"]);
  expect(decodeURIComponent(url.password)).toBe("p@ss:w/rd#1");
});

test("missing password fails", () => {
  expect(() => loadSettings({})).toThrow();
});
```

```ts
// test/integration/database.test.ts
import pg from "pg";
import { expect, test } from "vitest";
import { getSettings } from "../../src/config.ts";

test("database connection", async () => {
  const client = new pg.Client({ connectionString: getSettings().databaseUrl });
  await client.connect();
  try {
    const result = await client.query("select 1 as one");
    expect(result.rows[0].one).toBe(1);
  } finally {
    await client.end();
  }
});
```

```ts
// test/integration/llm.test.ts
import { expect, test } from "vitest";
import { getSettings } from "../../src/config.ts";

test("model is available", async () => {
  const settings = getSettings();
  const response = await fetch(`${settings.OLLAMA_BASE_URL}/api/tags`);
  expect(response.status).toBe(200);
  const body = (await response.json()) as { models: { name: string }[] };
  expect(body.models.map((model) => model.name)).toContain(settings.OLLAMA_MODEL);
});
```

**`supabase/config.toml`**: as in §5.1.3.

**`.pre-commit-config.yaml`**: Biome and gitleaks as local hooks, and the check for large files. The Biome hook runs the version from `pnpm-lock.yaml`, the gitleaks hook the version from `mise.toml`. pre-commit itself comes from mise (§3.3); `pre-commit install` activates the hooks.

```yaml
repos:
  - repo: local                    # Biome from package.json, gitleaks from mise
    hooks:
      - id: biome-check
        name: biome check
        entry: pnpm exec biome check --write --no-errors-on-unmatched --files-ignore-unknown=true
        language: unsupported
        types_or: [javascript, jsx, ts, tsx, json]
        require_serial: true
      - id: gitleaks
        name: gitleaks
        entry: gitleaks git --pre-commit --redact --staged --verbose
        language: unsupported
        pass_filenames: false
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v<latest-pre-commit-hooks-version>
    hooks:
      - id: check-added-large-files
```

**`.vscode/extensions.json`** and **`.vscode/settings.json`**: Biome as formatter for TypeScript, JavaScript and JSON, also JSON with comments such as `tsconfig.json` (it does not format Markdown or YAML), Vitest in the test view.

```json
{
  "recommendations": [
    "anthropic.claude-code",
    "biomejs.biome",
    "vitest.explorer"
  ]
}
```

```json
{
  "[typescript]": { "editor.defaultFormatter": "biomejs.biome", "editor.formatOnSave": true },
  "[javascript]": { "editor.defaultFormatter": "biomejs.biome", "editor.formatOnSave": true },
  "[json]": { "editor.defaultFormatter": "biomejs.biome", "editor.formatOnSave": true },
  "[jsonc]": { "editor.defaultFormatter": "biomejs.biome", "editor.formatOnSave": true }
}
```

**`.gitignore`** (relevant patterns): `node_modules/`, `.env`, `.env.*`, `!.env.example`, `coverage/`, `dist/`, `mise.local.toml`, `.supabase/`, `supabase/.temp/` and `supabase/seed.sql` (if generated).

#### 5.2.4 Environment variables and ports

As in §5.1.4. Each new variable gets a field in the zod schema of `src/config.ts`.

#### 5.2.5 Local services

As in §5.1.5.

#### 5.2.6 Secrets with 1Password

As in §5.1.6.

#### 5.2.7 Conventions

As in §5.1.7, with these differences:

- **Code style**: Biome for linting and formatting (spaces, line width 100); `pnpm fix` applies the safe fixes. TypeScript in strict mode; `pnpm typecheck` checks the types.
- **Project layout**: all code in `src/` as ES modules; imports of own files with `.ts`. The entry point is `src/main.ts` (`pnpm start`); other modules start with `node src/<module>.ts`.
- **Configuration**: only through `getSettings()` from `src/config.ts`. No `process.env` in the rest of the code. Never log the settings, they hold the password.
- **Testing**: unit tests in `test/unit` (`pnpm test`), tests that need the stack in `test/integration` (`pnpm run test:integration`).
- **Dependencies**: only through `pnpm add` / `pnpm remove`; never edit `pnpm-lock.yaml` by hand. Updates are made on demand with `/deps`.

#### 5.2.8 Claude Code setup

As in §5.1.8, with these parts for Node:

`CLAUDE.md`: the template from §5.1.8, with §5.2 instead of §5.1 in its first lines and under "Further reading", and with these sections:

````markdown
## Tooling
- Prefer CLIs over MCP servers: use `gh`, `supabase`, `psql`, `docker`, `pnpm`, `ctx7` directly.
  Use an MCP server only when no CLI covers the task.
- All CLIs are installed globally on the host and kept at the latest (LTS) version.
- Run project tools through pnpm: `pnpm check`, `pnpm typecheck`, `pnpm test`.
- Common commands are mise tasks: `mise run check`, `mise run test`, `mise run integration`, `mise run start`.
- Run all commands from the project root.
- Never bypass git hooks (`--no-verify`). A secret found by gitleaks is removed, not skipped.
- Commit directly to `main` with Conventional Commits; ask before every push.

## Commands
```bash
mise trust && mise install       # Node, pnpm and the other CLIs, the loading of .env
pnpm install --frozen-lockfile   # dependencies from pnpm-lock.yaml
cp .env.example .env && chmod 600 .env   # then fill in the required values
supabase stop --all              # stops the stacks of other spikes, which use the same ports
supabase start                   # local database
mise run start                   # entry point src/main.ts
op run --env-file secrets.env -- mise run start   # the same, with the secrets from 1Password
mise run check                   # Biome and TypeScript
mise run test                    # unit tests
mise run integration             # database and Ollama; needs the running stack
```

## Configuration
All settings come from `getSettings()` in src/config.ts (zod). Never use process.env elsewhere.
Real secrets are 1Password references (op://) in secrets.env; commands that need them run with `op run --env-file secrets.env -- …`.
````

`.claude/settings.json`: the hook runs Biome after every edit.

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": [
      "Bash(pnpm install *)",
      "Bash(mise run check *)",
      "Bash(mise run test *)",
      "Bash(mise run integration *)",
      "Bash(mise run start *)",
      "Bash(pnpm start *)",
      "Bash(pnpm test *)",
      "Bash(pnpm run test:integration *)",
      "Bash(pnpm typecheck *)",
      "Bash(pnpm check *)",
      "Bash(pnpm fix *)",
      "Bash(ctx7 library *)",
      "Bash(ctx7 docs *)",
      "Bash(ctx7 search *)",
      "Bash(docker port *)",
      "Bash(supabase start)",
      "Bash(supabase status *)",
      "Bash(supabase db lint *)",
      "Bash(supabase db advisors *)",
      "Bash(git status *)",
      "Bash(git diff *)",
      "Bash(git log *)",
      "Bash(git fetch *)"
    ],
    "ask": [
      "Bash(git push *)",
      "Bash(pnpm add *)",
      "Bash(pnpm remove *)",
      "Bash(pnpm update *)",
      "Bash(psql *)",
      "Bash(supabase db query *)",
      "Bash(supabase db reset *)",
      "Bash(supabase stop *)",
      "Bash(op run *)"
    ],
    "deny": [
      "Read(.env)"
    ]
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "cd \"$CLAUDE_PROJECT_DIR\" && pnpm exec biome check --write . 1>&2 || exit 2"
          }
        ]
      }
    ]
  }
}
```

Skill `/verify`: as in §5.1.8; its mise tasks run Biome, TypeScript and Vitest here.

Skill `/deps` (`.claude/skills/deps/SKILL.md`):

```markdown
---
name: deps
description: Update the project dependencies and hook versions, then verify
disable-model-invocation: true
---
Run, in order, and report what changed (git diff --stat):
1. pnpm update --latest '!@types/node', then pnpm update @types/node
   (@types/node stays at the major version of the Node LTS)
2. pre-commit autoupdate, then pre-commit run --all-files
   (runs the new hook versions once; the Biome hook may fix files)
3. Run /verify (.claude/skills/verify/SKILL.md)
```

#### 5.2.9 Bootstrap checklist for a new spike

The steps that Claude follows in a new Node project (§5.2.1), or that you run yourself. The command blocks use the shell variable `name` for `<PROJECT_NAME>`.

1. Once per host (skip if already done): set up the host as described in §3 and §4. `check-dev-tools.sh` must report no missing tool (`[MISSING]`); a pending update or a new Ubuntu release does not block a new spike.
2. Create the project with pnpm, its dependencies and the folders. `pnpm init` writes `package.json`; `jq` removes the entries that pin pnpm and sets the scripts (§5.2.3). `biome init` writes `biome.json`, and `jq` sets spaces and the line width:
   ```bash
   name=my-spike                        # <PROJECT_NAME>: lower case, words joined with -
   mkdir -p ~/Documents/workspaces/git/"$name" && cd ~/Documents/workspaces/git/"$name"
   git init -b main
   pnpm init
   jq '.version = "0.1.0" | .private = true | .type = "module"
       | del(.packageManager, .devEngines, .main, .description, .keywords, .author, .license)
       | .scripts = {"start": "node src/main.ts", "test": "vitest run test/unit",
                     "test:integration": "vitest run test/integration", "typecheck": "tsc",
                     "check": "biome check .", "fix": "biome check --write ."}' package.json > package.json.tmp \
     && mv package.json.tmp package.json
   pnpm add pg zod
   pnpm add -D typescript "@types/node@$(node -p 'process.versions.node.split(".")[0]')" @types/pg @biomejs/biome vitest
   pnpm exec biome init
   jq '.formatter.indentStyle = "space" | .formatter.lineWidth = 100' biome.json > biome.json.tmp \
     && mv biome.json.tmp biome.json
   mkdir -p src test/unit test/integration scripts docs .claude .vscode
   ```
   `@types/node` gets the major version of the Node LTS, so that the types match the running Node. Then create `tsconfig.json`, `.vscode/extensions.json` and `.vscode/settings.json` (§5.2.3).
3. Create `mise.toml` (§5.2.3), then trust it and install its CLIs:
   ```bash
   mise trust && mise install
   ```
4. Run `supabase init` and create the Supabase network, as in step 4 of §5.1.9:
   ```bash
   supabase init
   docker network create -o com.docker.network.bridge.host_binding_ipv4=127.0.0.1 "supabase_network_$name"
   ```
5. Create `.env.example` (§5.1.3) and `.gitignore` (§5.2.3). If the spike needs secrets, list their references in `secrets.env` (§5.1.6). Then create `.env` from the template:
   ```bash
   cp .env.example .env && chmod 600 .env
   ```
6. Create `src/config.ts`, `src/main.ts` and the tests `test/unit/config.test.ts`, `test/integration/database.test.ts` and `test/integration/llm.test.ts` (§5.2.3).
7. If the project has its own service: create `src/<module>.ts`; it runs with `node src/<module>.ts`. Containers belong to the extended variant (§5.2.10).
8. Create `.pre-commit-config.yaml` with the hooks from §5.2.3, then set the versions of the remote hooks and activate all hooks:
   ```bash
   pre-commit autoupdate
   pre-commit install
   ```
9. Write `CLAUDE.md`, `.claude/settings.json` and the skills `/verify` and `/deps` as described in §5.2.8.
10. Start and check the environment:
    ```bash
    pnpm install --frozen-lockfile
    supabase stop --all                  # the stack of another spike would block the ports (§5.1.5)
    supabase start
    docker port "supabase_db_$name"      # must show 127.0.0.1:54322 only
    mise run check
    mise run test
    mise run integration                 # database and Ollama
    mise run start                       # the entry point src/main.ts
    ```
11. Create the private GitHub repository and push the first commit:
    ```bash
    git add -A && git commit -m "chore: initial project setup"
    gh repo create "$name" --private --source . --push
    ```

Places to adapt: as in §5.1.9, with `package.json` (`name`) instead of `pyproject.toml`, and without the Python version and the skill symlinks.

#### 5.2.10 Decisions and the extended variant

The decisions and the extended variant from §5.1.10 apply, with these differences:

- **D7, type checking:** TypeScript checks the types with `pnpm typecheck`, in `/verify` and in CI.
- **D9, `.nvmrc`:** not used; the project's `mise.toml` requests Node.
- **CI:** the job `test` installs Node, pnpm and gitleaks with `jdx/mise-action` and runs the same mise tasks as in §5.1.10; the job `secrets` stays as in §5.1.10.

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v<latest-major>
      - uses: jdx/mise-action@v<latest-major>  # Node, pnpm and gitleaks from mise.toml
      - run: pnpm install --frozen-lockfile
      - run: mise run check
      - run: mise run test
```

- **Containers:** the Compose patterns from §5.1.10 apply unchanged. The `Dockerfile` installs the runtime dependencies with pnpm and runs the TypeScript code directly:

```dockerfile
FROM node:<node-lts-major>-slim
RUN npm install --global pnpm@<current-pnpm-version>
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --prod
COPY src ./src
USER node
EXPOSE <port>
CMD ["node", "src/main.ts"]
```

- **Update bot:** in `.github/dependabot.yml`, the ecosystem `npm` (it also covers `pnpm-lock.yaml`) replaces `uv`.
- **Places to adapt in the extended variant:** in addition, the Node major version and the pnpm version in the `Dockerfile`.

### 5.3 Java

A Java spike is a Maven project without a framework, with the same services as a Python spike:

- **Java (LTS) and Maven** from mise. Dependency and plugin versions are properties in `pom.xml`, raised with the versions plugin.
- **JUnit** for tests: unit tests (`*Test.java`) run with `mvn test`, integration tests (`*IT.java`) with `mvn verify`.
- **Spotless** with palantir-java-format for formatting, the PostgreSQL JDBC driver for the database.
- **Supabase, Ollama, GitHub, gitleaks, mise and 1Password** as in §5.1.

A framework such as Spring Boot or Quarkus is a decision of the spike: it brings its own configuration and start command instead of `Config.java` and the exec plugin.

#### 5.3.1 Starting a spike with Claude Code

As in §5.1.1, with this prompt in step 3:

```text
Set up this project according to docs/ENVIRONMENT.md as a Java spike. Work
through the bootstrap checklist in §5.3.9 from step 2 up to and including
step 10. Placeholders: <PROJECT_NAME>=my-spike (package: spike.my_spike).
Write CLAUDE.md as described in §5.3.8 and reference docs/ENVIRONMENT.md in it.
Ask before you push anything or create a GitHub repository.
```

#### 5.3.2 Project structure

```text
<PROJECT_ROOT>/
├── .claude/                # Claude Code configuration (settings, skills)
├── .vscode/                # recommended extensions for VS Code (versioned)
├── docs/                   # project documentation, including this file (ENVIRONMENT.md)
├── src/
│   ├── main/java/spike/<package>/
│   │   ├── Config.java     # settings from the environment and .env
│   │   └── Main.java       # entry point (mvn -q compile exec:java)
│   └── test/java/spike/<package>/
│       ├── ConfigTest.java # unit test (mvn test)
│       ├── DatabaseIT.java # integration test, needs the running stack (mvn verify)
│       └── OllamaIT.java   # integration test for Ollama (mvn verify)
├── supabase/               # Supabase CLI configuration (config.toml) and SQL migrations
├── CLAUDE.md               # project instructions for Claude Code
├── .pre-commit-config.yaml # git hooks (Spotless, gitleaks secret scan, large-file check)
├── mise.toml               # Java, Maven and the other CLIs of the project, the loading of .env
├── pom.xml                 # dependencies, plugins and their versions
├── .gitignore
├── .env.example            # template for .env (versioned)
├── .env                    # local values (not versioned)
└── secrets.env             # 1Password references for op run, no secrets (versioned, §5.1.6)
```

The Maven group is `spike`, the Java package `spike.<package>` (`<package>` as in the placeholders, for example `my_spike`). Maven builds into `target/`.

#### 5.3.3 Configuration files

Runtimes and tools of the project:

| Component | Version channel | Where it is set |
|---|---|---|
| Java | LTS (Eclipse Temurin) | `mise.toml` (`java = "lts"`); `maven.compiler.release` in `pom.xml` is the major version of this JDK |
| Maven | latest | `mise.toml`; no Maven wrapper (`mvnw`) |
| Dependencies and plugins | latest when the project is created, as properties in `pom.xml`, raised by `/deps` with `mvn versions:update-properties`, without pre-releases (§5.3.8) | `pom.xml` |
| PostgreSQL | as in §5.1.3 | `supabase/config.toml` |
| Supabase CLI, gitleaks | latest | `mise.toml` (below) |

**`mise.toml`**: as in §5.1.3, with Java and Maven, without the uv setting, and with tasks for Maven. `Config.java` reads `.env` itself, as in Python and Node, so the program and the tests also work when they start from the IDE.

```toml
[tools]
java = "lts"                         # Eclipse Temurin (mise's default vendor)
maven = "latest"
supabase = "latest"
gitleaks = "latest"                  # the secret scan in the pre-commit hook and in CI (§5.3.10)

[env]
_.file = { path = ".env", redact = true }   # loads .env if it exists; keeps the values out of mise's output

[tasks.check]
description = "Format check"
run = "mvn -q spotless:check"

[tasks.test]
description = "Unit tests"
run = "mvn -q test"

[tasks.integration]
description = "Unit and integration tests; they need the running stack"
run = "mvn -q verify"

[tasks.start]
description = "The entry point Main"
run = "mvn -q compile exec:java"
```

**`pom.xml`**: the checklist writes it with the newest versions from Maven Central. `latest` reads them from the metadata of the repository and skips alpha, beta, milestone and RC versions; `maven.compiler.release` comes from the JDK of mise. The block uses `name` and `package` from step 2 of §5.3.9. Surefire runs `*Test.java` in `mvn test`, Failsafe runs `*IT.java` in `mvn verify`, the exec plugin starts `Main`, and Spotless formats the code.

```bash
latest() {   # newest release of a Maven artifact, without alpha, beta, milestone and RC versions
  curl -fsSL "https://repo1.maven.org/maven2/${1//.//}/$2/maven-metadata.xml" \
    | grep -oP '(?<=<version>)[^<]+' | grep -viE 'alpha|beta|rc|-m[0-9]|snapshot|milestone' | sort -V | tail -1
}
java_release="$(java -XshowSettings:properties -version 2>&1 | awk -F' = ' '/java.specification.version/ {print $2}')"
cat > pom.xml << EOF
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>spike</groupId>
  <artifactId>$name</artifactId>
  <version>0.1.0</version>

  <properties>
    <maven.compiler.release>$java_release</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    <exec.mainClass>spike.$package.Main</exec.mainClass>
    <junit.version>$(latest org.junit junit-bom)</junit.version>
    <postgresql.version>$(latest org.postgresql postgresql)</postgresql.version>
    <compiler-plugin.version>$(latest org.apache.maven.plugins maven-compiler-plugin)</compiler-plugin.version>
    <surefire.version>$(latest org.apache.maven.plugins maven-surefire-plugin)</surefire.version>
    <exec-plugin.version>$(latest org.codehaus.mojo exec-maven-plugin)</exec-plugin.version>
    <spotless.version>$(latest com.diffplug.spotless spotless-maven-plugin)</spotless.version>
  </properties>

  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.junit</groupId>
        <artifactId>junit-bom</artifactId>
        <version>\${junit.version}</version>
        <type>pom</type>
        <scope>import</scope>
      </dependency>
    </dependencies>
  </dependencyManagement>

  <dependencies>
    <dependency>
      <groupId>org.postgresql</groupId>
      <artifactId>postgresql</artifactId>
      <version>\${postgresql.version}</version>
    </dependency>
    <dependency>
      <groupId>org.junit.jupiter</groupId>
      <artifactId>junit-jupiter</artifactId>
      <scope>test</scope>
    </dependency>
  </dependencies>

  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <version>\${compiler-plugin.version}</version>
      </plugin>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-surefire-plugin</artifactId>
        <version>\${surefire.version}</version>
      </plugin>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-failsafe-plugin</artifactId>
        <version>\${surefire.version}</version>
        <executions>
          <execution>
            <goals>
              <goal>integration-test</goal>
              <goal>verify</goal>
            </goals>
          </execution>
        </executions>
      </plugin>
      <plugin>
        <groupId>org.codehaus.mojo</groupId>
        <artifactId>exec-maven-plugin</artifactId>
        <version>\${exec-plugin.version}</version>
      </plugin>
      <plugin>
        <groupId>com.diffplug.spotless</groupId>
        <artifactId>spotless-maven-plugin</artifactId>
        <version>\${spotless.version}</version>
        <configuration>
          <java>
            <palantirJavaFormat/>
            <removeUnusedImports/>
          </java>
        </configuration>
      </plugin>
    </plugins>
  </build>
</project>
EOF
```

Spotless prints warnings about `sun.misc.Unsafe` on current JDKs; they are harmless.

**`Config.java`**: all settings in one place. Like pydantic-settings, `fromEnv()` reads `.env` (simple `KEY=VALUE` lines without quotes); real environment variables win, so `op run` works (§5.1.6). A missing password stops the program at startup. The JDBC URL holds no credentials; user and password go to the driver separately, so special characters need no encoding. `toString()` hides the password.

```java
package spike.<package>;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

/** All configuration, read from environment variables and `.env`. */
public record Config(
        String host,
        int port,
        String user,
        String password,
        String database,
        String ollamaBaseUrl,
        String ollamaModel) {

    /** Variables from `.env` (if it exists) and the environment; real environment variables win. */
    public static Config fromEnv() {
        Map<String, String> env = new HashMap<>(dotEnv(Path.of(".env")));
        env.putAll(System.getenv());
        return from(env);
    }

    static Config from(Map<String, String> env) {
        String password = env.get("POSTGRES_PASSWORD");
        if (password == null || password.isEmpty()) {
            throw new IllegalStateException("POSTGRES_PASSWORD is not set");
        }
        return new Config(
                env.getOrDefault("POSTGRES_HOST", "127.0.0.1"),
                Integer.parseInt(env.getOrDefault("POSTGRES_PORT", "54322")),
                env.getOrDefault("POSTGRES_USER", "postgres"),
                password,
                env.getOrDefault("POSTGRES_DB", "postgres"),
                env.getOrDefault("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
                env.getOrDefault("OLLAMA_MODEL", "gemma4:latest"));
    }

    /** Simple KEY=VALUE lines without quotes; empty lines and comments are skipped, a missing file gives no values. */
    static Map<String, String> dotEnv(Path file) {
        Map<String, String> values = new HashMap<>();
        if (!Files.exists(file)) {
            return values;
        }
        try {
            for (String line : Files.readAllLines(file)) {
                String trimmed = line.strip();
                int equals = trimmed.indexOf('=');
                if (trimmed.startsWith("#") || equals < 1) {
                    continue;
                }
                values.put(
                        trimmed.substring(0, equals).strip(),
                        trimmed.substring(equals + 1).strip());
            }
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
        return values;
    }

    /** JDBC URL without credentials: user and password go to the driver separately. */
    public String jdbcUrl() {
        return "jdbc:postgresql://" + host + ":" + port + "/" + database;
    }

    @Override
    public String toString() {
        return "Config[host=" + host + ", port=" + port + ", user=" + user + ", password=****, database=" + database
                + ", ollamaBaseUrl=" + ollamaBaseUrl + ", ollamaModel=" + ollamaModel + "]";
    }
}
```

**`Main.java`**:

```java
package spike.<package>;

public class Main {
    public static void main(String[] args) {
        System.out.println("Hello from <PROJECT_NAME> (" + Config.fromEnv() + ")");
    }
}
```

**`.env.example`**: as in §5.1.3.

**Tests**: unit tests for the settings and integration tests for the database connection and for Ollama. `mvn test` runs `ConfigTest`; `mvn verify` also runs `DatabaseIT` and `OllamaIT` and needs the running stack.

```java
// src/test/java/spike/<package>/ConfigTest.java
package spike.<package>;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class ConfigTest {

    @Test
    void jdbcUrl() {
        Config config = Config.from(Map.of("POSTGRES_PASSWORD", "secret"));
        assertEquals("jdbc:postgresql://127.0.0.1:54322/postgres", config.jdbcUrl());
        assertFalse(config.toString().contains("secret"));
    }

    @Test
    void missingPasswordFails() {
        assertThrows(IllegalStateException.class, () -> Config.from(Map.of()));
    }

    @Test
    void dotEnvFile(@TempDir Path dir) throws Exception {
        Path file = dir.resolve(".env");
        Files.writeString(file, "# comment\nPOSTGRES_PASSWORD=from-file\n\nPOSTGRES_PORT = 1111\n");
        assertEquals(Map.of("POSTGRES_PASSWORD", "from-file", "POSTGRES_PORT", "1111"), Config.dotEnv(file));
        assertEquals(Map.of(), Config.dotEnv(dir.resolve("missing")));
    }
}
```

```java
// src/test/java/spike/<package>/DatabaseIT.java
package spike.<package>;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.sql.DriverManager;
import org.junit.jupiter.api.Test;

class DatabaseIT {

    @Test
    void databaseConnection() throws Exception {
        Config config = Config.fromEnv();
        try (var connection = DriverManager.getConnection(config.jdbcUrl(), config.user(), config.password());
                var result = connection.createStatement().executeQuery("select 1")) {
            result.next();
            assertEquals(1, result.getInt(1));
        }
    }
}
```

```java
// src/test/java/spike/<package>/OllamaIT.java
package spike.<package>;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import org.junit.jupiter.api.Test;

class OllamaIT {

    @Test
    void modelIsAvailable() throws Exception {
        Config config = Config.fromEnv();
        HttpRequest request = HttpRequest.newBuilder(URI.create(config.ollamaBaseUrl() + "/api/tags"))
                .build();
        HttpResponse<String> response = HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString());
        assertEquals(200, response.statusCode());
        assertTrue(response.body().contains("\"" + config.ollamaModel() + "\""), "model not pulled");
    }
}
```

**`supabase/config.toml`**: as in §5.1.3.

**`.pre-commit-config.yaml`**: Spotless and gitleaks as local hooks, and the check for large files. pre-commit itself comes from mise (§3.3); `pre-commit install` activates the hooks.

```yaml
repos:
  - repo: local                    # Spotless from pom.xml, gitleaks from mise
    hooks:
      - id: spotless
        name: spotless apply
        entry: mvn -q spotless:apply
        language: unsupported
        types: [java]
        pass_filenames: false
      - id: gitleaks
        name: gitleaks
        entry: gitleaks git --pre-commit --redact --staged --verbose
        language: unsupported
        pass_filenames: false
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v<latest-pre-commit-hooks-version>
    hooks:
      - id: check-added-large-files
```

**`.vscode/extensions.json`**: the Java extensions for VS Code. IntelliJ IDEA from the JetBrains Toolbox (§3.2.1) opens `pom.xml` directly. For `JAVA_HOME` in the IDE, see §7.

```json
{
  "recommendations": [
    "anthropic.claude-code",
    "vscjava.vscode-java-pack"
  ]
}
```

**`.gitignore`** (relevant patterns): `target/`, `.env`, `.env.*`, `!.env.example`, `mise.local.toml`, `.supabase/`, `supabase/.temp/` and `supabase/seed.sql` (if generated).

#### 5.3.4 Environment variables and ports

As in §5.1.4. `Config.java` reads each new variable.

#### 5.3.5 Local services

As in §5.1.5.

#### 5.3.6 Secrets with 1Password

As in §5.1.6.

#### 5.3.7 Conventions

As in §5.1.7, with these differences:

- **Code style**: Spotless with palantir-java-format; `mvn -q spotless:apply` formats, `mvn -q spotless:check` checks.
- **Project layout**: the Maven standard layout, all code in the package `spike.<package>`. The entry point is `Main` (`mvn -q compile exec:java`); another class with `main()` starts with `-Dexec.mainClass=spike.<package>.<Class>`.
- **Configuration**: only through `Config.fromEnv()`, which also reads `.env`. No `System.getenv` in the rest of the code; `toString()` hides the password.
- **Testing**: unit tests are `*Test.java` (`mvn test`), tests that need the stack are `*IT.java` (`mvn verify`).
- **Dependencies**: versions only as properties in `pom.xml`. Updates are made on demand with `/deps`, which raises them with `mvn versions:update-properties` and skips pre-releases.

#### 5.3.8 Claude Code setup

As in §5.1.8, with these parts for Java:

`CLAUDE.md`: the template from §5.1.8, with §5.3 instead of §5.1 in its first lines and under "Further reading", and with these sections:

````markdown
## Tooling
- Prefer CLIs over MCP servers: use `gh`, `supabase`, `psql`, `docker`, `mvn`, `ctx7` directly.
  Use an MCP server only when no CLI covers the task.
- All CLIs are installed globally on the host and kept at the latest (LTS) version.
- Run project tools through Maven: `mvn -q spotless:apply`, `mvn -q test`, `mvn -q verify`.
- Common commands are mise tasks: `mise run check`, `mise run test`, `mise run integration`, `mise run start`.
- Run all commands from the project root.
- Never bypass git hooks (`--no-verify`). A secret found by gitleaks is removed, not skipped.
- Commit directly to `main` with Conventional Commits; ask before every push.

## Commands
```bash
mise trust && mise install       # Java, Maven and the other CLIs, the loading of .env
cp .env.example .env && chmod 600 .env   # then fill in the required values
supabase stop --all              # stops the stacks of other spikes, which use the same ports
supabase start                   # local database
mise run start                   # entry point Main
op run --env-file secrets.env -- mise run start   # the same, with the secrets from 1Password
mvn -q spotless:apply            # format the code
mise run check                   # Spotless check
mise run test                    # unit tests
mise run integration             # unit and integration tests; needs the running stack
```

## Configuration
All settings come from `Config.fromEnv()` in src/main/java/spike/<package>/Config.java. Never use System.getenv elsewhere.
Real secrets are 1Password references (op://) in secrets.env; commands that need them run with `op run --env-file secrets.env -- …`.
````

`.claude/settings.json`: the hook formats the code after every edit. Each run starts Maven and takes a few seconds; remove the hook if that slows you down, the pre-commit hook formats before every commit anyway.

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": [
      "Bash(mvn -q compile *)",
      "Bash(mise run check *)",
      "Bash(mise run test *)",
      "Bash(mise run integration *)",
      "Bash(mise run start *)",
      "Bash(mvn -q test *)",
      "Bash(mvn -q verify *)",
      "Bash(mvn -q spotless:apply *)",
      "Bash(mvn -q spotless:check *)",
      "Bash(ctx7 library *)",
      "Bash(ctx7 docs *)",
      "Bash(ctx7 search *)",
      "Bash(docker port *)",
      "Bash(supabase start)",
      "Bash(supabase status *)",
      "Bash(supabase db lint *)",
      "Bash(supabase db advisors *)",
      "Bash(git status *)",
      "Bash(git diff *)",
      "Bash(git log *)",
      "Bash(git fetch *)"
    ],
    "ask": [
      "Bash(git push *)",
      "Bash(mvn -q versions:update-properties *)",
      "Bash(psql *)",
      "Bash(supabase db query *)",
      "Bash(supabase db reset *)",
      "Bash(supabase stop *)",
      "Bash(op run *)"
    ],
    "deny": [
      "Read(.env)"
    ]
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "cd \"$CLAUDE_PROJECT_DIR\" && mvn -q spotless:apply 1>&2 || exit 2"
          }
        ]
      }
    ]
  }
}
```

Skill `/verify`: as in §5.1.8; its mise tasks run Spotless, the unit tests and `mvn verify` here.

Skill `/deps` (`.claude/skills/deps/SKILL.md`):

```markdown
---
name: deps
description: Update the project dependencies, plugins and hook versions, then verify
disable-model-invocation: true
---
Run, in order, and report what changed (git diff --stat):
1. mvn -q versions:update-properties -DgenerateBackupPoms=false '-Dmaven.version.ignore=(?i).*[-.](alpha|beta|m|rc|cr|ea|preview)[-.]?[0-9]*'
   (raises the version properties in pom.xml, without alpha, beta, milestone and RC versions)
2. pre-commit autoupdate, then pre-commit run --all-files
   (runs the new hook versions once; the Spotless hook may fix files)
3. Run /verify (.claude/skills/verify/SKILL.md)
```

#### 5.3.9 Bootstrap checklist for a new spike

The steps that Claude follows in a new Java project (§5.3.1), or that you run yourself. The command blocks use the shell variables `name` for `<PROJECT_NAME>` and `package` for `<package>`.

1. Once per host (skip if already done): set up the host as described in §3 and §4. `check-dev-tools.sh` must report no missing tool (`[MISSING]`); a pending update or a new Ubuntu release does not block a new spike.
2. Create the folders and the git repository:
   ```bash
   name=my-spike                        # <PROJECT_NAME>: lower case, words joined with -
   package="${name//-/_}"               # <package>: the Java package is spike.<package>
   mkdir -p ~/Documents/workspaces/git/"$name" && cd ~/Documents/workspaces/git/"$name"
   git init -b main
   mkdir -p "src/main/java/spike/$package" "src/test/java/spike/$package" docs .claude .vscode
   ```
3. Create `mise.toml` (§5.3.3), then trust it and install Java, Maven and the other CLIs:
   ```bash
   mise trust && mise install
   ```
4. Run `supabase init` and create the Supabase network, as in step 4 of §5.1.9:
   ```bash
   supabase init
   docker network create -o com.docker.network.bridge.host_binding_ipv4=127.0.0.1 "supabase_network_$name"
   ```
5. Create `.env.example` (§5.1.3) and `.gitignore` (§5.3.3). If the spike needs secrets, list their references in `secrets.env` (§5.1.6). Then create `.env` from the template:
   ```bash
   cp .env.example .env && chmod 600 .env
   ```
6. Write `pom.xml` with the block from §5.3.3. Create `Config.java`, `Main.java`, `ConfigTest.java`, `DatabaseIT.java` and `OllamaIT.java` (§5.3.3).
7. If the project has its own service: create a class with `main()`; it runs with `mvn -q compile exec:java -Dexec.mainClass=spike.<package>.<Class>`. Containers belong to the extended variant (§5.3.10).
8. Create `.pre-commit-config.yaml` with the hooks from §5.3.3, then set the versions of the remote hooks and activate all hooks:
   ```bash
   pre-commit autoupdate
   pre-commit install
   ```
9. Write `CLAUDE.md`, `.claude/settings.json` and the skills `/verify` and `/deps` as described in §5.3.8.
10. Start and check the environment:
    ```bash
    supabase stop --all                  # the stack of another spike would block the ports (§5.1.5)
    supabase start
    docker port "supabase_db_$name"      # must show 127.0.0.1:54322 only
    mvn -q spotless:apply
    mise run check
    mise run test
    mise run integration                 # unit tests and integration tests (database and Ollama)
    mise run start                       # the entry point Main
    ```
11. Create the private GitHub repository and push the first commit:
    ```bash
    git add -A && git commit -m "chore: initial project setup"
    gh repo create "$name" --private --source . --push
    ```

Places to adapt: as in §5.1.9, with `pom.xml` (`artifactId`, `exec.mainClass`) and the Java package `spike.<package>` instead of `pyproject.toml` and `src/<package>/`, and without the Python version and the skill symlinks.

#### 5.3.10 Decisions and the extended variant

The decisions and the extended variant from §5.1.10 apply, with these differences:

- **D7, type checking:** the Java compiler checks the types.
- **D9, `.nvmrc`:** does not apply.
- **CI:** the job `test` installs Java, Maven and gitleaks with `jdx/mise-action` and runs the same mise tasks as in §5.1.10; the job `secrets` stays as in §5.1.10.

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v<latest-major>
      - uses: jdx/mise-action@v<latest-major>  # Java, Maven and gitleaks from mise.toml
      - run: mise run check
      - run: mise run test
```

- **Containers:** the Compose patterns from §5.1.10 apply unchanged. The `Dockerfile` builds with Maven and runs on a JRE:

```dockerfile
FROM maven:<current-maven-version>-eclipse-temurin-<java-lts-major> AS build
WORKDIR /app
COPY pom.xml .
RUN mvn -B -q dependency:go-offline
COPY src ./src
RUN mvn -B -q package -DskipTests dependency:copy-dependencies -DincludeScope=runtime -DoutputDirectory=target/lib

FROM eclipse-temurin:<java-lts-major>-jre
WORKDIR /app
COPY --from=build /app/target/<PROJECT_NAME>-0.1.0.jar app.jar
COPY --from=build /app/target/lib lib
RUN useradd --create-home --uid 1000 appuser
USER appuser
EXPOSE <port>
CMD ["java", "-cp", "app.jar:lib/*", "spike.<package>.Main"]
```

- **Update bot:** in `.github/dependabot.yml`, the ecosystem `maven` replaces `uv`; it raises the version properties in `pom.xml`.
- **Places to adapt in the extended variant:** in addition, the Maven and Java versions of the images in the `Dockerfile`.

### 5.4 New spike from a template

The checklists in §5.1.9, §5.2.9 and §5.3.9 take eleven steps. A template repository per language shortens this to one command. Create the templates once, keep them up to date, and create every new spike from them.

**Create the templates, once per language, one after the other:** follow §5.1.1 (or §5.2.1, §5.3.1) with `name=spike-template`: copy this file into `docs/`, then work through the checklist of the language, steps 2 to 10. Every template is built in the folder `spike-template`, because `supabase init` takes the folder name as `project_id`, and `new-spike` replaces exactly the name `spike-template`. Then publish the template as a private template repository:

```bash
lang=python                          # python, node or java
cd ~/Documents/workspaces/git/spike-template
grep -Fx 'project_id = "spike-template"' supabase/config.toml   # must print the line
git add -A
git commit -m "chore: spike template"
gh repo create "spike-template-$lang" --private --source . --push && gh repo edit --template
```

When `gh repo view "spike-template-$lang"` shows the repository, free the Supabase stack and the folder for the next language:

```bash
cd ~/Documents/workspaces/git/spike-template
supabase stop --no-backup
docker network rm supabase_network_spike-template
cd .. && rm -rf spike-template
```

**The script `~/.local/bin/new-spike`** first checks the language and the name, and stops if the folder or the repository exists already. Then it creates the repository from the template and replaces the template names `spike-template` and `spike_template` with the name of the spike, also in the package folders; `docs/ENVIRONMENT.md` stays unchanged. It sets `project_id` to the name of the spike, so that it matches the Supabase network. Finally it creates the network, installs the tools and pushes the first commit.

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/new-spike << "EOF"
#!/usr/bin/env bash
# Creates a spike from the template repository of its language (§5.4).
# Usage: new-spike <python|node|java> <name>
set -euo pipefail
usage="usage: new-spike <python|node|java> <name>"
lang="${1:?$usage}"
name="${2:?$usage}"
[[ "$lang" =~ ^(python|node|java)$ ]] || { echo "$usage" >&2; exit 1; }
[[ "$name" =~ ^[a-z][a-z0-9]*(-[a-z0-9]+)*$ ]] \
  || { echo "name: lower case letters and digits, words joined with -, starting with a letter" >&2; exit 1; }
package="${name//-/_}"
owner="$(gh api user -q .login)"
workspace=~/Documents/workspaces/git

# Stop before anything is created
if [[ -e "$workspace/$name" ]]; then echo "$workspace/$name exists already" >&2; exit 1; fi
if gh repo view "$owner/$name" > /dev/null 2>&1; then echo "repository $owner/$name exists already" >&2; exit 1; fi

mkdir -p "$workspace" && cd "$workspace"
gh repo create "$owner/$name" --private --template "$owner/spike-template-$lang"
until gh api "repos/$owner/$name/commits?per_page=1" > /dev/null 2>&1; do sleep 2; done   # GitHub copies the template in the background
gh repo clone "$owner/$name"
cd "$name"

# Replace the template names with the names of the spike; docs/ENVIRONMENT.md stays unchanged
{ grep -rlZ --exclude-dir=.git --exclude=ENVIRONMENT.md -e spike-template -e spike_template . || true; } \
  | xargs -0 -r sed -i -e "s/spike-template/$name/g" -e "s/spike_template/$package/g"
for dir in src/spike_template src/main/java/spike/spike_template src/test/java/spike/spike_template; do
  if [[ -d "$dir" ]]; then git mv "$dir" "${dir%spike_template}$package"; fi
done
# The Supabase network below must match project_id, even if the template has another one
sed -i "s/^project_id = .*/project_id = \"$name\"/" supabase/config.toml

mise trust && mise install
docker network create -o com.docker.network.bridge.host_binding_ipv4=127.0.0.1 "supabase_network_$name" > /dev/null
cp .env.example .env && chmod 600 .env
case "$lang" in
  python) uv sync && uv run pre-commit install ;;
  node) pnpm install --frozen-lockfile && pre-commit install ;;
  java) pre-commit install ;;
esac
git add -A
git commit -m "chore: rename the template to $name"
git push
echo "Spike $name is ready in $workspace/$name. Next: supabase stop --all, supabase start, mise run check"
EOF
chmod +x ~/.local/bin/new-spike
shellcheck ~/.local/bin/new-spike    # no findings
```

A new spike then takes one command. Afterwards, let Claude Code describe the project in `CLAUDE.md` (project overview, architecture):

```bash
new-spike python my-spike            # or: new-spike node my-spike, new-spike java my-spike
cd ~/Documents/workspaces/git/my-spike
supabase stop --all                  # the stacks of other spikes use the same ports (§5.1.5)
supabase start
mise run check
```

**Keep the templates up to date:** when this file changes, and about once a month. Clone each template into the folder `spike-template` and prepare it like a new spike:

```bash
lang=python                          # python, node or java
cd ~/Documents/workspaces/git
gh repo clone "spike-template-$lang" spike-template && cd spike-template
cp "<PATH>/ENVIRONMENT.md" docs/     # the current master copy
mise trust && mise install
docker network create -o com.docker.network.bridge.host_binding_ipv4=127.0.0.1 supabase_network_spike-template
cp .env.example .env && chmod 600 .env
case "$lang" in
  python) uv sync && uv run pre-commit install ;;
  node) pnpm install --frozen-lockfile && pre-commit install ;;
  java) pre-commit install ;;
esac
```

Then start Claude Code in the folder. Let it apply the changes of this file to the template and run `/deps`; start the stack (`supabase stop --all`, then `supabase start`) and run `/verify`. Commit and push, then free the stack and the folder as above. New spikes start with the current versions; existing spikes keep theirs.

### 5.5 Ending a spike

A spike ends when its question is answered. If the project lives on, switch to the extended variant instead (§5.1.10). Otherwise archive the repository and free the local resources; the code stays readable on GitHub.

First check that nothing is lost. Both commands must print nothing; otherwise commit and push, or discard the changes. An archived repository accepts no more pushes.

```bash
name=my-spike
cd ~/Documents/workspaces/git/"$name"
git status --short                           # changes that are not committed
git fetch && git log --oneline '@{u}..'      # commits that are not pushed
```

Then end the spike:

```bash
name=my-spike
cd ~/Documents/workspaces/git/"$name"
docker compose down --volumes --rmi local 2> /dev/null || true   # only with containers (§5.1.10)
supabase stop --no-backup                    # stop the stack and delete its local data
docker network rm "supabase_network_$name"
gh repo archive --yes                        # read-only on GitHub
cd .. && rm -rf "$name"                      # optional: delete the local copy
```

Delete the 1Password items that only this spike used. To work on an archived spike again, run `gh repo unarchive` and clone it.

---

## 6. Claude Code and non-interactive shells

`mise activate bash` works through a prompt hook, so only interactive terminals run it. There, all mise tools, `[env]` (`.env`) and `python.uv_venv_auto` work as described in §5.1.3. Everywhere else:

- **Programs started from the desktop**, such as VS Code and Claude Code inside it, get their `PATH` from `~/.profile` at login. It contains the shims directory (`~/.local/share/mise/shims`, §3.3.1), so they find every mise tool by name, and Node CLIs such as `ctx7` always find the right Node. A change to `~/.profile` takes effect at the next login; `exec bash -l` updates only the current terminal.
- **Claude Code's Bash tool and its hooks** start from the environment of the `claude` process (an activated terminal or the desktop session) and run without a prompt, so the shims apply.
- **`[env]` without activation:** mise applies `[env]` only when a command runs through a shim, `mise exec` or `mise run`. `uv` and the Python in `.venv` are no mise tools, so `uv run` does not get `.env` from mise. Let the program read `.env` itself (for example with pydantic-settings), or call `mise exec -- uv run …`.
- **Cron jobs and systemd units** read neither `~/.bashrc` nor `~/.profile`. Set the `PATH` there, or call `mise exec -- <command>`:

```bash
export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:$PATH"
```

---

## 7. Pitfalls

- **Updating mise itself:** mise from APT is updated by APT. `mise self-update` is not meant for this install. `mise upgrade` updates the tools, not mise.
- **Duplicate tools:** a tool installed a second time outside mise (for example Maven from APT) can hide the mise version in `PATH`. `type -a <tool>` shows every copy.
- **`JAVA_HOME`:** the mise JDK sets `JAVA_HOME` only in activated shells. Programs started from the desktop find `java` through the shim, but without `JAVA_HOME`. If a program needs it (for example a Java extension in VS Code), set it in the program's settings to the output of `mise where java`.
- **GitHub rate limit:** mise gets its GitHub token from `gh` (`credential_command`, §3.3.1). If `gh` is not logged in, many requests in a row (`mise outdated`, first `mise install`) can hit the anonymous rate limit. `mise token github` shows which token mise uses.
- **Release age:** `mise install` and `mise upgrade` skip releases younger than 24 hours (mise's default for `minimum_release_age`). A brand-new release therefore arrives one day later. That is intended.
- **ufw and Docker:** ufw does not filter ports that Docker publishes. Publish container ports on `127.0.0.1` (`127.0.0.1:<port>:<port>`) unless the LAN must reach them.
- **Commit signing and Claude Code:** every commit is signed through 1Password (§3.1.3). When Claude Code commits, 1Password may ask for approval in its own window, and the commit waits until you approve it. Claude Code does not see this window, so a commit that seems to hang is usually waiting for it. How long an approval lasts is set in 1Password under *Settings > Developer*.
- **Trust:** mise ignores `[env]` and other settings of a `mise.toml` that you have not trusted. After cloning a repository, read its `mise.toml`, then run `mise trust`.

---

## Change log

The version of this document follows semantic versioning:

| Part | Raised when |
|---|---|
| MAJOR | an existing host or project must change, for example because a tool moves to another manager, a required tool is added or a convention changes |
| MINOR | something is added that an existing host or project can adopt later, for example an optional tool or template |
| PATCH | wording, commands or links are corrected without changing what a host or project must do |

- Every released change raises the version and adds a row to the table below. A change is released when it reaches the main branch or is copied into a project; until then, changes belong to the next version.
- The contents list at the start is updated whenever a heading changes.
- The copy of this file in a project shows the version that the project follows (§5.1.1).

| Version | Date | Changes |
|---|---|---|
| 1.0.0 | 2026-11-14 | First versioned release, with contents list and change log |
