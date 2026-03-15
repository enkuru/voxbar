"""Build Voxbar.app — run: python3 setup.py py2app"""

from setuptools import setup

APP = ["voxbar.py"]
DATA_FILES = [("", ["call_ui.html", "config.json"])]

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "Voxbar",
        "CFBundleDisplayName": "Voxbar",
        "CFBundleIdentifier": "com.voxbar.app",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0",
        "LSUIElement": True,  # No dock icon
        "NSMicrophoneUsageDescription": "Voxbar needs microphone access for voice dictation.",
    },
    "packages": ["objc", "AppKit", "Foundation", "WebKit", "Quartz"],
    "includes": [
        "objc",
        "AppKit",
        "Foundation",
        "WebKit",
        "Quartz",
    ],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
