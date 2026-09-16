#!/usr/bin/env python3
"""Publish the Home Assistant add-on repository without `git push`.

The script validates the local add-on, builds a local repository archive,
then optionally creates one GitHub commit by using the Git Data API.

Required to publish:
  GITHUB_TOKEN or GH_TOKEN with contents:write access to the repository.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "home_control"
DIST = ROOT / "dist"

SOURCE_FILES = [
    ".gitignore",
    "README.md",
    "repository.yaml",
    "home_control/CHANGELOG.md",
    "home_control/Dockerfile",
    "home_control/README.md",
    "home_control/config.yaml",
    "home_control/run.sh",
    "home_control/server.py",
    "home_control/www/index.html",
    "scripts/publish_to_github.py",
]


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def addon_version() -> str:
    config = read_text(ADDON / "config.yaml")
    match = re.search(r'^version:\s*"([^"]+)"\s*$', config, re.MULTILINE)
    if not match:
        fail("Could not find version in home_control/config.yaml")
    return match.group(1)


def validate_sources(skip_js: bool) -> str:
    for source in SOURCE_FILES:
        path = ROOT / source
        if not path.exists():
            fail(f"Required source file is missing: {source}")

    version = addon_version()
    html = read_text(ADDON / "www" / "index.html")
    changelog = read_text(ADDON / "CHANGELOG.md")

    if f"Home Control - {version}" in html:
        fail("Unexpected hyphenated version label; expected bullet label")

    if f"Home Control • {version}" not in html:
        fail(f"index.html does not show Home Control • {version}")

    if f"## {version}" not in changelog:
        fail(f"CHANGELOG.md is missing ## {version}")

    with tempfile.TemporaryDirectory() as pycache:
        py_compile.compile(
            str(ADDON / "server.py"),
            cfile=str(Path(pycache) / "server.pyc"),
            doraise=True,
        )

    if not skip_js:
        node = os.environ.get("NODE_BINARY") or shutil.which("node")
        if node:
            script = (
                "const fs=require('fs');"
                "const html=fs.readFileSync('home_control/www/index.html','utf8');"
                "const scripts=[...html.matchAll(/<script>([\\s\\S]*?)<\\/script>/g)]"
                ".map(m=>m[1]).join('\\n');"
                "new Function(scripts);"
            )
            subprocess.run(
                [node, "-e", script],
                cwd=ROOT,
                check=True,
            )
        else:
            print("WARN: node was not found; skipping JavaScript syntax check")

    return version


def build_archive(version: str) -> Path:
    DIST.mkdir(exist_ok=True)
    archive = DIST / f"home-assistant-home-control-local-repository-{version}.tar.gz"

    with tarfile.open(archive, "w:gz") as tar:
        for source in ("README.md", "repository.yaml", "home_control"):
            tar.add(ROOT / source, arcname=source)

    print(f"Built {archive}")
    return archive


class GitHub:
    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.base = f"https://api.github.com/repos/{repo}"

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        if body is not None:
            data = json.dumps(body).encode("utf-8")

        request = Request(
            self.base + path,
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            fail(f"GitHub API {method} {path} failed: {error.code} {detail}")

        if not raw:
            return {}

        return json.loads(raw)


def git_file_mode(path: str) -> str:
    if path == "home_control/run.sh":
        return "100755"
    if path == "scripts/publish_to_github.py":
        return "100755"
    return "100644"


def publish(repo: str, branch: str, message: str) -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        fail("Set GITHUB_TOKEN or GH_TOKEN before publishing")

    github = GitHub(token=token, repo=repo)
    ref_path = f"/git/ref/heads/{quote(branch, safe='')}"
    ref = github.request("GET", ref_path)
    head_sha = ref["object"]["sha"]
    head_commit = github.request("GET", f"/git/commits/{head_sha}")
    base_tree = head_commit["tree"]["sha"]

    tree_entries = []

    for source in SOURCE_FILES:
        content = (ROOT / source).read_bytes()
        blob = github.request(
            "POST",
            "/git/blobs",
            {
                "content": base64.b64encode(content).decode("ascii"),
                "encoding": "base64",
            },
        )
        tree_entries.append({
            "path": source,
            "mode": git_file_mode(source),
            "type": "blob",
            "sha": blob["sha"],
        })

    tree = github.request(
        "POST",
        "/git/trees",
        {
            "base_tree": base_tree,
            "tree": tree_entries,
        },
    )

    commit = github.request(
        "POST",
        "/git/commits",
        {
            "message": message,
            "tree": tree["sha"],
            "parents": [head_sha],
        },
    )

    github.request(
        "PATCH",
        ref_path,
        {
            "sha": commit["sha"],
            "force": False,
        },
    )

    return commit["sha"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate, package, and publish Home Control to GitHub.",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get(
            "HA_REPOSITORY",
            "dwaynejcrawford/home-assistant-home-control",
        ),
        help="GitHub repository in owner/name form.",
    )
    parser.add_argument(
        "--branch",
        default=os.environ.get("GITHUB_BRANCH", "main"),
        help="Branch to update.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Create the GitHub commit. Without this flag, only validate and package.",
    )
    parser.add_argument(
        "--message",
        help="Commit message to use when publishing.",
    )
    parser.add_argument(
        "--skip-js",
        action="store_true",
        help="Skip JavaScript syntax validation.",
    )
    parser.add_argument(
        "--no-package",
        action="store_true",
        help="Skip building the local repository archive.",
    )

    args = parser.parse_args()

    version = validate_sources(skip_js=args.skip_js)
    print(f"Validated Home Control {version}")

    if not args.no_package:
        build_archive(version)

    if not args.publish:
        print("Dry run complete. Add --publish to update GitHub.")
        return

    message = args.message or f"Publish Home Control {version}"
    commit_sha = publish(
        repo=args.repo,
        branch=args.branch,
        message=message,
    )
    print(f"Published {args.repo}@{args.branch}: {commit_sha}")


if __name__ == "__main__":
    main()
