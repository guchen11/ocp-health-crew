#!/usr/bin/env bash
# ============================================================================
# CNV HealthCrew AI - Installer
# One-command install for RHEL/Fedora desktops
#
# Usage:
#   curl -sL https://raw.githubusercontent.com/guchen11/ocp-health-crew/main/install.sh | bash
#   # or
#   bash install.sh
# ============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Paths
INSTALL_DIR="$HOME/cnv-healthcrew"
CONFIG_DIR="$HOME/.config/cnv-healthcrew"
DATA_DIR="$HOME/.local/share/cnv-healthcrew"
SYSTEMD_DIR="$HOME/.config/systemd/user"
REPO_URL="https://github.com/guchen11/ocp-health-crew.git"

# -------------------------------------------------------
# Helper functions
# -------------------------------------------------------
info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()    { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

header() {
    echo ""
    echo -e "${BOLD}============================================================${NC}"
    echo -e "${BOLD}  CNV HealthCrew AI - Installer${NC}"
    echo -e "${BOLD}============================================================${NC}"
    echo ""
}

# -------------------------------------------------------
# 1. Pre-flight checks
# -------------------------------------------------------
preflight() {
    info "Running pre-flight checks..."

    # Check OS
    if [ -f /etc/redhat-release ]; then
        OS_NAME=$(cat /etc/redhat-release)
        success "OS: $OS_NAME"
    elif [ -f /etc/fedora-release ]; then
        OS_NAME=$(cat /etc/fedora-release)
        success "OS: $OS_NAME"
    else
        warn "Not RHEL/Fedora -- proceeding anyway (may work on other distros)"
    fi

    # Check Python
    PYTHON_CMD=""
    for cmd in python3.11 python3.12 python3.13 python3.14 python3; do
        if command -v "$cmd" &>/dev/null; then
            PY_VER=$("$cmd" --version 2>&1 | awk '{print $2}')
            PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
            PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
            if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 11 ]; then
                PYTHON_CMD="$cmd"
                break
            fi
        fi
    done

    if [ -z "$PYTHON_CMD" ]; then
        fail "Python 3.11+ is required but not found. Install with: sudo dnf install python3.11"
    fi
    success "Python: $($PYTHON_CMD --version)"

    # Check git
    if ! command -v git &>/dev/null; then
        fail "git is not installed. Install with: sudo dnf install git"
    fi
    success "git: $(git --version)"

    # Check pip/venv modules
    if ! "$PYTHON_CMD" -m pip --version &>/dev/null; then
        warn "pip not found, attempting to install..."
        sudo dnf install -y python3-pip || fail "Could not install python3-pip"
    fi

    if ! "$PYTHON_CMD" -c "import venv" &>/dev/null; then
        warn "venv module not found, attempting to install..."
        sudo dnf install -y python3-virtualenv || fail "Could not install python3-virtualenv"
    fi

    success "pip and venv available"
}

# -------------------------------------------------------
# 2. Clone or update repository
# -------------------------------------------------------
clone_repo() {
    if [ -d "$INSTALL_DIR/.git" ]; then
        info "Existing installation found at $INSTALL_DIR"
        info "Updating from git..."
        cd "$INSTALL_DIR"
        git pull --ff-only || warn "Could not auto-update, continuing with existing code"
        success "Repository updated"
    else
        if [ -d "$INSTALL_DIR" ]; then
            warn "$INSTALL_DIR exists but is not a git repo. Backing up..."
            mv "$INSTALL_DIR" "${INSTALL_DIR}.bak.$(date +%s)"
        fi
        info "Cloning repository..."
        git clone "$REPO_URL" "$INSTALL_DIR"
        success "Repository cloned to $INSTALL_DIR"
    fi
}

# -------------------------------------------------------
# 3. Create Python virtual environment
# -------------------------------------------------------
setup_venv() {
    info "Setting up Python virtual environment..."
    cd "$INSTALL_DIR"

    if [ ! -d "venv" ]; then
        "$PYTHON_CMD" -m venv venv
        success "Virtual environment created"
    else
        success "Virtual environment already exists"
    fi

    # Activate and install
    source venv/bin/activate
    pip install --upgrade pip --quiet
    info "Installing Python dependencies (this may take a minute)..."
    pip install -r requirements.txt --quiet
    deactivate

    success "All Python dependencies installed"
}

