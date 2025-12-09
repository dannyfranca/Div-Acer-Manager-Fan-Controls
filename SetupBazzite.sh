#!/bin/bash

set -e

INSTALL_DIR="/var/opt/dam-fan-controls"
SERVICE_NAME="dam-fan-control"

echo "=============================================="
echo "  DAM Fan Controls - Bazzite OS Setup"
echo "=============================================="
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script must be run as root (use sudo)"
    exit 1
fi

if ! command -v rpm-ostree &> /dev/null; then
    echo "ERROR: This script is for Bazzite/Fedora Atomic systems only."
    echo "For traditional distributions, use SetupDrivers.sh"
    exit 1
fi

check_kernel_headers() {
    if [ -d "/lib/modules/$(uname -r)/build" ]; then
        return 0
    else
        return 1
    fi
}

check_secure_boot() {
    if command -v mokutil &> /dev/null; then
        if mokutil --sb-state 2>/dev/null | grep -q "SecureBoot enabled"; then
            return 0
        fi
    fi
    return 1
}

install_kernel_headers() {
    echo "Kernel headers not found. Installing..."
    echo "This will stage the installation and require a reboot."
    echo ""
    
    rpm-ostree install kernel-devel kernel-headers
    
    echo ""
    echo "=============================================="
    echo "  REBOOT REQUIRED"
    echo "=============================================="
    echo ""
    echo "Kernel headers have been staged for installation."
    echo "Please reboot your system and run this script again:"
    echo ""
    echo "  sudo systemctl reboot"
    echo ""
    echo "After reboot:"
    echo "  sudo ./SetupBazzite.sh"
    echo ""
    exit 0
}

compile_driver() {
    echo "Compiling kernel driver..."
    
    cd "$INSTALL_DIR/NitroDrivers"
    
    if ! make; then
        echo ""
        echo "ERROR: Driver compilation failed."
        echo ""
        echo "Common causes:"
        echo "  1. Kernel headers not properly installed"
        echo "  2. Missing build tools (gcc, make)"
        echo ""
        echo "Try installing build tools:"
        echo "  sudo rpm-ostree install gcc make"
        echo "  sudo systemctl reboot"
        echo ""
        exit 1
    fi
    
    echo "Driver compiled successfully."
}

install_service() {
    echo "Installing systemd service..."
    
    cp "$INSTALL_DIR/dam-fan-control.service" /etc/systemd/system/
    
    sed -i "s|/opt/dam-fan-controls|$INSTALL_DIR|g" /etc/systemd/system/dam-fan-control.service
    
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
}

echo "Step 1: Checking kernel headers..."
if ! check_kernel_headers; then
    install_kernel_headers
fi
echo "  ✓ Kernel headers found"
echo ""

echo "Step 2: Checking Secure Boot status..."
if check_secure_boot; then
    echo ""
    echo "=============================================="
    echo "  WARNING: Secure Boot is ENABLED"
    echo "=============================================="
    echo ""
    echo "Custom kernel modules cannot be loaded with Secure Boot enabled."
    echo "You have two options:"
    echo ""
    echo "  Option A: Disable Secure Boot in BIOS (recommended for personal use)"
    echo "  Option B: Sign the kernel module with a Machine Owner Key (advanced)"
    echo ""
    echo "To disable Secure Boot:"
    echo "  1. Reboot and enter BIOS/UEFI settings"
    echo "  2. Find Secure Boot option (usually under Security or Boot)"
    echo "  3. Disable Secure Boot"
    echo "  4. Save and exit"
    echo "  5. Run this script again"
    echo ""
    read -p "Continue anyway? The driver will fail to load. (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "  ✓ Secure Boot is disabled or not detected"
fi
echo ""

echo "Step 3: Creating installation directory..."
mkdir -p "$INSTALL_DIR"
echo "  ✓ Created $INSTALL_DIR"
echo ""

echo "Step 4: Copying daemon files..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -d "$SCRIPT_DIR/DAM-FC/Daemon" ]; then
    cp -r "$SCRIPT_DIR/DAM-FC/Daemon/"* "$INSTALL_DIR/"
elif [ -d "$SCRIPT_DIR/Daemon" ]; then
    cp -r "$SCRIPT_DIR/Daemon/"* "$INSTALL_DIR/"
else
    echo "ERROR: Cannot find Daemon directory"
    echo "Expected at: $SCRIPT_DIR/DAM-FC/Daemon or $SCRIPT_DIR/Daemon"
    exit 1
fi

if [ -f "$INSTALL_DIR/dist/DAMFC_daemon" ]; then
    cp "$INSTALL_DIR/dist/DAMFC_daemon" "$INSTALL_DIR/DAMFC_daemon"
    chmod +x "$INSTALL_DIR/DAMFC_daemon"
fi

echo "  ✓ Files copied"
echo ""

echo "Step 5: Compiling kernel driver..."
compile_driver
echo ""

echo "Step 6: Installing systemd service..."
install_service
echo "  ✓ Service installed and enabled"
echo ""

echo "Step 7: Starting the daemon..."
if systemctl start "$SERVICE_NAME"; then
    echo "  ✓ Daemon started"
else
    echo ""
    echo "WARNING: Daemon failed to start."
    echo "This might be due to Secure Boot or driver issues."
    echo ""
    echo "Check the logs with:"
    echo "  journalctl -u $SERVICE_NAME -f"
    echo ""
fi

echo ""
echo "=============================================="
echo "  Installation Complete!"
echo "=============================================="
echo ""
echo "Useful commands:"
echo ""
echo "  Check daemon status:"
echo "    sudo systemctl status $SERVICE_NAME"
echo ""
echo "  View daemon logs:"
echo "    journalctl -u $SERVICE_NAME -f"
echo ""
echo "  Restart daemon:"
echo "    sudo systemctl restart $SERVICE_NAME"
echo ""
echo "  Stop daemon:"
echo "    sudo systemctl stop $SERVICE_NAME"
echo ""
echo "Installation directory: $INSTALL_DIR"
echo "Log files: /var/log/Div_Acer_Manager_Logs/"
echo ""

