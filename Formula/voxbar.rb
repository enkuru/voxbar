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

  resource "pyobjc-core" do
    url "https://files.pythonhosted.org/packages/b8/b6/d5612eb40be4fd5ef88c259339e6313f46ba67577a95d86c3470b951fce0/pyobjc_core-12.1.tar.gz"
    sha256 "2bb3903f5387f72422145e1466b3ac3f7f0ef2e9960afa9bcd8961c5cbf8bd21"
  end

  resource "pyobjc-framework-Cocoa" do
    url "https://files.pythonhosted.org/packages/02/a3/16ca9a15e77c061a9250afbae2eae26f2e1579eb8ca9462ae2d2c71e1169/pyobjc_framework_cocoa-12.1.tar.gz"
    sha256 "5556c87db95711b985d5efdaaf01c917ddd41d148b1e52a0c66b1a2e2c5c1640"
  end

  resource "pyobjc-framework-Quartz" do
    url "https://files.pythonhosted.org/packages/94/18/cc59f3d4355c9456fc945eae7fe8797003c4da99212dd531ad1b0de8a0c6/pyobjc_framework_quartz-12.1.tar.gz"
    sha256 "27f782f3513ac88ec9b6c82d9767eef95a5cf4175ce88a1e5a65875fee799608"
  end

  resource "pyobjc-framework-WebKit" do
    url "https://files.pythonhosted.org/packages/14/10/110a50e8e6670765d25190ca7f7bfeecc47ec4a8c018cb928f4f82c56e04/pyobjc_framework_webkit-12.1.tar.gz"
    sha256 "97a54dd05ab5266bd4f614e41add517ae62cdd5a30328eabb06792474b37d82a"
  end

  def install
    # pyobjc uses deprecated macOS APIs that error on newer SDKs
    ENV.append "CFLAGS", "-Wno-error=unavailable-declarations"

    venv = virtualenv_create(libexec, "python3.13")
    venv.pip_install resources

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
