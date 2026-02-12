#!/usr/bin/env bash
# ============================================================================
# CNV HealthCrew AI - Uninstaller
# Cleanly removes all installed components
#
# Usage:
#   bash scripts/uninstall.sh
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

INSTALL_DIR="$HOME/cnv-healthcrew"
CONFIG_DIR="$HOME/.config/cnv-healthcrew"
DATA_DIR="$HOME/.local/share/cnv-healthcrew"
SERVICE_FILE="$HOME/.config/systemd/user/cnv-healthcrew.service"

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }

echo ""
echo -e "${BOLD}============================================================${NC}"
echo -e "${BOLD}  CNV HealthCrew AI - Uninstaller${NC}"
echo -e "${BOLD}============================================================${NC}"
echo ""

# Confirm
echo -e "${YELLOW}This will remove:${NC}"
echo "  - Application:  $INSTALL_DIR"
echo "  - Config:        $CONFIG_DIR"
echo "  - Data/Reports:  $DATA_DIR"
echo "  - systemd service"
echo ""
read -rp "Are you sure? [y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi
echo ""

# 1. Stop and disable systemd service
if systemctl --user is-active cnv-healthcrew &>/dev/null; then
    info "Stopping service..."
    systemctl --user stop cnv-healthcrew
    success "Service stopped"
fi

if systemctl --user is-enabled cnv-healthcrew &>/dev/null; then
    info "Disabling service..."
    systemctl --user disable cnv-healthcrew
    success "Service disabled"
fi

if [ -f "$SERVICE_FILE" ]; then
    info "Removing systemd unit file..."
    rm -f "$SERVICE_FILE"
    systemctl --user daemon-reload
    success "systemd unit removed"
fi

# 2. Remove application directory
if [ -d "$INSTALL_DIR" ]; then
    info "Removing application ($INSTALL_DIR)..."
    rm -rf "$INSTALL_DIR"
    success "Application removed"
else
    warn "Application directory not found (already removed?)"
fi

# 3. Remove config (ask first)
if [ -d "$CONFIG_DIR" ]; then
    read -rp "Remove config ($CONFIG_DIR)? [y/N] " rm_config
    if [[ "$rm_config" =~ ^[Yy]$ ]]; then
        rm -rf "$CONFIG_DIR"
        success "Config removed"
    else
        warn "Config preserved at $CONFIG_DIR"
    fi
fi

# 4. Remove data/reports (ask first)
if [ -d "$DATA_DIR" ]; then
    read -rp "Remove reports and data ($DATA_DIR)? [y/N] " rm_data
    if [[ "$rm_data" =~ ^[Yy]$ ]]; then
        rm -rf "$DATA_DIR"
        success "Data removed"
    else
        warn "Data preserved at $DATA_DIR"
    fi
fi

echo ""
echo -e "${GREEN}${BOLD}  Uninstall complete.${NC}"
echo ""
