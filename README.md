# GitSpyX - Advanced GitHub Intelligence Tool

```
     ██████╗ ██╗████████╗███████╗██████╗ ██╗   ██╗██╗  ██╗
    ██╔════╝ ██║╚══██╔══╝██╔════╝██╔══██╗╚██╗ ██╔╝╚██╗██╔╝
    ██║  ███╗██║   ██║   ███████╗██████╔╝ ╚████╔╝  ╚███╔╝ 
    ██║   ██║██║   ██║   ╚════██║██╔═══╝   ╚██╔╝   ██╔██╗ 
    ╚██████╔╝██║   ██║   ███████║██║        ██║   ██╔╝ ██╗
     ╚═════╝ ╚═╝   ╚═╝   ╚══════╝╚═╝        ╚═╝   ╚═╝  ╚═╝
```

<div align="center">

**An advanced, open-source intelligence (OSINT) tool designed for GitHub reconnaissance.**

[![Python](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-cross--platform-lightgrey.svg)](#requirements)
[![Version](https://img.shields.io/badge/version-2.3.0-brightgreen.svg)](#overview)
[![Status](https://img.shields.io/badge/status-stable-success.svg)](#overview)
[![Maintained](https://img.shields.io/badge/maintained-yes-green.svg)](#contributing)
[![Stars](https://img.shields.io/github/stars/VritraSecz/GitSpyX?style=social)](https://github.com/VritraSecz/GitSpyX)
[![Forks](https://img.shields.io/github/forks/VritraSecz/GitSpyX?style=social)](https://github.com/VritraSecz/GitSpyX)
[![Issues](https://img.shields.io/github/issues/VritraSecz/GitSpyX)](https://github.com/VritraSecz/GitSpyX/issues)
[![Contributors](https://img.shields.io/github/contributors/VritraSecz/GitSpyX)](https://github.com/VritraSecz/GitSpyX/graphs/contributors)
[![Languages](https://img.shields.io/github/languages/count/VritraSecz/GitSpyX)](https://github.com/VritraSecz/GitSpyX)
[![Code Size](https://img.shields.io/github/languages/code-size/VritraSecz/GitSpyX)](https://github.com/VritraSecz/GitSpyX)

</div>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Usage](#-usage)
- [Screenshots](#️-screenshots)
- [Project Structure](#-project-structure)
- [Contributing](#-contributing)
- [Developer](#-developer)
- [License](#-license)


## 🔮 Overview

**GitSpyX** is an advanced, open-source intelligence (OSINT) tool designed for GitHub reconnaissance. It allows security researchers, developers, and enthusiasts to gather detailed information about GitHub users, organizations, and repositories. From user profiles and repository details to organization memberships and contribution patterns, GitSpyX provides a comprehensive intelligence overview in a clean, user-friendly format. Whether you're conducting security assessments or just curious about GitHub projects, GitSpyX is your go-to spyglass.

### Key Highlights

- 🕵️ **Comprehensive intelligence**: Users, public repos, single-repo details, user search, and organizations.
- 💻 **CLI + Rich**: Colored tables, optional progress mode, and readable UTC timestamps in the terminal.
- 💾 **JSON export**: Raw GitHub API-shaped data under `output-gitspyx/` for pipelines and reports.
- 🐍 **Stack**: Python 3, `requests`, and `rich`.

## ✨ Features

### Core Functionality
- **User profile**: Public fields from `GET /users/{username}` (including **Profile updated** = account metadata `updated_at`).
- **User repositories**: Paginated public repos (`GET /users/{username}/repos`) with name, language, stars, forks, and URL.
- **Repository investigation**: Full repo object via `GET /repos/{owner}/{repo}` — license, topics, forks, issues, homepage, etc.
- **Search users**: `GET /search/users` with your query string.
- **Organization**: Public org details from `GET /orgs/{org}`.
- **JSON export**: Successful runs write timestamped files under `output-gitspyx/` (raw API JSON for scripting; see below).

### Accurate GitHub metrics (v2.3+)
- **Watchers** in repo details uses **`subscribers_count`** (people watching for notifications). GitHub’s REST **`watchers_count`** on repositories often matches **stars**, not true watchers.
- **Last push** shows **`pushed_at`** (last git push). **Repo activity (issues/stars, etc.)** shows **`updated_at`**, which changes on many non-push events.
- **Homepage** is shown as the plain URL from the API when set; empty values show as `N/A`.

### User experience
- **Human-readable dates** in tables (e.g. `28 July 2025 at 00:45:21 UTC`); saved JSON still uses GitHub’s ISO-8601 strings.
- **HTTP client**: `Accept: application/vnd.github+json`, a proper `User-Agent`, and a **30s** timeout on each request.
- **Rich tables & colors**: Terminal output via [Rich](https://github.com/Textualize/rich).
- **Progress bars**: When using `--no-display` with a username, bulk fetch shows progress.

## 📋 Requirements

### System Requirements
- **Python**: 3.7 or higher (3.9+ recommended)
- **Operating System**: Linux, macOS, or Windows (any OS with Python 3)
- **Internet Connection**: Required for GitHub API access

### Python Dependencies
```bash
rich
requests
```

## 🚀 Installation

### Method 1: PyPI (Recommended)
```bash
# Install from PyPI
pip install gitspyx
```

### Method 2: Git Clone
```bash
# Clone the repository
git clone https://github.com/VritraSecz/GitSpyX.git

# Navigate to project directory
cd GitSpyX

# Install dependencies
pip install -r requirements.txt

# Run the application
python3 gitspyx.py --help
```

## 🎯 Usage

Run the script as `python3 gitspyx.py …` from the project folder, or use the `gitspyx` entry point if you installed from PyPI.

### User investigation
```bash
# Profile only
python3 gitspyx.py -u <username>

# Profile + all public repositories (paginated)
python3 gitspyx.py -u <username> -r

# Deep-dive one repo (must use -u)
python3 gitspyx.py -u <username> -i <repo_name>
```

### Search & organizations
```bash
# Search GitHub users (keep special characters in mind for complex queries)
python3 gitspyx.py -s "search_query"

# Public organization metadata
python3 gitspyx.py -o <organization_name>
```

### JSON output
Whenever the tool collects data, it also writes **`output-gitspyx/<slug>-<DDMMYY-HHMMSS>.json`** (UTC-based timestamp in the filename). The JSON mirrors the GitHub API payloads (unmodified field names and ISO dates).

### Quiet / batch mode
`--no-display` **only** works as:

```bash
python3 gitspyx.py -u <username> --no-display
```

It fetches **profile + all repositories** with a progress bar, **no Rich tables**, and saves JSON. It cannot be combined with `-r`, `-i`, `-s`, `-o`, `--about`, `--connect`, or `-v` (the script will print an error).

### Other commands
```bash
python3 gitspyx.py --about    # Tool description
python3 gitspyx.py --connect  # Author links
python3 gitspyx.py -v         # Version (2.3.0)
python3 gitspyx.py            # Banner + help
```

### Rate limits
Unauthenticated requests use GitHub’s **public** rate limits. For heavier use, consider a personal access token in a future release or wrap calls with your own authenticated client.

## 🖼️ Screenshots

### Main Menu + Output Interface
![main-menu](https://i.ibb.co/9HKnBpZD/Screenshot-From-2025-08-06-03-46-08.png)

## 📁 Project Structure

```
GitSpyX/
├── gitspyx.py          # Main script
├── requirements.txt    # Dependencies
├── README.md           # Documentation
└── LICENSE             # MIT License
```

### File Descriptions


- **`gitspyx.py`**: Main application script containing all the core functionality

- **`requirements.txt`**: Lists all Python dependencies required by the project
- **`README.md`**: Comprehensive documentation and usage guide
- **`LICENSE`**: MIT license file


## 🤝 Contributing

We welcome contributions from the community! Here's how you can help:

### Ways to Contribute
- 🐛 **Bug Reports**: Submit detailed issue reports.
- 💡 **Feature Requests**: Suggest new functionality.
- 🔧 **Code Contributions**: Submit pull requests.
- 📚 **Documentation**: Improve documentation and examples.

### Development Setup
```bash
# Fork the repository on GitHub
# Clone your fork
git clone https://github.com/yourusername/GitSpyX.git

# Create a feature branch
git checkout -b feature/your-feature-name

# Make changes and test thoroughly
# Commit with descriptive messages
git commit -m "Add: new feature description"

# Push to your fork and create pull request
git push origin feature/your-feature-name
```


## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

```
MIT License

Copyright (c) 2025 Alex Butler (Vritra Security Organization)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```


## 👨‍💻 Developer

<div align="center">

### Alex Butler
**Vritra Security Organization**

[![GitHub](https://img.shields.io/badge/GitHub-VritraSecz-181717?style=for-the-badge&logo=github)](https://github.com/VritraSecz)
[![Website](https://img.shields.io/badge/Website-vritrasec.com-FF6B6B?style=for-the-badge&logo=firefox)](https://vritrasec.com)
[![Instagram](https://img.shields.io/badge/Instagram-haxorlex-E4405F?style=for-the-badge&logo=instagram)](https://instagram.com/haxorlex)
[![YouTube](https://img.shields.io/badge/YouTube-Technolex-FF0000?style=for-the-badge&logo=youtube)](https://youtube.com/@Technolex)

### 📱 Telegram Channels
[![Central](https://img.shields.io/badge/Central-LinkCentralX-0088CC?style=for-the-badge&logo=telegram)](https://t.me/LinkCentralX)
[![Main Channel](https://img.shields.io/badge/Main-VritraSec-0088CC?style=for-the-badge&logo=telegram)](https://t.me/VritraSec)
[![Community](https://img.shields.io/badge/Community-VritraSecz-0088CC?style=for-the-badge&logo=telegram)](https://t.me/VritraSecz)
[![Support Bot](https://img.shields.io/badge/Support-ethicxbot-0088CC?style=for-the-badge&logo=telegram)](https://t.me/ethicxbot)

</div>

---

<div align="center">

### 🌟 Support the Project

If you find GitSpyX helpful, please consider:
- ⭐ Starring the repository
- 🍴 Forking and contributing
- 📢 Sharing with others
- 🐛 Reporting issues
- 💡 Suggesting new features

**Made with ❤️ by the Vritra Security Organization**

</div>



