# Vulture whitelist (read by the global pre-commit hook). Names below are used dynamically:
# problem modules are loaded by loop.py via importlib and consumed by attribute, and the MATPOWER column
# constants are a reference table that solvers evolved by the loop import as needed.
_ = object()
_.TITLE
_.TARGETS
_.DEFAULTS
_.MAXIMIZE
_.FAIL_SCORE
_.TOTAL_DESC
_.SUBMIT_NOTE
_.EMAIL_TO
_.PROMPT
_.TASK
_.records_fetch
_.records_load
_.solver_argv
_.evaluate
_.score
_.better
_.beats
_.raw_path
_.sub_path
_.save
_.email_subject
_.email_body
_.BUS_AREA
_.BASE_KV
_.ZONE
_.MBASE
_.RATE_B
_.RATE_C
_.STARTUP
_.SHUTDOWN
_.author
# stdlib HTTPServer/BaseHTTPRequestHandler dispatch these by name.
_.daemon_threads
_.allow_reuse_address
_.server_version
_.log_message
_.do_GET
_.do_POST
# Compatibility helpers exercised by unchanged tests outside staged-file scans.
_.retro_slot
_.publish_slot
_.official_solution_path
# pytest invokes this autouse fixture by registration.
_.subscription_auth
