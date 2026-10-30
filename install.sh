#!/bin/bash
set -e

# Get the absolute path to the project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🚀 Installing Transcripe..."

# ── 0. Install system dependencies (best-effort, per platform) ──────────────
# Needed binaries: ffmpeg (media), libreoffice (docs→pdf), poppler (pdf→images),
# pandoc (doc formats — can also self-download), tk (native file browser),
# unrar/unar (RAR archive extraction).
install_system_deps() {
    if command -v apt-get >/dev/null 2>&1; then
        echo "🐧 Debian/Ubuntu detected — installing system dependencies (sudo)..."
        # One broken third-party repo fails `apt-get update`; under set -e that
        # used to end the install here, before the `transcripe` command was
        # ever created — leaving zsh to cd into the folder of that name instead.
        sudo apt-get update -qq || true
        sudo apt-get install -y ffmpeg libreoffice poppler-utils pandoc python3-tk unar nodejs npm \
            tesseract-ocr tesseract-ocr-ara tesseract-ocr-tur || true
    elif command -v dnf >/dev/null 2>&1; then
        echo "🐧 Fedora detected — installing system dependencies (sudo)..."
        sudo dnf install -y ffmpeg libreoffice poppler-utils pandoc python3-tkinter unar nodejs npm \
            tesseract tesseract-langpack-ara tesseract-langpack-tur || true
    elif command -v pacman >/dev/null 2>&1; then
        echo "🐧 Arch detected — installing system dependencies (sudo)..."
        sudo pacman -Sy --noconfirm ffmpeg libreoffice-fresh poppler pandoc tk unarchiver nodejs npm \
            tesseract tesseract-data-ara tesseract-data-tur tesseract-data-eng || true
    elif command -v brew >/dev/null 2>&1; then
        echo "🍏 macOS (Homebrew) detected — installing system dependencies..."
        brew install ffmpeg poppler pandoc python-tk unar node tesseract tesseract-lang || true
        brew install --cask libreoffice || true
    else
        echo "⚠️  Could not detect a package manager."
        echo "   Please install manually: ffmpeg, libreoffice, poppler, pandoc, tk, unar/unrar, nodejs."
    fi
}
install_system_deps

# ── 1. Ensure virtual environment exists ────────────────────────────────────
# Adopt an existing .venv rather than creating a second environment beside it.
if [ -d "$PROJECT_DIR/.venv" ]; then
    VENV="$PROJECT_DIR/.venv"
elif [ -d "$PROJECT_DIR/venv" ]; then
    VENV="$PROJECT_DIR/venv"
else
    echo "📦 Creating virtual environment..."
    python3 -m venv "$PROJECT_DIR/.venv"
    VENV="$PROJECT_DIR/.venv"
fi

# ── 2. Install Python requirements ──────────────────────────────────────────
echo "📥 Installing Python dependencies (this might take a minute)..."
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$PROJECT_DIR/requirements.txt"
"$VENV/bin/pip" install -q -e "$PROJECT_DIR"

# ── 3. Create the executable wrapper in ~/.local/bin ────────────────────────
mkdir -p "$HOME/.local/bin"
BIN_PATH="$HOME/.local/bin/transcripe"

# Unquoted heredoc expands $PROJECT_DIR now; \$@ stays literal (portable, no sed).
# The console script comes from the editable install (src layout). The wrapper
# re-resolves the venv at run time so renaming venv → .venv can't strand it.
cat > "$BIN_PATH" <<EOF
#!/bin/bash
for v in "$PROJECT_DIR/.venv" "$PROJECT_DIR/venv"; do
    [ -x "\$v/bin/transcripe" ] && exec "\$v/bin/transcripe" "\$@"
done
echo "transcripe: no virtualenv found in $PROJECT_DIR — re-run install.sh" >&2
exit 1
EOF
chmod +x "$BIN_PATH"

echo ""
echo "✅ Installation complete!"
echo "🎉 Run it from anywhere by typing: transcripe"
echo "   Browser + phone studio:  transcripe studio"
echo "   If 'transcripe' is not found, add ~/.local/bin to your PATH:"
echo "     export PATH=\"\$HOME/.local/bin:\$PATH\""
