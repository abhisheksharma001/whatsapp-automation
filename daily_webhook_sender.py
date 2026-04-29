#!/usr/bin/env python3
"""
Daily CSV Webhook Sender
Automatically sends CSV files to n8n webhook and moves them to prevent duplicates.

Features:
- Scans for unsent CSV files
- Sends to webhook with proper multipart form data
- Moves sent files to 'sent' directory
- Tracks sent files with JSON log
- Maintains duplicate prevention
"""

import os
import json
import hashlib
import requests
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPED_DATA_DIR = os.path.join(BASE_DIR, "scraped_data")
SENT_DIR = os.path.join(SCRAPED_DATA_DIR, "sent")
WEBHOOK_LOG_FILE = os.path.join(SCRAPED_DATA_DIR, "webhook_log.json")

# Your n8n webhook URL
WEBHOOK_URL = "https://abhishekshar649.app.n8n.cloud/webhook/2ea6a42a-8a7d-43e9-b751-43a4f8720e7b"

# Error webhook URL (optional)
ERROR_WEBHOOK_URL = "https://abhishekshar649.app.n8n.cloud/webhook/751afecc-bf71-495f-897c-8d52be94bbc5"

def setup_directories():
    """Ensure required directories exist."""
    os.makedirs(SCRAPED_DATA_DIR, exist_ok=True)
    os.makedirs(SENT_DIR, exist_ok=True)

