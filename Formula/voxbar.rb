class Voxbar < Formula
  include Language::Python::Virtualenv

  desc "macOS menu bar voice chat app with Fn hotkey for hands-free dictation"
  homepage "https://github.com/enkuru/voxbar"
  url "https://github.com/enkuru/voxbar/archive/refs/tags/v1.0.0.tar.gz"
  sha256 "77902a05bd7c92679d34131c8d7c058bd2b4c3c0d3997933d9207d0a04e5720c"
  license "MIT"

  depends_on "python@3.13"
  depends_on "cliclick"
  depends_on :macos

  def install
    venv = virtualenv_create(libexec, "python3.13")

    # Install pyobjc from PyPI with binary wheels (source builds fail on macOS 26+
    # because CGWindowListCreateImageFromArray is marked unavailable in the SDK)
    system libexec/"bin/pip", "install", "--only-binary", ":all:",
      "pyobjc-core>=10.0",
      "pyobjc-framework-Cocoa>=10.0",
      "pyobjc-framework-Quartz>=10.0",
      "pyobjc-framework-WebKit>=10.0"

    libexec.install "voxbar.py"
    libexec.install "call_ui.html"
    libexec.install "AppIcon.icns"

    etc.install "config.example.json" => "voxbar/config.json"

    (bin/"voxbar").write <<~EOS
      #!/bin/bash
      export VOXBAR_CONFIG="#{etc}/voxbar/config.json"
      cd "#{libexec}"
      exec "#{libexec}/bin/python3" "#{libexec}/voxbar.py" "$@"
    EOS
  end

  service do
    run [opt_libexec/"bin/python3", opt_libexec/"voxbar.py"]
    working_dir opt_libexec
    environment_variables VOXBAR_CONFIG: etc/"voxbar/config.json"
    keep_alive false
    log_path var/"log/voxbar.log"
    error_log_path var/"log/voxbar.err.log"
  end

  def post_install
    (var/"log").mkpath
  end

  def caveats
    <<~EOS
      Voxbar requires Accessibility permissions for the Fn hotkey.
      Grant access in System Settings > Privacy & Security > Accessibility.

      Config: #{etc}/voxbar/config.json

      Start now and auto-start at login:
        brew services start voxbar

      Stop:
        brew services stop voxbar
    EOS
  end

  test do
    system libexec/"bin/python3", "-c",
      "import importlib.util; spec = importlib.util.spec_from_file_location('voxbar', '#{libexec}/voxbar.py'); assert spec is not None"
  end
end
