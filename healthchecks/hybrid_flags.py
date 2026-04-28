"""CLI flags and runtime options parsed from sys.argv for hybrid health check."""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

USE_AI = "--ai" in sys.argv
AI_RCA = "--ai-rca" in sys.argv
RCA_BUGS = "--rca-bugs" in sys.argv
RCA_JIRA = "--rca-jira" in sys.argv
RCA_EMAIL = "--rca-email" in sys.argv
SEND_EMAIL = "--email" in sys.argv or "-e" in sys.argv
CHECK_JIRA_NEW = "--check-jira" in sys.argv or "--jira" in sys.argv

SERVER_HOST = None
for i, arg in enumerate(sys.argv):
    if arg == "--server" and i + 1 < len(sys.argv):
        SERVER_HOST = sys.argv[i + 1]
        break

EMAIL_TO = os.getenv("EMAIL_TO", "guchen@redhat.com")
for i, arg in enumerate(sys.argv):
    if arg == "--email-to" and i + 1 < len(sys.argv):
        EMAIL_TO = sys.argv[i + 1]
        break

LAB_NAME = None
for i, arg in enumerate(sys.argv):
    if arg == "--lab-name" and i + 1 < len(sys.argv):
        LAB_NAME = sys.argv[i + 1]
        break
