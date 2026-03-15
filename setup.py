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
        "CFBundleIconFile": "AppIcon",
        "LSUIElement": True,
        "NSSupportsAutomaticTermination": False,
        "NSSupportsSuddenTermination": False,
        "NSMicrophoneUsageDescription": "Voxbar needs microphone access for voice dictation.",
    },
    "iconfile": "Voxbar.app/Contents/Resources/AppIcon.icns",
    "packages": ["objc", "AppKit", "Foundation", "WebKit", "Quartz"],
    "excludes": ["unittest", "test"],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
