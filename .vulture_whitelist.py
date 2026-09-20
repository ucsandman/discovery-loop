# Vulture whitelist (read by the global pre-commit hook). Names below are used dynamically:
# problem modules are loaded by loop.py via importlib and consumed by attribute, and the MATPOWER column
# constants are a reference table that solvers evolved by the loop import as needed.
_ = object()
_.TITLE
_.TARGETS
_.DEVELOPMENT_TARGETS
_.VALIDATION_TARGETS
# Alternate plugin manifest fields read by evaluation.build_manifest via getattr.
_.DEVELOPMENT
# Release validation hook, read by loop.py via getattr(plugin, "validate_release").
_.validate_release
_.LARGE_TARGETS
_.LARGE_DEFAULTS
_.VALIDATION
_.RELEASE_HOLDOUT
_.CONFIRMATION_ON_DEVELOPMENT
_.EVOLUTION_POLICY  # read via getattr in loop.py; the matmul plugin opts in
_.HOLDOUT
_.DEFAULTS
# research_context reads tags through getattr; plugin integrity tests check capabilities.
_.PATTERN_TAGS
_.RELEASE_VALIDATION_SUPPORTED
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
# Isolation tests inspect the bounded worker mount through this helper.
_._mount_source
# pytest invokes this autouse fixture by registration.
_.subscription_auth
# Canonical provider API callers may be outside an incremental staged-file scan.
_.preflight
_.call_model
# CVRP save/export and unchanged plugin tests use these outside staged scans.
_.to_sol
_.parse_sol
# loop.py entrypoint, called under __main__ (vulture reports it at 60% whenever loop.py is staged).
_.main
