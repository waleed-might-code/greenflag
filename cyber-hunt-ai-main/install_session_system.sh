#!/bin/bash
# Session Management System - Installation Script
# Run this to set up the session management system

set -e

echo "=================================================="
echo "Session Management System - Installation"
echo "=================================================="
echo ""

# Check Python version
echo "Checking Python version..."
python3 --version || { echo "Error: Python 3 not found"; exit 1; }

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r cyberAI/requirements.txt

# Install Playwright browsers
echo "Installing Playwright browsers..."
playwright install chromium

# Create directories
echo "Creating directories..."
mkdir -p login_sequences
mkdir -p outputs/session_debug
mkdir -p outputs/authenticated_recon

# Copy environment template
if [ ! -f ".env" ]; then
    echo "Creating .env file from template..."
    cp .env.session.example .env
    echo "⚠️  Please edit .env and add your configuration"
else
    echo "✓ .env file already exists"
fi

# Verify installation
echo ""
echo "Verifying installation..."
python3 -c "
import sys
sys.path.insert(0, 'cyberAI')
from session_manager import SessionStore
from login_macro import LoginSequence
from session_integration import SessionIntegration
print('✅ All modules imported successfully')
"

echo ""
echo "=================================================="
echo "Installation Complete!"
echo "=================================================="
echo ""
echo "Next steps:"
echo "1. Edit .env with your configuration"
echo "2. Create login sequences: python cyberAI/cli_login_macro.py create"
echo "3. Test sequences: python cyberAI/cli_login_macro.py test <sequence>"
echo "4. Run demo: python run_demo.py"
echo "5. See SESSION_MANAGEMENT.md for full documentation"
echo ""
