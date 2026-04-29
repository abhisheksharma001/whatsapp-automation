#!/bin/bash

# Setup script for daily webhook sender scheduler
# This script installs the launchd plist for macOS

echo "🚀 Setting up Daily Webhook Sender Scheduler..."

# Create logs directory
mkdir -p "/Users/abhisheksharma/whatsapp-automation/logs"

# Copy plist file to LaunchAgents
PLIST_FILE="com.abhishek.webhook-sender.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
TARGET_PATH="$LAUNCH_AGENTS_DIR/$PLIST_FILE"

echo "📁 Installing plist file to LaunchAgents..."
cp "$PLIST_FILE" "$TARGET_PATH"

# Load the launch agent
echo "⏰ Loading launch agent..."
launchctl load "$TARGET_PATH"

# Verify installation
if launchctl list | grep -q "com.abhishek.webhook-sender"; then
    echo "✅ Scheduler successfully installed and loaded!"
    echo "📅 The webhook sender will run daily at 9:00 AM"
    echo "📋 To check status: launchctl list | grep webhook-sender"
    echo "🛑 To stop: launchctl unload $TARGET_PATH"
    echo "📁 Logs will be saved to logs/webhook-sender.log"
else
    echo "❌ Failed to load launch agent"
    echo "🔧 Try manually: launchctl load $TARGET_PATH"
fi

echo ""
echo "🔍 Test the scheduler now with:"
echo "python3 daily_webhook_sender.py"
