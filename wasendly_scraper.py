#!/usr/bin/env python3
"""
WhatsApp Group Contacts Scraper — WASendly Integration
Uses the WASendly Chrome extension's internal Store API to extract
contacts from newly joined WhatsApp groups.

Features:
  - Differential group detection (finds groups joined since last run)
  - Direct Store API access via WASendly extension (no DOM scraping)
  - CSV export with timestamped filenames
  - UTF-8 safe for Windows PowerShell
"""

import sys
# Force UTF-8 encoding for stdout to prevent emoji printing errors on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

import os
import csv
import json
import time
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, WebDriverException

# ─── Configuration ───────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "scraped_data")
SNAPSHOT_FILE = os.path.join(OUTPUT_DIR, "groups_snapshot.json")
CHROME_DRIVER_PATH = r"C:\selenium\chromedriver.exe"
CHROME_PROFILE_PATH = r"C:\selenium\chrome_profile"

# How long to wait for WhatsApp Web to fully load (seconds)
WHATSAPP_LOAD_TIMEOUT = 90
# How long to wait for WASendly Store API to be ready (seconds)
STORE_READY_TIMEOUT = 15

# Webhook URL to send the CSV to (leave empty to disable)
WEBHOOK_URL = "https://abhishekshar649.app.n8n.cloud/webhook/2ea6a42a-8a7d-43e9-b751-43a4f8720e7b"

# Webhook URL for errors/failures (leave empty to disable)
ERROR_WEBHOOK_URL = "https://abhishekshar649.app.n8n.cloud/webhook/751afecc-bf71-495f-897c-8d52be94bbc5"

# ─── JavaScript Payloads ────────────────────────────────────────────────────

JS_WAIT_FOR_STORE = """
var callback = arguments[arguments.length - 1];
var startTime = Date.now();
var maxWait = arguments[0] || 20000;

function checkStore() {
    // Check if WASendly's store-init.js has fully initialized window.Store.Chat
    if (window.Store && window.Store.Chat) {
        // Store is fully initialized
        var chatCount = 0;
        try {
            if (window.Store.Chat.models) chatCount = window.Store.Chat.models.length;
            else if (window.Store.Chat._models) chatCount = window.Store.Chat._models.size;
        } catch(e) {}
        callback({ ready: true, storeType: window.Store.InitType || 'unknown', chatCount: chatCount });
    } else if (Date.now() - startTime > maxWait) {
        callback({ ready: false, error: 'Store initialization timeout (' + maxWait + 'ms)', hasStore: !!window.Store });
    } else {
        setTimeout(checkStore, 500);
    }
}
checkStore();
"""

JS_GET_GROUPS = """
var callback = arguments[arguments.length - 1];

// First approach: Try direct Store access (fastest, no message passing needed)
if (window.Store && window.Store.Chat) {
    try {
        var allChats = [];
        if (window.Store.Chat.models && window.Store.Chat.models.length > 0) {
            allChats = window.Store.Chat.models;
        } else if (window.Store.Chat._models) {
            allChats = Array.from(window.Store.Chat._models.values());
        } else if (typeof window.Store.Chat.filter === 'function') {
            allChats = window.Store.Chat.filter(function() { return true; });
        }

        var groups = [];
        for (var i = 0; i < allChats.length; i++) {
            var chat = allChats[i];
            if (!chat || !chat.id) continue;
            var chatId = chat.id._serialized || chat.id;
            if (typeof chatId !== 'string') continue;
            if (!chatId.includes('@g.us')) continue;

            groups.push({
                id: chatId,
                name: chat.name || chat.formattedTitle || 'Unnamed Group',
                participantCount: chat.groupMetadata ? (chat.groupMetadata.participants ? chat.groupMetadata.participants.length || 0 : 0) : 0
            });
        }

        if (groups.length > 0) {
            callback({ success: true, groups: groups, method: 'direct' });
            return;
        }
    } catch(e) {
        // Fall through to message-based approach
    }
}

// Second approach: Use WASendly's message passing (triggers store-init.js handler)
new Promise(function(resolve) {
    var timeout = setTimeout(function() {
        window.removeEventListener('message', listener);
        resolve({ success: false, error: 'Timeout waiting for groups list' });
    }, 15000);

    function listener(event) {
        if (event.data && event.data.groupsInfoTwoInject) {
            clearTimeout(timeout);
            window.removeEventListener('message', listener);
            resolve({ success: true, groups: event.data.groupsInfoTwoInject, method: 'message' });
        } else if (event.data && event.data.type === 'groups-list-response') {
            clearTimeout(timeout);
            window.removeEventListener('message', listener);
            if (event.data.success) {
                resolve({ success: true, groups: event.data.groups || [], method: 'message' });
            } else {
                resolve({ success: false, error: event.data.error });
            }
        }
    }
    window.addEventListener('message', listener);
    window.postMessage({ type: 'groupsInfoTwo' }, '*');
}).then(callback).catch(function(err) { callback({ success: false, error: String(err) }); });
"""

