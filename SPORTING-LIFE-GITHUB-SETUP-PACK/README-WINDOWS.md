# Windows setup — first GitHub sync

The GitHub Actions workflow is proposed in **PR #1** at https://github.com/notdamien2009/horse/pull/1. The main branch is unchanged.

1. Make the GitHub repository **private** before uploading any collected data. GitHub Settings → General → Danger Zone → Change repository visibility.
2. Ensure **Git**, **GitHub CLI (`gh`)** and **Python** are installed. Run `gh auth login` once if not already connected.
3. Extract this ZIP into a new folder and double-click **START_GITHUB_SETUP.bat**.
4. When asked for your SQLite path, press Enter for the screenshot-derived location (`Desktop\Speeds\HORSE-RACING-v2.7-HISTORY-READY\data\racing_history.sqlite`) or paste the actual latest database path.
5. The setup creates a consistent SQLite backup, pushes only Python source onto the existing **feature branch**, and uploads the compressed database into a **private prerelease**. No main-branch changes are made by the script.
6. Review and merge **PR #1** on GitHub after checking the changed files.
7. Use GitHub Actions → **Sporting Life private archive** → **Run workflow** → **verify**. Confirm the race count matches your newest local database before disabling the local job.
8. The workflow's live collection is **off**. Sporting Life's terms expressly restrict automated capture. Do not enable `SL_COLLECTION_ENABLED` until appropriate source permission is established. Once permitted, run **collect**; scheduled runs can subsequently continue the checkpoint.

## Why the repository needs to be private

GitHub's public repositories expose commits, Releases and workflow artifacts to visitors. The existing historical racing source and running comments should not be published there.

## What is not yet done

No GitHub Actions run has executed. No complete 2022–2026 history has been collected. The public repository has only a draft PR containing the disabled workflow and instructions; it does not yet contain the collector source or the local 88-race checkpoint.

## Running continuously

A run processes bounded pages, commits a SQLite checkpoint in private Release storage, and can resume later. A batch limit is **not a permanent limit on how many races can be stored**. GitHub runner limits and source access remain practical constraints. The collector stops and reports errors rather than silently skipping unavailable pages.
