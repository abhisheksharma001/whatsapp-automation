CHROME_DRIVER_PATH = r"C:\selenium\chromedriver.exe"
CHROME_PROFILE_PATH = r"C:\selenium\chrome_profile_instagram"

INSTAGRAM_URL = "https://www.instagram.com/"

# Set to True to run without a visible browser window.
# Note: if True, you won't be able to do manual likes/follows during the session.
HEADLESS = False

SESSION_DURATION_SECONDS = 60 * 60

# Manual cadence prompts (no auto-engagement). The script will print reminders
# to help you keep a consistent rhythm while you engage manually.
CADENCE_MIN_SECONDS = 5
CADENCE_MAX_SECONDS = 10

# Minimal cooldown to avoid repeated runs too close together.
COOLDOWN_MINUTES = 30

SCHEDULE_START_HOUR = 11
SCHEDULE_END_HOUR = 15

VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800

# Demo mode settings (visual scrolling + mouse movement, no engagement)
DEMO_DURATION_SECONDS = 120  # 2 minutes of visual demo
DEMO_SCROLL_MIN_WAIT = 2     # Minimum seconds between scrolls
DEMO_SCROLL_MAX_WAIT = 5     # Maximum seconds between scrolls
DEMO_MOUSE_MOVEMENT = True   # Enable mouse movement during demo
