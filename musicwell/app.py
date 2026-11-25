"""Application entry point."""
import os
import sys
from pathlib import Path

# numpy's maths library would start a thread per core at import; the EQ and visualizer don't need them
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from musicwell import APP_ID, APP_NAME, __version__


# CA bundles used by common Linux distributions
_CA_FILES = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu, Mint, Arch, Gentoo
    "/etc/pki/tls/certs/ca-bundle.crt",  # Fedora, RHEL, CentOS
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
    "/etc/ssl/ca-bundle.pem",  # openSUSE
    "/etc/ssl/cert.pem",  # Alpine, Arch, Void
    "/etc/certs/ca-certificates.crt",
)


def fix_certificates():
    """The AppImage's OpenSSL looks in Red Hat's paths, so point it at the system's CA bundle."""
    if os.environ.get("SSL_CERT_FILE"):
        return
    import ssl
    try:
        if ssl.create_default_context().cert_store_stats().get("x509_ca", 0) > 0:
            return
    except Exception:
        pass
    for f in _CA_FILES:
        if os.path.isfile(f):
            os.environ["SSL_CERT_FILE"] = f
            break
    else:
        try:
            import certifi
            os.environ["SSL_CERT_FILE"] = certifi.where()
        except ImportError:
            return
    if os.path.isdir("/etc/ssl/certs") and not os.environ.get("SSL_CERT_DIR") and not sys.platform == "win32":
        os.environ["SSL_CERT_DIR"] = "/etc/ssl/certs"


def _pick_audio_backend():
    """Qt's PipeWire backend can crash with no PipeWire daemon; fall back to PulseAudio."""
    if sys.platform == "win32":
        # The EQ and gapless output need Qt's FFmpeg backend.
        os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
        return
    if os.environ.get("QT_AUDIO_BACKEND") or not sys.platform.startswith("linux"):
        return
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if not os.path.exists(os.path.join(runtime, "pipewire-0")):
        os.environ["QT_AUDIO_BACKEND"] = "pulseaudio"


def main() -> int:
    # Switch threads every 1 ms (default 5) so the audio thread isn't starved while the UI is busy.
    sys.setswitchinterval(0.001)
    from musicwell.paths import move_from_old_name
    move_from_old_name()
    from musicwell import log as mwlog
    mwlog.setup()
    from musicwell.paths import install_error_log
    install_error_log()
    fix_certificates()
    _pick_audio_backend()
    from musicwell.system import windows_setup
    windows_setup()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_ID)
    if os.environ.get("SNAP_NAME"):
        app.setDesktopFileName(f"{os.environ['SNAP_NAME']}_{APP_ID}")  # the menu entry snapd made
    elif sys.platform.startswith("linux"):
        from musicwell import menuentry
        menuentry.keep_up_to_date()
        # Without a desktop file the portal logs "App info not found".
        if menuentry.known_to_desktop():
            app.setDesktopFileName(APP_ID)
    app.setStyle("Fusion")
    mwlog.qt_messages()
    icon = Path(__file__).parent / ("icon.ico" if sys.platform == "win32" else "icon.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    from musicwell.mainwindow import MainWindow
    win = MainWindow()
    app.aboutToQuit.connect(win.save_and_stop)  # e.g. logging out with the window open
    app.aboutToQuit.connect(mwlog.stopped)
    QTimer.singleShot(1500, lambda: mwlog.started(win))
    if not win.starts_hidden():
        win.show()

    folders = [a for a in sys.argv[1:] if os.path.isdir(a)]
    for f in folders:  # `musicwell ~/Music` adds a folder
        win.library.add_folder(f)
    code = app.exec()
    # Everything is saved in closeEvent. Exit now instead of letting Python tear down Qt objects while background threads still run.
    for stream in (sys.stdout, sys.stderr):  # None under pythonw on Windows
        if stream is not None:
            stream.flush()
    os._exit(code)
