"""Tests for TLS configuration and run() parameter handling."""

from unittest.mock import MagicMock, patch

from ungula.config import ServerConfig


class TestTLSConfig:
    def test_tls_fields_default_none(self):
        config = ServerConfig()
        assert config.tls_cert_path is None
        assert config.tls_key_path is None

    def test_tls_fields_set(self):
        config = ServerConfig(
            tls_cert_path="/etc/ssl/cert.pem",
            tls_key_path="/etc/ssl/key.pem",
        )
        assert config.tls_cert_path == "/etc/ssl/cert.pem"
        assert config.tls_key_path == "/etc/ssl/key.pem"

    def test_tls_roundtrip_dict(self):
        config = ServerConfig(
            tls_cert_path="/etc/ssl/cert.pem",
            tls_key_path="/etc/ssl/key.pem",
        )
        data = config.model_dump()
        assert data["tls_cert_path"] == "/etc/ssl/cert.pem"
        assert data["tls_key_path"] == "/etc/ssl/key.pem"

        restored = ServerConfig(**data)
        assert restored.tls_cert_path == "/etc/ssl/cert.pem"


class TestRunTLS:
    @patch("uvicorn.run")
    @patch("ungula.main.load_config")
    def test_run_passes_tls_to_uvicorn(self, mock_load, mock_uvi_run, tmp_path):
        """When TLS cert/key files exist, run() passes them to uvicorn."""
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        cert.write_text("CERT")
        key.write_text("KEY")

        mock_config = MagicMock()
        mock_config.server.host = "0.0.0.0"
        mock_config.server.port = 8001
        mock_config.server.reload = False
        mock_config.server.workers = 1
        mock_config.server.tls_cert_path = None
        mock_config.server.tls_key_path = None
        mock_load.return_value = mock_config

        from ungula.main import run

        run(ssl_certfile=str(cert), ssl_keyfile=str(key))

        mock_uvi_run.assert_called_once()
        call_kwargs = mock_uvi_run.call_args[1]
        assert call_kwargs["ssl_certfile"] == str(cert)
        assert call_kwargs["ssl_keyfile"] == str(key)

    @patch("uvicorn.run")
    @patch("ungula.main.load_config")
    def test_run_without_tls(self, mock_load, mock_uvi_run):
        """When no TLS configured, run() does not pass ssl args."""
        mock_config = MagicMock()
        mock_config.server.host = "0.0.0.0"
        mock_config.server.port = 8001
        mock_config.server.reload = False
        mock_config.server.workers = 1
        mock_config.server.tls_cert_path = None
        mock_config.server.tls_key_path = None
        mock_load.return_value = mock_config

        from ungula.main import run

        run()

        mock_uvi_run.assert_called_once()
        call_kwargs = mock_uvi_run.call_args[1]
        assert "ssl_certfile" not in call_kwargs
        assert "ssl_keyfile" not in call_kwargs

    @patch("uvicorn.run")
    @patch("ungula.main.load_config")
    def test_run_tls_missing_files_warns(self, mock_load, mock_uvi_run):
        """When TLS files don't exist, run() proceeds without TLS."""
        mock_config = MagicMock()
        mock_config.server.host = "0.0.0.0"
        mock_config.server.port = 8001
        mock_config.server.reload = False
        mock_config.server.workers = 1
        mock_config.server.tls_cert_path = None
        mock_config.server.tls_key_path = None
        mock_load.return_value = mock_config

        from ungula.main import run

        run(ssl_certfile="/nonexistent/cert.pem", ssl_keyfile="/nonexistent/key.pem")

        mock_uvi_run.assert_called_once()
        call_kwargs = mock_uvi_run.call_args[1]
        assert "ssl_certfile" not in call_kwargs

    @patch("uvicorn.run")
    @patch("ungula.main.load_config")
    def test_run_tls_from_config(self, mock_load, mock_uvi_run, tmp_path):
        """TLS can be configured via config file fields."""
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        cert.write_text("CERT")
        key.write_text("KEY")

        mock_config = MagicMock()
        mock_config.server.host = "0.0.0.0"
        mock_config.server.port = 8001
        mock_config.server.reload = False
        mock_config.server.workers = 1
        mock_config.server.tls_cert_path = str(cert)
        mock_config.server.tls_key_path = str(key)
        mock_load.return_value = mock_config

        from ungula.main import run

        run()

        mock_uvi_run.assert_called_once()
        call_kwargs = mock_uvi_run.call_args[1]
        assert call_kwargs["ssl_certfile"] == str(cert)
        assert call_kwargs["ssl_keyfile"] == str(key)
