"""
CNV Health Dashboard - Background Scheduler
Checks for scheduled tasks and runs them at the appropriate times.
"""

import os
import sys
import json
import time
import threading
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import Config

BASE_DIR = Config.BASE_DIR
SCHEDULES_FILE = os.path.join(BASE_DIR, "schedules.json")

# Scheduler state
scheduler_running = False
scheduler_thread = None
check_interval = 60  # Check every minute


def load_schedules():
    """Load schedules from file"""
    if os.path.exists(SCHEDULES_FILE):
        try:
            with open(SCHEDULES_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []


def save_schedules(schedules):
    """Save schedules to file"""
    with open(SCHEDULES_FILE, 'w') as f:
        json.dump(schedules, f, indent=2)


def should_run_now(schedule):
    """Check if a schedule should run at the current time"""
    if schedule.get('status') != 'active':
        return False

    now = datetime.now()

    if schedule['type'] == 'once':
        scheduled_time = schedule.get('scheduled_time', '')
        if scheduled_time:
            scheduled_dt = datetime.strptime(scheduled_time, '%Y-%m-%d %H:%M')
            diff = abs((now - scheduled_dt).total_seconds())
            if diff < check_interval and now >= scheduled_dt:
                return True

    elif schedule['type'] == 'recurring':
        frequency = schedule.get('frequency', 'daily')
        schedule_time = schedule.get('time', '06:00')

        schedule_hour, schedule_min = map(int, schedule_time.split(':'))
        time_match = now.hour == schedule_hour and abs(now.minute - schedule_min) < 2

        if not time_match and frequency != 'hourly':
            return False

        if frequency == 'hourly':
            return now.minute < 2
        elif frequency == 'daily':
            return time_match
        elif frequency == 'weekly':
            days = schedule.get('days', ['mon'])
            day_map = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}
            target_days = [day_map.get(d, 0) for d in days]
            return time_match and now.weekday() in target_days
        elif frequency == 'monthly':
            day_of_month = schedule.get('day_of_month', 1)
            return time_match and now.day == day_of_month

    return False


def run_schedule(schedule, app):
    """Execute a scheduled task"""
    from app.routes import start_build
    from config.settings import AVAILABLE_CHECKS

    print(f"[Scheduler] Running schedule: {schedule.get('name', 'Unnamed')}")

    checks = schedule.get('checks', list(AVAILABLE_CHECKS.keys()))
    options = schedule.get('options', {'rca_level': 'none'})

    # Mark as scheduled build
    options['scheduled'] = True
    options['schedule_id'] = schedule['id']
    options['schedule_name'] = schedule.get('name', 'Scheduled')

    with app.app_context():
        # Scheduled builds run as 'system' (no user_id)
        start_build(checks, options, user_id=None)

    # Update schedule
    schedules = load_schedules()
    for s in schedules:
        if s['id'] == schedule['id']:
            s['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M')
            if s['type'] == 'once':
                s['status'] = 'completed'
            break

    save_schedules(schedules)


def scheduler_loop(app):
    """Main scheduler loop - runs in a background thread"""
    global scheduler_running

    print("[Scheduler] Started background scheduler")

    while scheduler_running:
        try:
            schedules = load_schedules()

            for schedule in schedules:
                if should_run_now(schedule):
                    last_run = schedule.get('last_run', '')
                    if last_run:
                        try:
                            last_run_dt = datetime.strptime(last_run, '%Y-%m-%d %H:%M')
                            if (datetime.now() - last_run_dt).total_seconds() < check_interval:
                                continue
                        except:
                            pass

                    run_schedule(schedule, app)

        except Exception as e:
            print(f"[Scheduler] Error: {e}")

        time.sleep(check_interval)

    print("[Scheduler] Stopped background scheduler")


def start_scheduler(app):
    """Start the background scheduler"""
    global scheduler_running, scheduler_thread

    if scheduler_running:
        return

    scheduler_running = True
    scheduler_thread = threading.Thread(target=scheduler_loop, args=(app,), daemon=True)
    scheduler_thread.start()


def stop_scheduler():
    """Stop the background scheduler"""
    global scheduler_running
    scheduler_running = False