JS_GET_GROUP_CONTACTS = """
var callback = arguments[arguments.length - 1];
var groupId = arguments[0];

return new Promise(function(resolve) {
    var timeout = setTimeout(function() {
        window.removeEventListener('message', listener);
        resolve({ success: false, error: 'Timeout waiting for group contacts' });
    }, 15000);

    function listener(event) {
        if (event.data && event.data.type === 'group-contacts-response' && event.data.groupId === groupId) {
            clearTimeout(timeout);
            window.removeEventListener('message', listener);
            if (event.data.success) {
                resolve({ success: true, contacts: event.data.contacts || [] });
            } else {
                resolve({ success: false, error: event.data.error || 'Failed to get contacts' });
            }
        }
    }
    window.addEventListener('message', listener);
    window.postMessage({ type: 'get-group-contacts', groupId: groupId }, '*');
}).then(callback).catch(function(err) { callback({ success: false, error: String(err) }); });
"""

# ─── Helper Functions ────────────────────────────────────────────────────────

def create_driver():
    """Create Chrome WebDriver with WASendly extension loaded."""
    try:
        chrome_options = Options()
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument(f"--user-data-dir={CHROME_PROFILE_PATH}")
        chrome_options.add_argument("--profile-directory=Default")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        service = Service(executable_path=CHROME_DRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return driver
    except Exception as e:
        print(f"❌ Failed to create Chrome driver: {e}")
        return None


def wait_for_whatsapp_login(driver, timeout=WHATSAPP_LOAD_TIMEOUT):
    """Wait for WhatsApp Web to fully load and be logged in."""
    print("⏳ Waiting for WhatsApp Web to load...")
    end_time = time.time() + timeout

    while time.time() < end_time:
        try:
            # Check for logged-in indicators
            logged_in = driver.find_elements(By.CSS_SELECTOR,
                "[data-icon='chat-filled-refreshed'], "
                "[data-testid='chat-list'], "
                "#pane-side"
            )
            if logged_in:
                print("✅ WhatsApp Web is logged in and ready!")
                return True

            # Check for QR code
            qr = driver.find_elements(By.CSS_SELECTOR, "canvas")
            if qr:
                remaining = int(end_time - time.time())
                print(f"📱 QR code detected — scan with your phone ({remaining}s remaining)...", end="\r")
        except:
            pass

        time.sleep(1)

    print()
    print("❌ WhatsApp Web login timed out.")
    return False


def wait_for_store_api(driver, timeout=STORE_READY_TIMEOUT):
    """Wait for WASendly's Store API to be ready."""
    print("⏳ Waiting for WASendly Store API...")
    try:
        driver.set_script_timeout(timeout + 5)
        result = driver.execute_async_script(JS_WAIT_FOR_STORE, timeout * 1000)
        if result and result.get('ready'):
            print("✅ WASendly Store API is ready!")
            return True
        else:
            print(f"⚠️ Store API not ready: {result.get('error', 'unknown')}")
            return False
    except Exception as e:
        print(f"⚠️ Store API wait error: {e}")
        # Might still work — WhatsApp is loaded even if store flag isn't set
        return True


def fetch_groups(driver):
    """Fetch all WhatsApp groups using WASendly's Store API."""
    print("📋 Fetching groups list...")
    try:
        driver.set_script_timeout(20)
        result = driver.execute_async_script(JS_GET_GROUPS)

        if result and result.get('success'):
            groups = result.get('groups', [])
            print(f"✅ Found {len(groups)} groups")
            return groups
        else:
            print(f"❌ Failed to fetch groups: {result.get('error', 'unknown')}")
            return []
    except Exception as e:
        print(f"❌ Error fetching groups: {e}")
        return []


def fetch_group_contacts(driver, group_id, group_name):
    """Fetch contacts for a specific group using WASendly's Store API."""
    try:
        driver.set_script_timeout(20)
        result = driver.execute_async_script(JS_GET_GROUP_CONTACTS, group_id)

        if result and result.get('success'):
            contacts = result.get('contacts', [])
            print(f"   ✅ {group_name}: {len(contacts)} contacts extracted")
            return contacts
        else:
            print(f"   ⚠️ {group_name}: {result.get('error', 'no contacts')}")
            return []
    except Exception as e:
        print(f"   ❌ {group_name}: Error — {e}")
        return []


# ─── Snapshot / Differential Detection ───────────────────────────────────────

def load_snapshot():
    """Load the previous groups snapshot."""
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('group_ids', set()), data.get('last_run', 'never')
        except:
            pass
    return set(), 'never'


def save_snapshot(group_ids):
    """Save the current groups snapshot."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(SNAPSHOT_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'group_ids': list(group_ids),
            'last_run': datetime.now().isoformat(),
            'count': len(group_ids)
        }, f, indent=2, ensure_ascii=False)
    print(f"💾 Snapshot saved with {len(group_ids)} groups")


def find_new_groups(current_groups, previous_ids):
    """Find groups that are new since the last snapshot."""
    new_groups = []
    for group in current_groups:
        gid = group.get('id') or group.get('jid') or group.get('_serialized') or str(group.get('name', ''))
        if gid and gid not in previous_ids:
            new_groups.append(group)
    return new_groups


# ─── CSV Export ──────────────────────────────────────────────────────────────

def save_contacts_csv(all_contacts, output_dir):
    """Save all scraped contacts to a timestamped CSV file."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"wasendly_contacts_{timestamp}.csv"
    filepath = os.path.join(output_dir, filename)

    headers = ['Contact Index', 'Phone Number', 'Name', 'Push Name', 'Is Admin']

    with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)
        for contact in all_contacts:
            writer.writerow([
                contact.get('index', ''),
                contact.get('id', contact.get('phone', contact.get('number', 'N/A'))),
                contact.get('name', contact.get('displayName', '')),
                contact.get('pushname', contact.get('pushName', '')),
                contact.get('isAdmin', contact.get('isSuperAdmin', False))
            ])

    print(f"\n📁 Contacts saved to: {filename}")
    print(f"📊 Total contacts: {len(all_contacts)}")
    return filepath


