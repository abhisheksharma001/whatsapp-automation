# WhatsApp Group Contacts Scraper

Automated WhatsApp group contact extraction using the **WASendly Chrome extension** and Selenium.

## How It Works

1. Selenium launches Chrome with a persistent profile that has WASendly pre-installed
2. WhatsApp Web loads automatically (no QR code after first login)
3. WASendly's internal Store API fetches all group data directly — no DOM scraping
4. **Differential detection**: Compares today's groups with the previous snapshot to find newly joined groups
5. Extracts contacts from new groups and exports to CSV

## Quick Start

```bash
# Run directly
python wasendly_scraper.py

# Or via batch file (for n8n/Task Scheduler)
run_whatsapp.bat
```

## Files

| File | Purpose |
|------|---------|
| `wasendly_scraper.py` | Main scraper script |
| `run_whatsapp.bat` | Batch file for scheduled execution |
| `scraped_data/` | CSV output + groups snapshot |
| `whatsapp_automation_workflow.json` | n8n workflow definition |

## Output

- **CSV files**: `scraped_data/wasendly_contacts_YYYYMMDD_HHMMSS.csv`
- **Snapshot**: `scraped_data/groups_snapshot.json` (tracks groups for differential detection)

## Requirements

- Python 3.11+ with Selenium
- Chrome + ChromeDriver at `C:\selenium\`
- WASendly extension installed in `C:\selenium\chrome_profile`
