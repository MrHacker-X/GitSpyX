#!/usr/bin/env python3

"""
- Project GitSpyX: Fetches GitHub user data and lists public repositories using the GitHub API
- Author: Alex Butler [Vritra Security Organization]
- Version: 2.3.0
"""

import argparse
import requests
import json
import os
from datetime import datetime, timezone
from time import sleep
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress

console = Console()

GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "GitSpyX/2.3 (OSINT; VritraSecz)",
}


def _format_github_datetime(iso_str):
    """
    Format GitHub API timestamps (e.g. 2025-07-28T00:45:21Z) for display.
    Output is UTC, human-readable: '28 July 2025 at 00:45:21 UTC'.
    """
    if iso_str is None:
        return "N/A"
    s = str(iso_str).strip()
    if not s or s.upper() == "N/A":
        return "N/A"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
    except (ValueError, TypeError, OSError):
        return s
    return dt.strftime("%d %B %Y at %H:%M:%S UTC")


def print_banner():
    banner = r"""
     ██████╗ ██╗████████╗███████╗██████╗ ██╗   ██╗██╗  ██╗
    ██╔════╝ ██║╚══██╔══╝██╔════╝██╔══██╗╚██╗ ██╔╝╚██╗██╔╝
    ██║  ███╗██║   ██║   ███████╗██████╔╝ ╚████╔╝  ╚███╔╝ 
    ██║   ██║██║   ██║   ╚════██║██╔═══╝   ╚██╔╝   ██╔██╗ 
    ╚██████╔╝██║   ██║   ███████║██║        ██║   ██╔╝ ██╗
     ╚═════╝ ╚═╝   ╚═╝   ╚══════╝╚═╝        ╚═╝   ╚═╝  ╚═╝    """
    console.print(Text(banner, style="bold #4A90E2"))
    console.print("\nGitSpyX - Advanced GitHub Intelligence Tool", style="bold #F5A623")
    console.print("Developed by VritraSecz | Vritra Security Organization", style="bold #BD10E0")
    console.print("-" * 70, style="bold #4A90E2")

def get_github_data(url):
    try:
        response = requests.get(url, headers=GITHUB_HEADERS, timeout=30)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as errh:
        console.print(f"[bold red]Http Error:[/bold red] {errh}")
    except requests.exceptions.ConnectionError as errc:
        console.print(f"[bold red]Error Connecting:[/bold red] {errc}")
    except requests.exceptions.Timeout as errt:
        console.print(f"[bold red]Timeout Error:[/bold red] {errt}")
    except requests.exceptions.RequestException as err:
        console.print(f"[bold red]Oops: Something Else[/bold red] {err}")
    return None

def display_user_profile(username, progress=None):
    """Fetches and displays a GitHub user's profile."""
    if progress:
        task = progress.add_task("[#F5A623]Fetching profile...", total=1)
    profile_data = get_github_data(f"https://api.github.com/users/{username}")
    if progress:
        progress.update(task, advance=1)

    if not profile_data:
        console.print(f"[bold red]User profile not found for '{username}'.[/bold red]")
        return None

    if not progress:
        table = Table(title=f"Profile Details for {username}", show_header=True, header_style="bold #4A90E2")
        table.add_column("Field", style="#F5A623", width=22)
        table.add_column("Value", style="bold #7ED321")

        table.add_row("• Name", profile_data.get('name', 'N/A'))
        table.add_row("• Username", f"@{profile_data.get('login', 'N/A')}")
        table.add_row("• Bio", profile_data.get('bio', 'N/A'))
        table.add_row("• Company", profile_data.get('company', 'N/A'))
        table.add_row("• Location", profile_data.get('location', 'N/A'))
        table.add_row("• Public Repos", str(profile_data.get('public_repos', 0)))
        table.add_row("• Followers", str(profile_data.get('followers', 0)))
        table.add_row("• Following", str(profile_data.get('following', 0)))
        table.add_row("• ID", str(profile_data.get('id', 'N/A')))
        table.add_row("• Type", profile_data.get('type', 'N/A'))
        table.add_row("• Public Gists", str(profile_data.get('public_gists', 0)))
        table.add_row("• Blog", profile_data.get('blog', 'N/A'))
        table.add_row("• Email", profile_data.get('email', 'N/A'))
        table.add_row("• Twitter", f"@{profile_data.get('twitter_username', 'N/A')}" if profile_data.get('twitter_username') else 'N/A')
        table.add_row("• Hireable", "Yes" if profile_data.get('hireable') else "No")
        table.add_row("• Avatar URL", profile_data.get('avatar_url', 'N/A'))
        table.add_row("• Created At", _format_github_datetime(profile_data.get("created_at")))
        table.add_row("• Profile updated", _format_github_datetime(profile_data.get("updated_at")))

        console.print(table)
    return profile_data