def send_to_webhook(filepath, url):
    """Send the generated CSV file to a webhook."""
    if not url or url == "YOUR_WEBHOOK_URL_HERE":
        return
        
    print(f"\n🌐 Sending data to webhook: {url}")
    try:
        with open(filepath, 'rb') as f:
            files = {'file': (os.path.basename(filepath), f, 'text/csv')}
            response = requests.post(url, files=files, timeout=30)
            
        if response.status_code in (200, 201, 202, 204):
            print(f"✅ Successfully sent to webhook (Status: {response.status_code})")
        else:
            print(f"⚠️ Webhook responded with status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ Failed to send to webhook: {e}")

def send_error_webhook(error_msg, url):
    """Send an error alert to a webhook."""
    if not url or url == "YOUR_ERROR_WEBHOOK_URL_HERE":
        return
        
    print(f"\n🌐 Sending ERROR to webhook: {url}")
    try:
        payload = {
            "error": error_msg,
            "timestamp": datetime.now().isoformat(),
            "script": "wasendly_scraper.py"
        }
        response = requests.post(url, json=payload, timeout=30)
            
        if response.status_code in (200, 201, 202, 204):
            print(f"✅ Successfully sent error alert to webhook")
        else:
            print(f"⚠️ Error Webhook responded with status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ Failed to send error to webhook: {e}")

