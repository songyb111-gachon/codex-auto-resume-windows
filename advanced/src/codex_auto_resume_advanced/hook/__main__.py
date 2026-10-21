# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""`python -m codex_auto_resume_advanced.hook --home <installation home>`: the handler, as the launcher runs it."""
import sys

from . import main

main(sys.argv[1:])