# -------------------------------------------------------
# 4. Setup configuration
# -------------------------------------------------------
setup_config() {
    info "Setting up configuration..."

    mkdir -p "$CONFIG_DIR"

    if [ ! -f "$CONFIG_DIR/config.env" ]; then
        if [ -f "$INSTALL_DIR/config.env.example" ]; then
            cp "$INSTALL_DIR/config.env.example" "$CONFIG_DIR/config.env"
        else
            # Create default config
            cat > "$CONFIG_DIR/config.env" <<'ENVEOF'
# CNV HealthCrew AI - Configuration
# Edit this file with your cluster connection details

# Remote lab host (SSH target that has oc/kubectl access)
RH_LAB_HOST=
RH_LAB_USER=root

# Path to your SSH private key (on this machine)
SSH_KEY_PATH=~/.ssh/id_ed25519

# KUBECONFIG path on the remote host
KUBECONFIG_REMOTE=/home/kni/clusterconfigs/auth/kubeconfig

# Email settings (optional)
EMAIL_TO=
EMAIL_FROM=cnv-healthcrew@redhat.com
SMTP_SERVER=smtp.corp.redhat.com
SMTP_PORT=25

# Google Gemini AI key (optional, for AI-powered RCA)
GOOGLE_API_KEY=

# Flask settings
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
ENVEOF
        fi
        warn "Config created at: $CONFIG_DIR/config.env"
        warn ">>> You MUST edit this file with your cluster details! <<<"
    else
        success "Config already exists at $CONFIG_DIR/config.env"
    fi
}

# -------------------------------------------------------
# 5. Setup data directories
# -------------------------------------------------------
setup_data_dirs() {
    info "Setting up data directories..."
    mkdir -p "$DATA_DIR/reports"
    mkdir -p "$DATA_DIR/logs"
    success "Data directory: $DATA_DIR"
}

# -------------------------------------------------------
# 6. Install systemd user service
# -------------------------------------------------------
setup_systemd() {
    info "Setting up systemd user service..."

    mkdir -p "$SYSTEMD_DIR"

    cat > "$SYSTEMD_DIR/cnv-healthcrew.service" <<SVCEOF
[Unit]
Description=CNV HealthCrew AI - OpenShift Health Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$CONFIG_DIR/config.env
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/run.py
Restart=on-failure
RestartSec=5

# Logging
StandardOutput=append:$DATA_DIR/logs/healthcrew.log
StandardError=append:$DATA_DIR/logs/healthcrew.log

[Install]
WantedBy=default.target
SVCEOF

    # Reload systemd to pick up the new service
    systemctl --user daemon-reload
    success "systemd service installed"

    # Enable lingering so user services run without login
    if command -v loginctl &>/dev/null; then
        loginctl enable-linger "$(whoami)" 2>/dev/null || true
    fi
}

# -------------------------------------------------------
# 7. Print summary
# -------------------------------------------------------
print_summary() {
    echo ""
    echo -e "${BOLD}============================================================${NC}"
    echo -e "${GREEN}${BOLD}  Installation Complete!${NC}"
    echo -e "${BOLD}============================================================${NC}"
    echo ""
    echo -e "  ${BOLD}Install dir:${NC}  $INSTALL_DIR"
    echo -e "  ${BOLD}Config file:${NC}  $CONFIG_DIR/config.env"
    echo -e "  ${BOLD}Data dir:${NC}     $DATA_DIR"
    echo -e "  ${BOLD}Logs:${NC}         $DATA_DIR/logs/healthcrew.log"
    echo ""
    echo -e "${YELLOW}${BOLD}  Next steps:${NC}"
    echo ""
    echo -e "  1. Edit your config:"
    echo -e "     ${CYAN}vi $CONFIG_DIR/config.env${NC}"
    echo ""
    echo -e "  2. Start the service:"
    echo -e "     ${CYAN}systemctl --user start cnv-healthcrew${NC}"
    echo ""
    echo -e "  3. Enable auto-start on boot:"
    echo -e "     ${CYAN}systemctl --user enable cnv-healthcrew${NC}"
    echo ""
    echo -e "  4. Open the dashboard:"
    echo -e "     ${CYAN}xdg-open http://localhost:5000${NC}"
    echo ""
    echo -e "  ${BOLD}Useful commands:${NC}"
    echo -e "     Status:  ${CYAN}systemctl --user status cnv-healthcrew${NC}"
    echo -e "     Logs:    ${CYAN}tail -f $DATA_DIR/logs/healthcrew.log${NC}"
    echo -e "     Stop:    ${CYAN}systemctl --user stop cnv-healthcrew${NC}"
    echo -e "     Update:  ${CYAN}cd $INSTALL_DIR && git pull && systemctl --user restart cnv-healthcrew${NC}"
    echo ""
}

# -------------------------------------------------------
# Main
# -------------------------------------------------------
main() {
    header
    preflight
    clone_repo
    setup_venv
    setup_config
    setup_data_dirs
    setup_systemd
    print_summary
}

main "$@"
