from flask import Flask, render_template, jsonify
import os
import json
import subprocess
from datetime import datetime

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATS_FILE = os.path.join(BASE_DIR, "scraped_data", "dashboard_stats.json")

def get_stats():
    """Read the current stats from the JSON file."""
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            return {"error": f"Failed to read stats: {e}"}
    return {
        "last_run_time": "Never",
        "last_run_status": "unknown",
        "total_contacts_all_time": 0,
        "last_run_contacts": 0,
        "recent_runs": []
    }

@app.route('/')
def dashboard():
    """Render the main dashboard."""
    stats = get_stats()
    
    # Format dates
    if stats.get('last_run_time') and stats['last_run_time'] != "Never":
        try:
            dt = datetime.fromisoformat(stats['last_run_time'])
            stats['formatted_time'] = dt.strftime("%B %d, %Y at %I:%M %p")
        except:
            stats['formatted_time'] = stats['last_run_time']
    else:
        stats['formatted_time'] = "No runs yet"
        
    return render_template('index.html', stats=stats)

@app.route('/api/stats')
def api_stats():
    """API endpoint to get latest stats (for auto-refresh)."""
    return jsonify(get_stats())

@app.route('/api/run-scraper', methods=['POST'])
def run_scraper():
    """Endpoint to trigger the scraper manually."""
    # We use Popen so we don't block the UI while it runs
    try:
        script_path = os.path.join(BASE_DIR, "wasendly_scraper.py")
        # Start detached depending on OS, stdout straight to the void or a log file to keep it clean
        subprocess.Popen(
            ["python", script_path], 
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE  # Opens a new window so user can see it running
        )
        return jsonify({"success": True, "message": "Scraper started in a new window."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    # Ensure scraped_data dir exists
    os.makedirs(os.path.join(BASE_DIR, "scraped_data"), exist_ok=True)
    app.run(host='127.0.0.1', port=5000, debug=True)