def load_webhook_log():
    """Load the webhook tracking log."""
    if os.path.exists(WEBHOOK_LOG_FILE):
        try:
            with open(WEBHOOK_LOG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Error loading webhook log: {e}")
    return {"sent_files": [], "last_run": None}

def save_webhook_log(log_data):
    """Save the webhook tracking log."""
    try:
        with open(WEBHOOK_LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Error saving webhook log: {e}")

def get_file_hash(filepath):
    """Calculate SHA256 hash of a file for duplicate detection."""
    hash_sha256 = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()
    except Exception as e:
        print(f"⚠️ Error calculating hash for {filepath}: {e}")
        return None

def is_file_sent(filepath, webhook_log):
    """Check if a file has already been sent."""
    filename = os.path.basename(filepath)
    file_hash = get_file_hash(filepath)
    
    if not file_hash:
        return False
    
    for sent_file in webhook_log.get("sent_files", []):
        if sent_file.get("hash") == file_hash or sent_file.get("filename") == filename:
            return True
    return False

def send_csv_to_webhook(filepath):
    """Send a CSV file to the n8n webhook with week/date metadata."""
    print(f"🌐 Sending {os.path.basename(filepath)} to webhook...")
    
    # Calculate week and date metadata
    now = datetime.now()
    week_number = now.isocalendar()[1]  # ISO week number
    year = now.year
    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=6)
    
    metadata = {
        'date': now.strftime("%Y-%m-%d"),
        'week_number': week_number,
        'year': year,
        'week_start': week_start.strftime("%Y-%m-%d"),
        'week_end': week_end.strftime("%Y-%m-%d"),
        'week_label': f"Week {week_number} ({year})",
        'sheet_name': f"Week{week_number}_{year}",
        'filename': os.path.basename(filepath)
    }
    
    try:
        with open(filepath, 'rb') as f:
            # Send file and only date field
            files = {
                'file': (os.path.basename(filepath), f, 'text/csv')
            }
            data = {
                'date': metadata['date']
            }
            response = requests.post(WEBHOOK_URL, files=files, data=data, timeout=30)
        
        if response.status_code in (200, 201, 202, 204):
            print(f"✅ Successfully sent {os.path.basename(filepath)} (Status: {response.status_code})")
            print(f"📅 Week {week_number} ({year}) - {metadata['week_start']} to {metadata['week_end']}")
            return True, response.status_code, response.text
        else:
            print(f"⚠️ Webhook responded with status {response.status_code}: {response.text}")
            return False, response.status_code, response.text
            
    except Exception as e:
        print(f"❌ Failed to send {os.path.basename(filepath)}: {e}")
        return False, None, str(e)

def move_to_sent(filepath):
    """Move a file to the sent directory."""
    try:
        filename = os.path.basename(filepath)
        sent_filepath = os.path.join(SENT_DIR, filename)
        
        # If file already exists in sent dir, add timestamp
        if os.path.exists(sent_filepath):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            name, ext = os.path.splitext(filename)
            sent_filepath = os.path.join(SENT_DIR, f"{name}_{timestamp}{ext}")
        
        os.rename(filepath, sent_filepath)
        print(f"📁 Moved {filename} to sent directory")
        return sent_filepath
        
    except Exception as e:
        print(f"❌ Failed to move {os.path.basename(filepath)}: {e}")
        return None

def log_sent_file(filepath, status, response_status, response_text):
    """Log a sent file to the tracking log."""
    webhook_log = load_webhook_log()
    
    log_entry = {
        "filename": os.path.basename(filepath),
        "original_path": filepath,
        "hash": get_file_hash(filepath),
        "sent_time": datetime.now().isoformat(),
        "status": status,
        "response_status": response_status,
        "response_text": response_text[:200] if response_text else ""
    }
    
    webhook_log["sent_files"].append(log_entry)
    webhook_log["last_run"] = datetime.now().isoformat()
    
    save_webhook_log(webhook_log)

def send_error_alert(error_msg, error_type="general", filename=None, webhook_status=None, webhook_response=None):
    """Send a detailed error alert to the error webhook."""
    if not ERROR_WEBHOOK_URL:
        return
        
    try:
        payload = {
            "error": error_msg,
            "error_type": error_type,
            "timestamp": datetime.now().isoformat(),
            "script": "daily_webhook_sender.py",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "filename": filename,
            "webhook_status": webhook_status,
            "webhook_response": webhook_response[:500] if webhook_response else None,
            "system_info": {
                "working_directory": BASE_DIR,
                "scraped_data_dir": SCRAPED_DATA_DIR,
                "sent_dir": SENT_DIR
            }
        }
        response = requests.post(ERROR_WEBHOOK_URL, json=payload, timeout=30)
        
        if response.status_code in (200, 201, 202, 204):
            print("✅ Error alert sent successfully")
        else:
            print(f"⚠️ Error webhook responded with status {response.status_code}")
            
    except Exception as e:
        print(f"❌ Failed to send error alert: {e}")

def find_unsent_csv_files():
    """Find all CSV files that haven't been sent yet."""
    unsent_files = []
    webhook_log = load_webhook_log()
    
    if not os.path.exists(SCRAPED_DATA_DIR):
        print(f"⚠️ Directory {SCRAPED_DATA_DIR} does not exist")
        return unsent_files
    
    for filename in os.listdir(SCRAPED_DATA_DIR):
        if filename.endswith('.csv'):
            filepath = os.path.join(SCRAPED_DATA_DIR, filename)
            if os.path.isfile(filepath) and not is_file_sent(filepath, webhook_log):
                unsent_files.append(filepath)
    
    return unsent_files

def main():
    """Main execution function."""
    print("=" * 70)
    print("🤖 Daily CSV Webhook Sender")
    print("=" * 70)
    
    setup_directories()
    
    # Find unsent CSV files
    unsent_files = find_unsent_csv_files()
    
    if not unsent_files:
        print("📂 No unsent CSV files found.")
        print("✅ All CSV files have been sent to webhook.")
        return
    
    print(f"📋 Found {len(unsent_files)} unsent CSV files:")
    for filepath in unsent_files:
        print(f"   📄 {os.path.basename(filepath)}")
    
    # Send each file
    successful_sends = 0
    failed_sends = 0
    
    for filepath in unsent_files:
        print(f"\n📤 Processing: {os.path.basename(filepath)}")
        
        # Send to webhook
        success, status_code, response_text = send_csv_to_webhook(filepath)
        
        if success:
            # Move to sent directory
            sent_path = move_to_sent(filepath)
            if sent_path:
                log_sent_file(sent_path, "success", status_code, response_text)
                successful_sends += 1
            else:
                log_sent_file(filepath, "move_failed", status_code, "Failed to move file")
                # Send detailed error alert for file move failure
                error_msg = f"Failed to move {os.path.basename(filepath)} to sent directory"
                send_error_alert(error_msg, error_type="file_move_failure", 
                               filename=os.path.basename(filepath), 
                               webhook_status=None, 
                               webhook_response="File move operation failed")
                failed_sends += 1
        else:
            log_sent_file(filepath, "send_failed", status_code, response_text)
            # Send detailed error alert for individual file failure
            error_msg = f"Failed to send {os.path.basename(filepath)} to webhook"
            send_error_alert(error_msg, error_type="webhook_failure", 
                           filename=os.path.basename(filepath), 
                           webhook_status=status_code, 
                           webhook_response=response_text)
            failed_sends += 1
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 Webhook Sending Summary")
    print("=" * 70)
    print(f"✅ Successfully sent: {successful_sends}")
    print(f"❌ Failed to send: {failed_sends}")
    print(f"📊 Total processed: {len(unsent_files)}")
    
    if failed_sends > 0:
        error_msg = f"Failed to send {failed_sends} CSV files to webhook"
        send_error_alert(error_msg, error_type="batch_failure", webhook_status=None, webhook_response=None)

if __name__ == "__main__":
    main()
