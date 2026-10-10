#!/usr/bin/env bash
# Bring new commits from the two old repositories into this one, until they are archived.
#
# Each old main is cloned fresh and rewritten into its subdirectory with git filter-repo, the same way as the first
# import. The rewrite is deterministic, so commits that were imported before get the same hashes again and the merge
# only adds what is new. Needs `pip install git-filter-repo`. Run on a clean checkout of main; it makes merge commits,
# it pushes nothing.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
if [ -n "$(git status --porcelain)" ]; then echo "commit or stash your changes first" >&2; exit 1; fi
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

import() { # <github repo> <subdirectory> <tag prefix>
  git clone --quiet --single-branch --branch main "https://github.com/$1" "$work/$2"
  (cd "$work/$2" && git filter-repo --quiet --force --to-subdirectory-filter "$2" --tag-rename "":"$3")
  git fetch --quiet "$work/$2" HEAD
  git merge --no-edit -m "Import new $1 commits into $2/" FETCH_HEAD
}

import Joost-Jansen/health-tracker health-tracker health-
import Joost-Jansen/stock-tracker wealth-tracker wealth-
