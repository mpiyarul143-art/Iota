# Authored By Iota Coders © 2025
import asyncio
import shlex
from typing import Tuple

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError

import config

from ..logging import LOGGER


def install_req(cmd: str) -> Tuple[str, str, int, int]:
    async def install_requirements():
        args = shlex.split(cmd)
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return (
            stdout.decode("utf-8", "replace").strip(),
            stderr.decode("utf-8", "replace").strip(),
            process.returncode,
            process.pid,
        )

    return asyncio.get_event_loop().run_until_complete(install_requirements())


def git():
    """Best-effort self-update from the upstream repo. Never fatal: the bot
    must keep running even when there is no git repo, no network, or the
    upstream remote does not exist yet."""
    try:
        REPO_LINK = config.UPSTREAM_REPO
        if config.GIT_TOKEN:
            GIT_USERNAME = REPO_LINK.split("com/")[1].split("/")[0]
            TEMP_REPO = REPO_LINK.split("https://")[1]
            UPSTREAM_REPO = f"https://{GIT_USERNAME}:{config.GIT_TOKEN}@{TEMP_REPO}"
        else:
            UPSTREAM_REPO = config.UPSTREAM_REPO
        try:
            repo = Repo()
            LOGGER(__name__).info(f"Git Client Found [VPS DEPLOYER]")
        except (GitCommandError, InvalidGitRepositoryError):
            # Not a git repo (e.g. deployed as a subfolder) – skip self-update.
            LOGGER(__name__).info("No git repository found – skipping self-update.")
            return
        if "origin" not in repo.remotes:
            repo.create_remote("origin", UPSTREAM_REPO)
        origin = repo.remote("origin")
        origin.fetch()
        if config.UPSTREAM_BRANCH not in repo.heads:
            repo.create_head(
                config.UPSTREAM_BRANCH,
                origin.refs[config.UPSTREAM_BRANCH],
            )
        repo.heads[config.UPSTREAM_BRANCH].set_tracking_branch(
            origin.refs[config.UPSTREAM_BRANCH]
        )
        repo.heads[config.UPSTREAM_BRANCH].checkout(True)
        try:
            origin.pull(config.UPSTREAM_BRANCH)
        except GitCommandError:
            repo.git.reset("--hard", "FETCH_HEAD")
        install_req("pip3 install --no-cache-dir -r requirements.txt")
        LOGGER(__name__).info(f"Fetching updates from upstream repository...")
    except Exception as exc:
        LOGGER(__name__).warning(f"Self-update skipped: {type(exc).__name__}: {exc}")