def update_dashboard_stats(status, error_msg=None, contacts_scraped=0, groups_scraped=0):
    """Write run statistics to a JSON file for the dashboard UI to read."""
    stats_file = os.path.join(OUTPUT_DIR, "dashboard_stats.json")
    
    # Load existing stats to preserve history
    stats = {}
    if os.path.exists(stats_file):
        try:
            with open(stats_file, 'r', encoding='utf-8') as f:
                stats = json.load(f)
        except:
            pass
            
    # Update stats
    stats["last_run_time"] = datetime.now().isoformat()
    stats["last_run_status"] = status
    stats["last_error"] = error_msg
    
    if status == "success":
        # Increment totals
        stats["total_contacts_all_time"] = stats.get("total_contacts_all_time", 0) + contacts_scraped
        stats["last_run_contacts"] = contacts_scraped
        stats["last_run_groups"] = groups_scraped
        
        # Keep a history of the last 5 runs
        history = stats.get("recent_runs", [])
        history.insert(0, {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "contacts": contacts_scraped,
            "groups": groups_scraped,
            "status": "success"
        })
        stats["recent_runs"] = history[:5]
    else:
        # Log failure in history
        history = stats.get("recent_runs", [])
        history.insert(0, {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "failed",
            "error": str(error_msg)[:100]
        })
        stats["recent_runs"] = history[:5]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("🤖 WhatsApp Group Contacts Scraper — WASendly Integration")
    print("=" * 70)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load previous snapshot
    previous_ids, last_run = load_snapshot()
    if previous_ids:
        print(f"📂 Previous snapshot: {len(previous_ids)} groups (last run: {last_run})")
    else:
        print("📂 No previous snapshot — first run, will scrape ALL groups")

    # Launch Chrome
    print("\n🚀 Launching Chrome with WASendly extension...")
    driver = create_driver()
    if not driver:
        return

    try:
        # Navigate to WhatsApp Web
        print("🌐 Opening WhatsApp Web...")
        driver.get("https://web.whatsapp.com")

        # Wait for login
        if not wait_for_whatsapp_login(driver):
            msg = "Could not log into WhatsApp Web. Timeout reached."
            print(f"❌ {msg} Exiting.")
            send_error_webhook(msg, ERROR_WEBHOOK_URL)
            update_dashboard_stats("failed", error_msg=msg)
            return

        # Give WhatsApp time to fully initialize its internal stores
        # WASendly's store-init.js hooks into webpack modules which need time
        print("⏳ Waiting 10 seconds for WhatsApp internal stores to initialize...")
        time.sleep(10)

        # Wait for WASendly Store API
        wait_for_store_api(driver)

        # Fetch all groups
        groups = fetch_groups(driver)
        if not groups:
            msg = "No groups found. Make sure you are in at least one group or WhatsApp data is loaded."
            print(f"❌ {msg}")
            send_error_webhook(msg, ERROR_WEBHOOK_URL)
            update_dashboard_stats("failed", error_msg=msg)
            return

        # Build current group ID set
        current_ids = set()
        for g in groups:
            gid = g.get('id') or g.get('jid') or g.get('_serialized') or str(g.get('name', ''))
            if gid:
                current_ids.add(gid)

        # Find new groups (differential detection)
        if previous_ids:
            new_groups = find_new_groups(groups, previous_ids)
            if new_groups:
                print(f"\n🆕 Found {len(new_groups)} NEW groups since last run:")
                for g in new_groups:
                    print(f"   📱 {g.get('name', g.get('subject', 'Unknown'))}")
                groups_to_scrape = new_groups
            else:
                print(f"\n✅ Reason: All {len(groups)} currently found groups were already recorded in the previous snapshot.")
                print("ℹ️  Skipping scraping. To scrape them again, either join a new group or delete 'scraped_data/groups_snapshot.json'.")
                groups_to_scrape = []
        else:
            print(f"\n📋 First run — scraping all {len(groups)} groups")
            groups_to_scrape = groups

        # Extract contacts from each group
        print(f"\n🔍 Extracting contacts from {len(groups_to_scrape)} groups...")
        all_contacts = []

        for i, group in enumerate(groups_to_scrape):
            group_id = group.get('id') or group.get('jid') or group.get('_serialized')
            group_name = group.get('name') or group.get('subject') or 'Unknown Group'
            print(f"\n[{i+1}/{len(groups_to_scrape)}] 📱 {group_name}")

            if not group_id:
                print(f"   ⚠️ Skipping — no group ID available")
                continue

            contacts = fetch_group_contacts(driver, group_id, group_name)
            for idx, contact in enumerate(contacts):
                contact['groupName'] = group_name
                contact['index'] = idx + 1
                all_contacts.append(contact)

            # Small delay between groups to avoid overwhelming the API
            if i < len(groups_to_scrape) - 1:
                time.sleep(1)

        # Save results
        if all_contacts:
            csv_file = save_contacts_csv(all_contacts, OUTPUT_DIR)

            # Print summary
            print("\n" + "=" * 70)
            print("📊 Scraping Summary")
            print("=" * 70)
            group_summary = {}
            for c in all_contacts:
                gn = c.get('groupName', 'Unknown')
                group_summary[gn] = group_summary.get(gn, 0) + 1
            for gn, count in group_summary.items():
                print(f"   📱 {gn}: {count} contacts")
            print(f"\n   📁 CSV: {csv_file}")
            
            # Send to webhook if configured
            if WEBHOOK_URL and WEBHOOK_URL != "YOUR_WEBHOOK_URL_HERE":
                send_to_webhook(csv_file, WEBHOOK_URL)
        else:
            print("\n⚠️ No contacts were extracted from any group.")

        # Save updated snapshot
        save_snapshot(current_ids)
        
        # Update Dashboard Stats
        update_dashboard_stats("success", contacts_scraped=len(all_contacts), groups_scraped=len(groups_to_scrape))

    except Exception as e:
        msg = f"Critical Scraper Error: {e}"
        print(f"\n❌ {msg}")
        send_error_webhook(msg, ERROR_WEBHOOK_URL)
        update_dashboard_stats("failed", error_msg=msg)
        import traceback
        traceback.print_exc()
    finally:
        print("\n🔄 Closing Chrome...")
        try:
            driver.quit()
            print("✅ Browser closed.")
        except:
            pass


if __name__ == "__main__":
    main()
