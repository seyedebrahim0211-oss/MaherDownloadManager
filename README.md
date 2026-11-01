# Maher Download Manager 2.1

Bilingual (Persian/English) Windows download manager with Iranian-inspired tile motifs, four selectable palettes, queue management, segmented HTTP(S) downloads, FTP and opt-in browser integration.

## In-app automatic updates
The application checks the configured repository's **GitHub Releases/latest** at most once per 24 hours (configurable checkbox). It can automatically download and validate an installer against a published SHA-256 checksum. An update is installed **only after the user clicks Install update and confirms**. This avoids interrupting active downloads without permission. It uses per-user Inno Setup installs; unsigned binaries may trigger Windows SmartScreen warnings. SHA-256 is not a substitute for code signing.

## Build on GitHub Actions
Upload all repository files including `.github/workflows/main.yml`, open Actions, choose **Windows Installer - Build and Release**, then Run workflow. Once the job passes, download the installer in Artifacts. To publish a release, tag the exact matching version (e.g. `v2.1.0`); the workflow attaches the installer and the checksum file.

## Local development
Install Python 3.12, `pip install -r requirements.txt`, run `python app.py`. Build with `BUILD-EXE-WINDOWS.bat` on Windows. For Windows installer, use the GitHub Actions workflow, which invokes Inno Setup.

## UI
Settings → App language → English or فارسی. Settings → Iranian theme → Turquoise Night, Lapis & Gold, Ruby Termeh or Persian Manuscript. All settings persist across sessions, independently from existing job categories.

## Scope
Public/non-DRM media supported via yt-dlp/FFmpeg, subject to site availability and rights. No DRM circumvention. Automatic browser capture requires the extension and permission.

## Testing
13 offline tests plus virtual-display GUI smoke tests. EXE installation and full media integration on Windows remain to be tested in a real Windows runner.