def display_user_repositories(username, progress=None, profile_data=None):
    """Fetches and displays a user's repositories."""
    repos_url = f"https://api.github.com/users/{username}/repos"
    repos = []
    
    total_pages = None
    if progress and profile_data and 'public_repos' in profile_data:
        total_repos = profile_data['public_repos']
        total_pages = (total_repos + 99) // 100 if total_repos > 0 else 0

    if progress:
        task = progress.add_task("[#4A90E2]Fetching repositories...", total=total_pages)

    if not (progress and total_pages == 0):
        page = 1
        while True:
            data = get_github_data(f"{repos_url}?page={page}&per_page=100")
            if progress:
                progress.update(task, advance=1)
            if not data:
                break
            repos.extend(data)
            if len(data) < 100:
                break
            page += 1
    
    if progress and total_pages is None:
        progress.update(task, completed=True)

    if not repos:
        if not progress:
            console.print(f"[bold yellow]No public repositories found for {username}.[/bold yellow]")
        return None

    if not progress:
        table = Table(title=f"Repositories for {username}", show_header=True, header_style="bold #4A90E2")
        table.add_column("Name", style="bold #F5A623")
        table.add_column("Language", style="#BD10E0")
        table.add_column("Stars", style="#7ED321")
        table.add_column("Forks", style="#7ED321")
        table.add_column("URL")

        for repo in repos:
            table.add_row(
                repo['name'],
                repo.get('language', 'N/A'),
                str(repo.get('stargazers_count', 0)),
                str(repo.get('forks_count', 0)),
                repo['html_url']
            )
        console.print(table)
    return repos

def display_repo_details(username, repo_name, no_display=False):
    """Fetches and displays details for a specific repository."""
    if no_display:
        console.print(f"Fetching details for repo: {repo_name}")
    repo_data = get_github_data(f"https://api.github.com/repos/{username}/{repo_name}")
    if not repo_data:
        if not no_display:
            console.print(f"[bold red]Repository '{repo_name}' not found for user '{username}'.[/bold red]")
        return None

    if not no_display:
        table = Table(title=f"Repository Details: {repo_name}", show_header=True, header_style="bold #4A90E2")
        table.add_column("Field", style="#F5A623", width=22)
        table.add_column("Value", style="bold #7ED321")

        table.add_row("• Name", repo_data.get('name', 'N/A'))
        table.add_row("• Full Name", repo_data.get('full_name', 'N/A'))
        table.add_row("• Description", repo_data.get('description', 'N/A'))
        table.add_row("• URL", repo_data.get('html_url', 'N/A'))
        hp = repo_data.get("homepage")
        homepage_val = hp.strip() if isinstance(hp, str) and hp.strip() else "N/A"
        table.add_row("• Homepage", homepage_val)
        table.add_row("• Language", repo_data.get('language', 'N/A'))
        table.add_row("• Default Branch", repo_data.get('default_branch', 'N/A'))
        table.add_row("• Size (KB)", str(repo_data.get('size', 'N/A')))
        table.add_row("• Stars", str(repo_data.get('stargazers_count', 0)))
        subs = repo_data.get("subscribers_count")
        table.add_row("• Watchers", str(subs if subs is not None else 0))
        table.add_row("• Forks", str(repo_data.get('forks_count', 0)))
        table.add_row("• Open Issues", str(repo_data.get('open_issues_count', 0)))
        license_info = repo_data.get('license')
        table.add_row("• License", license_info['name'] if license_info else 'N/A')
        table.add_row("• Topics", ", ".join(repo_data.get('topics', [])))
        table.add_row("• Created At", _format_github_datetime(repo_data.get("created_at")))
        table.add_row("• Last push", _format_github_datetime(repo_data.get("pushed_at")))
        table.add_row(
            "• Repo activity (issues/stars, etc.)",
            _format_github_datetime(repo_data.get("updated_at")),
        )
        table.add_row("• Is Fork", "Yes" if repo_data.get('fork') else "No")
        if repo_data.get('fork'):
            parent_repo = repo_data.get('parent', {})
            table.add_row("• Parent Repo", parent_repo.get('full_name', 'N/A'))
        table.add_row("• Archived", "Yes" if repo_data.get('archived') else "No")

        console.print(table)
    return repo_data

