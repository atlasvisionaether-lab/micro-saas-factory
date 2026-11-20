"""Local scheduler for the desk and data jobs.

systemd (or cron) calls `python3 -m runner tick` every few minutes. Each tick
decides which jobs are due from the NYSE calendar and its own state, runs each
as a separate process with a timeout, logs JSON lines and writes a heartbeat.
`python3 -m runner health` checks that the ticks keep coming and jobs succeed.

It schedules analysis only: there is no order path anywhere in it.
"""

__version__ = "0.1.0"
