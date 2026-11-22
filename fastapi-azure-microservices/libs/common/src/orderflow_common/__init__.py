"""OrderFlow shared platform library.

Everything a service needs to be "production shaped" lives here so each
service only contains business logic: settings, structured logging,
OpenTelemetry/Azure Monitor, correlation IDs, RFC 7807 errors, health
probes, JWT auth, async SQLAlchemy and a pluggable event bus.
"""

__version__ = "0.1.0"