def search_users(query, no_display=False):
    """Searches for users on GitHub."""
    if no_display:
        console.print(f"Searching for users: {query}")
    search_data = get_github_data(f"https://api.github.com/search/users?q={query}")
    if not search_data or not search_data.get('items'):
        if not no_display:
            console.print(f"[bold red]No users found for query '{query}'.[/bold red]")
        return None

    if not no_display:
        table = Table(title=f"Search Results for '{query}'", show_header=True, header_style="bold #4A90E2")
        table.add_column("Username", style="bold #F5A623")
        table.add_column("ID", style="#7ED321")
        table.add_column("Profile URL")

        for user in search_data['items']:
            table.add_row(user['login'], str(user['id']), user['html_url'])

        console.print(table)
    return search_data

def get_org_details(org_name, no_display=False):
    """Fetches and displays details for a GitHub organization."""
    if no_display:
        console.print(f"Fetching details for organization: {org_name}")
    org_data = get_github_data(f"https://api.github.com/orgs/{org_name}")
    if not org_data:
        if not no_display:
            console.print(f"[bold red]Organization not found: '{org_name}'.[/bold red]")
        return None

    if not no_display:
        table = Table(title=f"Organization Details for {org_name}", show_header=True, header_style="bold #4A90E2")
        table.add_column("Field", style="#F5A623", width=22)
        table.add_column("Value", style="bold #7ED321")

        table.add_row("• Name", org_data.get('name', 'N/A'))
        table.add_row("• Description", org_data.get('description', 'N/A'))
        table.add_row("• Location", org_data.get('location', 'N/A'))
        table.add_row("• Public Repos", str(org_data.get('public_repos', 0)))
        table.add_row("• Followers", str(org_data.get('followers', 0)))
        table.add_row("• Blog", org_data.get('blog', 'N/A'))
        table.add_row("• Email", org_data.get('email', 'N/A'))
        table.add_row("• Created At", _format_github_datetime(org_data.get("created_at")))

        console.print(table)
    return org_data

def save_to_json(data, username, no_display=False):
    """Saves data to a JSON file in a dedicated directory."""
    if not data:
        if not no_display:
            console.print("[bold yellow]No data to save.[/bold yellow]")
        return

    output_dir = "output-gitspyx"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
    filename = os.path.join(output_dir, f"{username}-{timestamp}.json")

    try:
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)
        console.print(f"[bold #4A90E2]Data successfully saved to {filename}[/bold #4A90E2]")
    except IOError as e:
        console.print(f"[bold red]Error saving file:[/bold red] {e}")

def show_about():
    about_text = """
    GitSpyX is an advanced, open-source intelligence (OSINT) tool designed for GitHub reconnaissance. 
    It allows security researchers, developers, and enthusiasts to gather detailed information about GitHub users, organizations, and repositories. 
    From user profiles and repository details to organization memberships and contribution patterns, GitSpyX provides a comprehensive intelligence overview in a clean, user-friendly format. 
    Whether you're conducting security assessments or just curious about GitHub projects, GitSpyX is your go-to spyglass.

    This tool is developed and maintained by VritraSec from Vritra Security Organization.
    """
    console.print(Panel(Text(about_text, justify="center"), title="About GitSpyX", border_style="bold #4A90E2"))

