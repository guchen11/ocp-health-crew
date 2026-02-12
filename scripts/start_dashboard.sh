#!/bin/bash
# Start CNV Health Dashboard and open browser
#
# Usage:
#   ./scripts/start_dashboard.sh          # Start with new modular app
#   ./scripts/start_dashboard.sh --legacy # Start with legacy web_dashboard.py

cd "$(dirname "$0")/.."

# Determine which entry point to use
if [[ "$1" == "--legacy" ]]; then
    ENTRY_POINT="legacy/web_dashboard.py"
    KILL_PATTERN="python.*web_dashboard.py"
else
    ENTRY_POINT="run.py"
    KILL_PATTERN="python run.py"
fi

# Kill any existing instance
pkill -f "$KILL_PATTERN" 2>/dev/null
pkill -f "python.*web_dashboard.py" 2>/dev/null
pkill -f "python run.py" 2>/dev/null
sleep 1

# Activate virtual environment
source venv/bin/activate

echo "╔════════════════════════════════════════════════════════════╗"
echo "║           🔍 CNV Health Dashboard                          ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Starting server using: $ENTRY_POINT"

# Start the server in background
python "$ENTRY_POINT" &
SERVER_PID=$!

# Wait for server to be ready
echo "Waiting for server to start..."
for i in {1..20}; do
    if curl -s -o /dev/null http://localhost:5000 2>/dev/null; then
        echo "✅ Server is ready!"
        break
    fi
    sleep 0.5
done

# Open browser
echo "Opening browser..."
xdg-open http://localhost:5000 2>/dev/null || \
firefox http://localhost:5000 2>/dev/null || \
google-chrome http://localhost:5000 2>/dev/null &

echo ""
echo "🌐 Dashboard running at http://localhost:5000"
echo "Press Ctrl+C to stop"
echo ""

# Wait for the python process
wait $SERVER_PID
