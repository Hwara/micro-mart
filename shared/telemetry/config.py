"""
OpenTelemetry configuration.

The telemetry package reads process environment variables only. Docker Compose,
Kubernetes, or a local launcher is responsible for loading any `.env` file
before the service process starts.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class TelemetrySettings(BaseSettings):
    """
    Settings used by init_telemetry.

    Defaults are conservative for direct local execution. Docker local examples
    override the collector endpoint and insecure mode through environment
    variables.
    """

    model_config = SettingsConfigDict(extra="ignore")

    otel_enabled: bool = True
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_exporter_otlp_insecure: bool = True
    log_format: str = "json"
    service_version: str = "0.1.0"


@lru_cache
def get_telemetry_settings() -> TelemetrySettings:
    """Return cached telemetry settings from process environment variables."""
    return TelemetrySettings()