def show_connect():
    connect_text = """
    Connect with the developer and support the project:

    GitHub:    https://github.com/VritraSecz
    Instagram: https://instagram.com/vritrasec
    YouTube:   https://youtube.com/@Technolex
    Website:   https://vritrasec.com
    Community: t.me/VritraSecz
    Channel:   t.me/LinkCentralX
    Main:      t.me/VritraSec
    """
    console.print(Panel(Text(connect_text), title="Connect with the Developer", border_style="bold #F5A623"))

def main():
    parser = argparse.ArgumentParser(description="GitSpyX - A GitHub Intelligence Tool", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-u', '--username', help='GitHub username to fetch profile for.')
    parser.add_argument('-r', '--repos', action='store_true', help='Fetch all user repositories.')
    parser.add_argument('-i', '--investigate', help='Investigate a specific repository of the user. Requires -u.')
    parser.add_argument('-s', '--search', help='Search for GitHub users.')
    parser.add_argument('-o', '--org', help='Fetch details for a GitHub organization.')
    parser.add_argument('--about', action='store_true', help='Show information about the tool.')
    parser.add_argument('--connect', action='store_true', help='Show developer social media links.')
    parser.add_argument('-v', '--version', action='store_true', help='Show script version.')
    parser.add_argument('--no-display', action='store_true', help='Suppress detailed output and save all data.')

    args = parser.parse_args()

    # Error handling for incorrect flag combinations
    if args.username and any([args.search, args.org, args.about, args.connect, args.version]):
        console.print("[bold red]Error:[/bold red] The -u/--username flag cannot be combined with -s, -o, --about, --connect, or --version.")
        return

    if args.no_display and not args.username:
        console.print("[bold red]Error:[/bold red] The --no-display flag requires a username (-u).")
        console.print("Usage: gitspyx.py -u <username> --no-display")
        return

    if args.no_display and (args.repos or args.investigate or args.search or args.org or args.about or args.connect or args.version):
        console.print("[bold red]Error:[/bold red] The --no-display flag with -u cannot be combined with other flags.")
        console.print("Usage: gitspyx.py -u <username> --no-display")
        return

    if (args.repos or args.investigate) and not args.username:
        console.print("[bold red]Error:[/bold red] The -r/--repos and -i/--investigate flags require a username (-u).")
        console.print("Usage: gitspyx.py -u <username> -r")
        console.print("       gitspyx.py -u <username> -i <repo_name>")
        return

    # Handle standalone flags
    if args.version:
        console.print("[bold #4A90E2]GitSpyX Version: 2.3.0[/bold #4A90E2]")
        return
    
    if args.about:
        show_about()
        return

    if args.connect:
        show_connect()
        return

    if not any([args.username, args.search, args.org]):
        print_banner()
        parser.print_help()
        return

    if not args.no_display:
        print_banner()

    output_data = {}
    username_for_file = "gitspyx_output"

    if args.username:
        username_for_file = args.username
        if args.no_display:
            with Progress() as progress:
                profile = display_user_profile(args.username, progress=progress)
                if profile:
                    output_data['profile'] = profile
                    repos = display_user_repositories(args.username, progress=progress, profile_data=profile)
                    if repos:
                        output_data['repositories'] = repos
        else:
            if args.investigate:
                repo_details = display_repo_details(args.username, args.investigate)
                if repo_details:
                    output_data['investigated_repo'] = repo_details
            else:
                profile = display_user_profile(args.username)
                if profile:
                    output_data['profile'] = profile
                if args.repos:
                    repos = display_user_repositories(args.username)
                    if repos:
                        output_data['repositories'] = repos

    elif args.search:
        username_for_file = args.search
        results = search_users(args.search, args.no_display)
        if results:
            output_data['search_results'] = results
    elif args.org:
        username_for_file = args.org
        org_details = get_org_details(args.org, args.no_display)
        if org_details:
            output_data['organization'] = org_details

    if output_data:
        save_to_json(output_data, username_for_file, args.no_display)

if __name__ == "__main__":
    main()