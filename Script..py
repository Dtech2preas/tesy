#!/usr/bin/env python3
"""
Universal Codebase Analyzer (GitLab + GitHub + Offline/Local repo)
==================================================================
One script to analyze three kinds of sources:
  1. GitLab   (gitlab.com OR self-hosted)  - via API, no clone needed
  2. GitHub   (github.com OR GitHub Enterprise) - via API
  3. Offline  (repo cloned on local disk) - only git required

Fields that get extracted:
  - Project/Group name
  - Established year, First/Last commit date, Years active, Last activity
  - # of contributors
  - Primary coding language + language breakdown
  - Total LoC (real CODE-line count — comments/blank lines/docstrings
    excluded via the same scanner loc.py uses; sampled+extrapolated over
    the API for GitLab/GitHub, exact for local repos)
  - # of Repos (projects)
  - # of MRs/PRs, # of Merged
  - Avg LoC per MR
  - % Simple fixes / % Standard work / % Rich tasks / % Automated / % Other
  - # of Commits
  - CI/CD analysis (NEW):
      * Whether CI/CD is configured or not
      * Which CI systems (GitLab CI, GitHub Actions, Jenkins, CircleCI,
        Travis, Azure Pipelines, Drone, Buildkite, etc.)
      * CI config files count + jobs/stages (approx)
      * Total pipelines / workflow runs
      * Recent pipeline success rate %
      * Avg pipeline duration (min)
      * Unit test coverage % — GitLab: from pipeline coverage if configured,
        else a real clone + `pytest --cov` run; GitHub: always a real
        clone + `pytest --cov` run (can be skipped with
        --skip-remote-coverage)
  - Test files count, Test cases count (approx) + genuineness check
  - AI/LLM detection (NEW):
      * LLM usage %  — what % of commits/MRs carry an explicit AI signature
      * Which LLM    — Claude Code, GitHub Copilot, Cursor, Aider, Devin,
        ChatGPT/Codex, Gemini/Jules, Sweep, Windsurf/Codeium, OpenHands...
      * Detection sources: commit trailers (Co-Authored-By), commit messages,
        AI bot authors, MR/PR descriptions, code comments, tool config files
        (CLAUDE.md, .cursorrules, copilot-instructions.md, AGENTS.md, etc.)
      * NOTE: only EXPLICIT signatures are detected. If a developer
        copy-pasted AI code and stripped the attribution, it will NOT be
        detected — so this is a LOWER BOUND, not an upper bound.
  - Training-data quality (NEW) — factors for LLM post-training curation:
      * License + risk (permissive/weak-copyleft/copyleft/no-license)
        [heuristic detection — not legal advice]
      * Syntax validity % (Python: exact via ast.parse)
      * Quality metrics: avg/long line %, comment ratio, docstring %,
        avg function length, nesting depth
      * Duplicate files % (normalized content hash)
      * Secrets/PII: AWS/GitHub/OpenAI keys, private keys, hardcoded
        passwords (always MASKED in the report), email count
      * Eval contamination: known HumanEval/MBPP signatures
      * Composite Quality score (0-100) + Training suitability grade (A-D)
  - Quality of SWE (NEW) — heuristic estimate of the engineering team's
      skill/discipline (CI usage, PR review depth, test genuineness,
      function size, comment habits, duplication, secret hygiene), scored
      0-100 with a Weak/Mixed/Solid/Strong label. Built for free from
      fields already computed above — distinct from "Quality score", which
      grades the CODE for LLM-training use, not the people who wrote it.
  - Code availability (public/private/local)

How to create a token:
  GitLab -> Profile -> Preferences -> Access Tokens  (scope: read_api)
  GitHub -> Settings -> Developer settings -> Personal access tokens
            (classic: 'repo' scope for private repos, nothing for public)

Usage:
  # --- GitLab ---
  python repo_analyzer.py --provider gitlab --project "group/repo" --token glpat-XXXX
  python repo_analyzer.py --provider gitlab --group "my-group" --token glpat-XXXX
  python repo_analyzer.py --project "team/app" --token XXXX \\
      --gitlab-url https://gitlab.mycompany.com

  # --- GitHub ---
  python repo_analyzer.py --provider github --project "owner/repo" --token ghp_XXXX
  python repo_analyzer.py --provider github --org "my-org" --token ghp_XXXX

  # --- Many repos (100+) from a text file, one repo per line ---
  #   (blank lines and lines starting with # are ignored)
  python repo_analyzer.py --provider github --project-file repos.txt --token ghp_XXXX

  # --- Offline / Local repo (no internet required) ---
  python repo_analyzer.py --provider local --path /home/user/my-repo
  python repo_analyzer.py --path C:\\code\\repo1 --path C:\\code\\repo2

  # Provider auto-detection also works:
  #   --path given              -> local
  #   token starts with glpat-  -> gitlab
  #   token ghp_/github_        -> github
  #   --org given               -> github,  --group given -> gitlab

Options:
  --max-mrs 0        how many MRs/PRs to fetch (0 = ALL, default)
  --sample-mrs 0     how many MRs/PRs to deep-analyze (0 = all fetched)
  --max-test-files 0   how many test files to check
                       (default 0 = auto: ALL files locally, 200 via API)
  --max-commit-scan 0     how many commits to scan for LLM signatures
                          (default 0 = ALL commits are scanned)
  --max-ai-file-scan 0    how many source files to search for AI-attribution
                          comments (0 = auto: ALL locally, 30 via API)
  LOCAL MODE GUARANTEE: with default settings EVERY code file, EVERY test
  file and EVERY commit of a local repo is scanned — no sampling.
  --workers 8        parallel API requests
  --local-mrs auto   MR detection for local repos:
                       auto   = prefer explicit #N/!N refs (default)
                       strict = ONLY explicit refs (most accurate)
                       merges = also count all merge commits (approx)
                       off    = leave MR fields blank
  --output report.csv

Note: analyzing all MRs on large repos takes time — each MR needs 1-2
extra API calls. Progress is shown, and on rate limits the script waits
and resumes on its own.

Requirements:  pip install requests   (local mode only needs git)
"""

import argparse
import ast
import csv
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import shutil
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

try:
    import requests
    from requests.adapters import HTTPAdapter
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False   # local mode also works without requests

# ---------------------------------------------------------------------------
# Patterns (covers both GitLab and GitHub bots)
# ---------------------------------------------------------------------------

BOT_PATTERNS = [
    r"\bbot\b", r"\[bot\]", r"dependabot", r"renovate", r"gitlab-bot",
    r"group_\d+_bot", r"project_\d+_bot", r"ghost", r"semantic-release",
    r"snyk", r"codecov", r"greenkeeper", r"release-tools", r"-bot$", r"^bot-",
    r"github-actions", r"web-flow", r"mergify", r"kodiak", r"imgbot",
    r"allcontributors", r"pre-commit-ci", r"pyup", r"whitesource", r"mend",
    # AI coding agents that commit/PR via bot accounts
    r"devin-ai-integration", r"sweep-ai", r"copilot-swe-agent",
    r"google-labs-jules", r"cursor-agent", r"openhands-agent",
    r"claude\[bot\]", r"codegen-sh", r"ellipsis-dev", r"coderabbitai",
]

SIMPLE_FIX_TITLE_PATTERNS = [
    r"\btypo\b", r"\bbump\b", r"\bupgrade\b", r"\bupdate dep", r"\blint\b",
    r"\bformat(ting)?\b", r"\bwhitespace\b", r"^chore\b", r"^docs?\b",
    r"^style\b", r"\bconfig\b", r"\breadme\b", r"\bversion\b",
]

ISSUE_LINK_PATTERNS = [
    r"(close[sd]?|fix(e[sd])?|resolve[sd]?|implement[sed]*)\s*:?\s*#\d+",
    r"#\d+",
    r"\b[A-Z][A-Z0-9]{1,9}-\d+\b",           # JIRA style
    r"(issues|merge_requests|pull)/\d+",
]

TEST_FILE_PATTERNS = [
    r"(^|/)test_[^/]*\.py$", r"[^/]*_test\.py$", r"(^|/)tests?\.py$",
    r"\.test\.(js|jsx|ts|tsx|mjs|cjs)$", r"\.spec\.(js|jsx|ts|tsx|rb|php)$",
    r"Tests?\.(java|kt|cs|php|swift|m)$", r"_test\.(go|rb|ex|exs|c|cc|cpp|rs)$",
    r"_spec\.rb$", r"\.feature$", r"(^|/)Test[A-Z][^/]*\.(java|kt|php)$",
    r"IT\.java$", r"Spec\.(scala|kt|groovy)$",
]

# NOTE: "/feature/" and "/unit/" used to be here too — they wrongly flagged
# app source folders (src/feature/login, app/unit/converter) as tests.
# Now only definite test directories. "/testing/" was also removed (ambiguous).
TEST_DIR_HINTS = ("/test/", "/tests/", "/spec/", "/specs/", "/__tests__/",
                  "/src/test/", "/androidtest/", "/cypress/", "/e2e/")

# Support files inside test folders — these are NOT tests (fixtures,
# helpers, config). They must not be counted as test files.
TEST_SUPPORT_PATTERNS = [
    r"(^|/)conftest\.py$", r"(^|/)__init__\.py$", r"(^|/)setup\.py$",
    r"/fixtures?/", r"/__mocks__/", r"/mocks?/", r"/testdata/",
    r"/test_data/", r"/factories/", r"/stubs?/", r"/helpers?/",
    r"(^|/)jest\.(config|setup)\.", r"(^|/)setup[-_]?tests?\.",
    r"(^|/)test[-_]?(utils?|helpers?|setup|config)\.",
]

# --- Test-case declaration patterns (what counts as a test case) ---
# NOTE: "async def test_" is not a separate pattern — "def test_" matches it
# too; keeping it separate counted every async test TWICE (bug fix).
TEST_CASE_PATTERNS = [
    r"\bdef test_\w+",
    r"\b(?:it|test)\s*\(\s*['\"`]", r"\bit\.each\s*\(",
    r"\b(?:it|test)\.todo\s*\(",     # stub/pending tests (without assertions
                                     # the verdict will come out suspicious)
    r"@Test\b", r"@ParameterizedTest\b", r"\bfunc Test[A-Z]\w*",
    r"#\[(?:tokio::)?test\]", r"\bTEST(_F|_P)?\s*\(",
    r"\bscenario\s*['\"(]",
    r"\bpublic function test\w+",              # PHPUnit / Laravel
    r"/\*\*\s*@test\s*\*/", r"#\[Test\]",       # PHPUnit annotations
    r"\btest\s+['\"].+['\"]\s+do\b",            # ruby minitest
]

# --- Assertion patterns (the mark of a genuine test) ---
ASSERTION_PATTERNS = [
    r"\bassert\s+\w", r"\bself\.assert\w+\s*\(", r"\bpytest\.raises\b",
    r"\bexpect\s*\(", r"\bassert\.\w+\s*\(", r"\.should[\.\(]",
    r"\bassert(Equals|True|False|That|NotNull|Null|Same|Throws)\s*\(",
    r"\bverify\s*\(", r"\bt\.(Error|Fatal|Errorf|Fatalf)\b",
    r"\brequire\.\w+\s*\(", r"\bassert_\w+", r"\bmust_\w+",
    r"\$this->assert\w+\s*\(", r"\bAssert::\w+\s*\(",   # PHP
    r"->assert\w+\s*\(", r"\bassertDatabaseHas\b",       # Laravel
    r"\bXCTAssert\w*\s*\(", r"\bEXPECT_\w+\s*\(", r"\bASSERT_\w+\s*\(",
]

# --- Fake/trivial assertions (ones that always pass) ---
TRIVIAL_ASSERTION_PATTERNS = [
    r"assert\s+True\b", r"assert\s+1\b", r"assertTrue\s*\(\s*true\s*\)",
    r"assertTrue\s*\(\s*1\s*\)", r"expect\s*\(\s*true\s*\)\s*\.\s*toBe(Truthy)?\s*\(\s*true?\s*\)",
    r"assertEquals?\s*\(\s*(\d+)\s*,\s*\1\s*\)", r"expect\s*\(\s*(\d+)\s*\)\s*\.\s*toBe\s*\(\s*\1\s*\)",
    r"\$this->assertTrue\s*\(\s*true\s*\)", r"XCTAssertTrue\s*\(\s*true\s*\)",
]

# --- Skipped/disabled tests ---
SKIP_PATTERNS = [
    r"@pytest\.mark\.skip", r"@unittest\.skip", r"\bit\.skip\s*\(",
    r"\bxit\s*\(", r"\bxdescribe\s*\(", r"\btest\.skip\s*\(",
    r"@Disabled\b", r"@Ignore\b", r"markTestSkipped", r"markTestIncomplete",
    r"\bt\.Skip\s*\(", r"\bskip\s*[:=]\s*true",
]

CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".go",
                   ".rb", ".rs", ".c", ".h", ".cpp", ".cc", ".cs", ".php",
                   ".swift", ".m", ".scala", ".ex", ".exs", ".dart", ".sh",
                   ".lua", ".r", ".pl", ".vue", ".svelte", ".blade.php"}

# ---------------------------------------------------------------------------
# AI / LLM detection (NEW)
# ---------------------------------------------------------------------------
# Detection happens from 4 places:
#   1. Commit messages/trailers  (most reliable — Co-Authored-By etc.)
#   2. Commit/MR author          (AI agent bot accounts)
#   3. MR/PR title+description   (agents write their own attribution)
#   4. Tool config files in repo (CLAUDE.md, .cursorrules... = tool was used)
#   5. Code comments             ("Generated by ..." headers)
#
# IMPORTANT: these are all EXPLICIT markers. Silent AI use (pasting with
# attribution stripped) cannot be detected — the result is a LOWER BOUND.

LLM_SIGNATURES = [
    ("Claude (Claude Code)", [
        r"co-authored-by:\s*claude\b",
        r"noreply@anthropic\.com",
        r"generated with \[?claude",
        r"claude\.(ai|com)/(code|claude-code)",
        r"\bclaude code\b",
        r"🤖 generated with",
    ]),
    ("GitHub Copilot", [
        r"co-authored-by:.{0,40}copilot",
        r"copilot-swe-agent",
        r"generated (by|with|using) (github )?copilot",
        r"copilot@github\.com",
        r"\bcopilot workspace\b",
    ]),
    ("Cursor", [
        r"co-authored-by:\s*cursor",
        r"cursoragent@cursor\.(sh|com)",
        r"generated (by|with|using) cursor\b",
        r"\bcursor (agent|composer)\b",
    ]),
    ("Aider", [
        r"co-authored-by:\s*aider",
        r"\baider \(.*\) *$",
        r"aider\.chat",
        r"generated (by|with|using) aider\b",
        r"aider:\s",
    ]),
    ("Devin", [
        r"devin-ai-integration",
        r"co-authored-by:\s*devin",
        r"devin\.ai",
        r"created by devin\b",
    ]),
    ("ChatGPT / OpenAI Codex", [
        r"co-authored-by:.{0,40}(chatgpt|openai|codex)",
        r"generated (by|with|using) (chatgpt|gpt-?[345o]|openai codex|codex)",
        r"generated by (an? )?llm.{0,60}(openai|gpt-?\d)",
        r"\bopenai'?s\s+gpt", r"\bgpt-?[34](\.\d)?[o]?\s+model\b",
        r"chatgpt\.com/codex",
        r"codex-cli",
    ]),
    ("Gemini / Jules", [
        r"co-authored-by:.{0,40}(gemini|jules|google-labs)",
        r"generated (by|with|using) gemini",
        r"google-labs-jules",
        r"\bgemini (cli|code assist)\b",
    ]),
    ("Sweep AI", [r"sweep-ai\b", r"sweep\.dev", r"generated by sweep\b"]),
    ("Windsurf / Codeium", [
        r"co-authored-by:.{0,40}(windsurf|codeium|cascade)",
        r"generated (by|with|using) (windsurf|codeium)",
    ]),
    ("Amazon Q / CodeWhisperer", [
        r"\bamazon q developer\b", r"codewhisperer",
    ]),
    ("OpenHands", [r"openhands", r"all-hands\.dev"]),
    ("Codegen", [r"codegen-sh\b", r"codegen\.com"]),
    ("Generic AI", [
        r"co-authored-by:.{0,40}\bai\b",
        r"(auto-?)?generated (by|with|using) (an? )?(ai|llm|large language model)\b",
        r"this (commit|change|code|pr|mr) was (written|generated|created) by (an? )?(ai|llm)\b",
        # Reversed word-order: "29 AI-generated", "LLM-generated tests"
        # (strict word boundaries — so project names like "ClientAI" do NOT match)
        r"\b(ai|llm)[- ]generated\b",
        r"\b(ai|llm)[- ](written|created|assisted)\b",
        r"\bwritten (by|with) (an? )?(ai|llm)\b",
    ]),
]

# Author/username -> LLM (bot accounts that commit/PR by themselves)
LLM_BOT_AUTHORS = [
    ("Claude (Claude Code)", [r"^claude(\[bot\])?$", r"claude-code"]),
    ("GitHub Copilot",       [r"copilot", r"copilot-swe-agent"]),
    ("Devin",                [r"devin-ai-integration", r"^devin\b"]),
    ("Sweep AI",             [r"sweep-ai"]),
    ("Gemini / Jules",       [r"google-labs-jules", r"^jules\b"]),
    ("Cursor",               [r"^cursor(\[bot\]|-agent)?$", r"cursoragent"]),
    ("OpenHands",            [r"openhands"]),
    ("Codegen",              [r"codegen-sh"]),
]

# AI tool config/instruction files in the repo = the tool was actively used
AI_TOOL_CONFIGS = [
    ("Claude (Claude Code)", [r"(^|/)CLAUDE(\.local)?\.md$", r"^\.claude/"]),
    ("Cursor",               [r"^\.cursorrules$", r"^\.cursor/",
                              r"^\.cursorignore$"]),
    ("GitHub Copilot",       [r"^\.github/copilot-instructions\.md$",
                              r"^\.github/copilot/"]),
    ("Aider",                [r"^\.aider\.conf\.ya?ml$", r"^\.aiderignore$",
                              r"(^|/)CONVENTIONS\.md$"]),
    ("Windsurf / Codeium",   [r"^\.windsurfrules$", r"^\.windsurf/",
                              r"^\.codeium/"]),
    ("Gemini / Jules",       [r"(^|/)GEMINI\.md$", r"^\.gemini/",
                              r"^\.jules/"]),
    ("Continue",             [r"^\.continue/", r"^\.continuerc"]),
    ("Sourcegraph Cody",     [r"^\.sourcegraph/", r"^\.cody/"]),
    ("Generic AI agents",    [r"(^|/)AGENTS?\.md$", r"^\.ai/", r"^\.mcp\.json$"]),
]

# Explicit AI-attribution comments inside source code
LLM_CODE_COMMENT_SIGNATURES = [
    ("Claude (Claude Code)", [r"generated (by|with|using) claude",
                              r"written (by|with) claude\b"]),
    ("ChatGPT / OpenAI Codex", [r"generated (by|with|using) (chatgpt|gpt-?[345o]|codex)",
                              r"generated by (an? )?llm.{0,60}(openai|gpt-?\d)",
                              r"\bopenai'?s\s+gpt"]),
    ("GitHub Copilot",       [r"generated (by|with|using) (github )?copilot",
                              r"suggested by copilot"]),
    ("Cursor",               [r"generated (by|with|using) cursor\b"]),
    ("Gemini / Jules",       [r"generated (by|with|using) gemini"]),
    ("Generic AI",           [r"(auto-?)?generated (by|with|using) (an? )?(ai|llm)\b",
                              r"ai-generated (code|file|module|test)",
                              r"\b(ai|llm)[- ]generated\b"]),
]


def detect_llms_in_text(text):
    """Which LLM signatures appear in text (commit msg / MR description).
    Returns: set of LLM names."""
    found = set()
    t = text or ""
    for name, pats in LLM_SIGNATURES:
        if any(_compiled(p, re.IGNORECASE).search(t) for p in pats):
            found.add(name)
    # Keep "Generic AI" only when no specific LLM was found
    if len(found) > 1:
        found.discard("Generic AI")
    return found


def detect_llm_author(author):
    """Is the author/username an AI agent bot? Returns the name or None."""
    a = (author or "").lower()
    for name, pats in LLM_BOT_AUTHORS:
        if any(_compiled(p, re.IGNORECASE).search(a) for p in pats):
            return name
    return None


def detect_ai_tool_configs(paths):
    """AI tool config files in the file tree. Returns {tool: [paths...]}"""
    found = {}
    for p in paths:
        norm = (p or "").replace("\\", "/").lstrip("/")
        for tool, pats in AI_TOOL_CONFIGS:
            if any(_compiled(pat, re.IGNORECASE).search(norm) for pat in pats):
                found.setdefault(tool, []).append(norm)
                break
    return found


def detect_llms_in_code(content):
    """Explicit AI attribution in a source file's comments — including the
    EXACT LOCATION (line number).

    Previously this only returned a `set` of LLM names (just "yes/no" — you
    couldn't tell WHERE inside the file it matched). Now every match also
    comes with its exact line number, so the evidence can show file + line
    (e.g. "utils.py:3").

    Returns: {llm_name: [line_no, line_no, ...]}   (1-indexed lines)
    """
    found = {}
    head = (content or "")[:8000]   # attribution headers sit at the top
    lines = head.splitlines()
    for name, pats in LLM_CODE_COMMENT_SIGNATURES:
        hit_lines = [i for i, line in enumerate(lines, start=1)
                    if any(_compiled(p, re.IGNORECASE).search(line) for p in pats)]
        if hit_lines:
            found[name] = hit_lines
    # Keep "Generic AI" only when no specific LLM was found
    if len(found) > 1:
        found.pop("Generic AI", None)
    return found


# ---------------------------------------------------------------------------
# Training-data quality detection (NEW)
# ---------------------------------------------------------------------------
# Factors needed when curating code for LLM post-training:
#   1. License          — permissive/copyleft/none (legal filter)
#   2. Syntax validity  — Python files ast.parse se, baaki binary-junk check
#   3. Quality metrics  — line length, comment ratio, function length, nesting
#   4. Deduplication    — duplicate files % (normalized content hash)
#   5. Secrets/PII      — API keys, private keys, emails (masked report)
#   6. Eval contamination — known HumanEval/MBPP function signatures
#   7. Composite score + Training suitability grade (A/B/C/D)
#
# NOTE: License classification is HEURISTIC — not legal advice.
# Secrets are never reported in PLAIN text — always masked.

LICENSE_CLASSIFIERS = [
    # Order matters: specific ones first (AGPL before GPL, BSD-3 before BSD-2)
    ("AGPL-3.0",     r"gnu affero general public license"),
    ("LGPL",         r"gnu lesser general public license"),
    ("GPL-3.0",      r"gnu general public license[\s\S]{0,80}version 3"),
    ("GPL-2.0",      r"gnu general public license[\s\S]{0,80}version 2"),
    ("Apache-2.0",   r"apache license[,\s]*version 2\.0"),
    ("MPL-2.0",      r"mozilla public license[,\s]*(v(ersion)?\.?\s*)?2\.0"),
    ("MIT",          r"permission is hereby granted, free of charge"),
    ("BSD-3-Clause", r"redistribution and use in source and binary forms"
                     r"[\s\S]{0,600}neither the name"),
    ("BSD-2-Clause", r"redistribution and use in source and binary forms"),
    ("ISC",          r"permission to use, copy, modify, and(/or)? distribute "
                     r"this software"),
    ("Unlicense",    r"this is free and unencumbered software"),
    ("CC0-1.0",      r"cc0|creative commons zero"),
    ("WTFPL",        r"do what the f\w+ you want"),
]

LICENSE_RISK = {
    "MIT": "permissive", "Apache-2.0": "permissive",
    "BSD-2-Clause": "permissive", "BSD-3-Clause": "permissive",
    "ISC": "permissive", "Unlicense": "permissive", "CC0-1.0": "permissive",
    "WTFPL": "permissive", "MPL-2.0": "weak-copyleft", "LGPL": "weak-copyleft",
    "GPL-2.0": "copyleft", "GPL-3.0": "copyleft", "AGPL-3.0": "copyleft",
}

LICENSE_FILE_RE = re.compile(
    r"(^|/)(un)?licen[cs]e(\.(md|txt|rst))?$|(^|/)copying(\.txt)?$",
    re.IGNORECASE)

SECRET_PATTERNS = [
    ("AWS Access Key",   r"\bAKIA[0-9A-Z]{16}\b"),
    ("GitHub Token",     r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    ("GitLab Token",     r"\bglpat-[A-Za-z0-9_\-]{20,}\b"),
    ("Google API Key",   r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("Slack Token",      r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),
    ("Stripe Key",       r"\b[sp]k_(live|test)_[A-Za-z0-9]{16,}\b"),
    ("OpenAI Key",       r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    ("Anthropic Key",    r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b"),
    ("Private Key",      r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?"
                         r"PRIVATE KEY"),
    ("JWT",              r"\beyJ[A-Za-z0-9_\-]{15,}\.eyJ[A-Za-z0-9_\-]{15,}"),
    ("Hardcoded secret", r"(?i)\b(password|passwd|secret|api[_-]?key|"
                         r"auth[_-]?token)\b\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
]

# Skip "hardcoded secret" false positives (placeholders). Deliberately
# narrow — this is a security scanner, so a broad word like bare "test"
# or "sample" would silently swallow real secrets that happen to sit in a
# test fixture/config (a very common place for a leaked real credential).
_PLACEHOLDER_RE = re.compile(
    r"(?i)(changeme|change[_-]?this|example\.com|your[_-]|dummy|placeholder|"
    r"xxxx|\*\*\*|<[^>]*>|\{\{|\$\{|os\.environ|process\.env|getenv|"
    r"\bNone\b|\bnull\b|\bTODO\b|\bFIXME\b|fake[_-]?(key|secret|token)|"
    r"insert[_-]?(your|api)|replace[_-]?(with|me))")

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
_EMAIL_IGNORE_RE = re.compile(
    r"(?i)(example\.|noreply|no-reply|test@|@test\.|localhost|\.png|\.jpg|"
    r"@example|users\.noreply|@sentry|@2x)")

# Distinctive HumanEval / MBPP signatures — if these are in training data
# it's benchmark contamination (eval scores become fake)
EVAL_CONTAMINATION_SIGNATURES = [
    "def has_close_elements(", "def separate_paren_groups(",
    "def truncate_number(", "def below_zero(",
    "def mean_absolute_deviation(", "def intersperse(",
    "def parse_nested_parens(", "def similar_elements(",
    "def is_not_prime(", "def heap_queue_largest(",
    "def count_ways(", "def differ_At_One_Bit_Pos(",
]

_COMMENT_PREFIXES = ("#", "//", "/*", "*", "--", "<!--", "%", ";", "'")
_FUNC_DEF_RE = re.compile(
    r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:def|function|func|fn)\s+\w+|"
    r"^\s*(?:export\s+(?:default\s+)?)?(?:public|private|protected|static)"
    r"[\w<>\[\],\s]*\s\w+\s*\([^;]*\)\s*\{|"
    # JS/TS arrow-function assignments — export const Foo = (...) => {...}
    # (by far the most common function form in modern React/Next.js code;
    # the plain 'function' keyword patterns above miss these entirely)
    r"^\s*(?:export\s+(?:default\s+)?)?(?:const|let|var)\s+\w+\s*"
    r"(?::\s*[^=\n]+)?=\s*(?:async\s*)?\([^)]*\)\s*(?::\s*[^=\n]+)?=>|"
    r"^\s*(?:export\s+(?:default\s+)?)?(?:const|let|var)\s+\w+\s*=\s*"
    r"async\s+function\b",
    re.MULTILINE)
_CLASS_DEF_RE = re.compile(
    r"^\s*(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+\w+|"
    r"^\s*(?:public|private|protected|internal)?\s*(?:abstract\s+|final\s+|"
    r"static\s+|sealed\s+)*class\s+\w+|"
    r"^\s*(?:export\s+)?(?:pub\s+)?struct\s+\w+|"   # Rust structs (no classes)
    r"^\s*(?:export\s+)?interface\s+\w+|"           # TS/Java/Go interfaces
    r"^\s*(?:export\s+)?type\s+\w+\s+struct\s*\{",  # Go structs
    re.MULTILINE)


def _mask_secret(v):
    """Secrets are never reported in plain text — masked version."""
    return (v[:4] + "…" + v[-2:]) if len(v) > 10 else "****"


def scan_secrets_and_pii(content, path):
    """Secrets (masked) + email count for one file. Returns (secrets, emails).

    Uses finditer (not search) per pattern — a file can carry more than one
    distinct secret of the same type (e.g. two different AWS keys), and
    re.search would only ever surface the first one.
    """
    secrets = []
    seen = set()
    for name, pat in SECRET_PATTERNS:
        matched = 0
        for m in _compiled(pat, 0).finditer(content):
            if matched >= 20:   # cap per pattern per file — avoid pathological blowup
                break
            val = m.group(0)
            if name == "Hardcoded secret":
                # skip placeholder values / env lookups
                line_start = content.rfind("\n", 0, m.start()) + 1
                line_end = content.find("\n", m.end())
                if line_end == -1:
                    line_end = len(content)
                if _PLACEHOLDER_RE.search(content[line_start:line_end]):
                    continue
            key = (name, val)
            if key in seen:
                continue
            seen.add(key)
            matched += 1
            secrets.append({"type": name, "file": path,
                            "masked": _mask_secret(val)})
    emails = 0
    for m in EMAIL_RE.finditer(content):
        if not _EMAIL_IGNORE_RE.search(m.group(0)):
            emails += 1
    return secrets, emails


def scan_file_quality(path, content):
    """Per-file quality metrics — the standard signals for training-data curation."""
    lines = content.splitlines()
    n = len(lines) or 1
    lens = [len(l) for l in lines]
    stripped = [l.strip() for l in lines]
    nonblank = [s for s in stripped if s]
    blank = n - len(nonblank)
    comment = sum(1 for s in stripped if s.startswith(_COMMENT_PREFIXES))
    code_lines = max(1, n - blank - comment)
    long_lines = sum(1 for L in lens if L > 120)
    funcs = len(_FUNC_DEF_RE.findall(content))
    classes = len(_CLASS_DEF_RE.findall(content))
    # nesting depth (approx): max leading indent / 4 (tabs = 1 level)
    depth = 0
    for l in lines:
        ind = len(l) - len(l.lstrip(" \t"))
        tabs = l[:ind].count("\t")
        depth = max(depth, tabs + (ind - tabs) // 4)
    alnum = sum(c.isalnum() for c in content)
    # syntax check — exact for Python (ast), binary-junk heuristic for the rest
    syntax_valid = None
    if path.endswith(".py"):
        try:
            ast.parse(content)
            syntax_valid = True
        except (SyntaxError, ValueError, MemoryError, RecursionError):
            syntax_valid = False
    elif "\x00" in content[:4000]:
        syntax_valid = False
    return {
        "lines": n, "code_lines": code_lines,
        "avg_len": sum(lens) / n, "max_len": max(lens) if lens else 0,
        "long_lines": long_lines,
        "comment_lines": comment, "blank_lines": blank,
        "funcs": funcs, "classes": classes, "max_depth": depth,
        "alnum_ratio": alnum / max(1, len(content)),
        "syntax_valid": syntax_valid,
        "has_docstring": (path.endswith(".py")
                          and bool(re.search(r'^\s*(?:\'\'\'|""")',
                                             content[:2000], re.M))),
        # hash=None for near-empty files (e.g. blank __init__.py) so they
        # don't all collide and massively inflate the duplicate-file %
        "hash": (hashlib.sha1(
            "\n".join(nonblank).encode("utf-8", "ignore")).hexdigest()
            if len(nonblank) >= 3 else None),
        "eval_contam": any(sig in content
                           for sig in EVAL_CONTAMINATION_SIGNATURES),
    }


_SPDX_SHORT = {"mit": "MIT", "apache-2.0": "Apache-2.0", "apache2": "Apache-2.0",
               "gpl-2.0": "GPL-2.0", "gpl-3.0": "GPL-3.0", "gplv2": "GPL-2.0",
               "gplv3": "GPL-3.0", "agpl-3.0": "AGPL-3.0", "lgpl": "LGPL",
               "bsd-2-clause": "BSD-2-Clause", "bsd-3-clause": "BSD-3-Clause",
               "isc": "ISC", "mpl-2.0": "MPL-2.0", "unlicense": "Unlicense",
               "cc0": "CC0-1.0", "wtfpl": "WTFPL"}


def classify_license(text):
    """SPDX-like name from license file text. Heuristic — not legal advice."""
    t = (text or "").lower()
    # Short form: the file contains only an SPDX id ("MIT", "Apache-2.0"...)
    if len(t.strip()) <= 40 and t.strip() in _SPDX_SHORT:
        return _SPDX_SHORT[t.strip()]
    for name, pat in LICENSE_CLASSIFIERS:
        if re.search(pat, t):
            return name
    return ""

VENDOR_DIR_HINTS = ("/vendor/", "/node_modules/", "/dist/", "/build/",
                    "/.git/", "/bower_components/", "/storage/framework/",
                    "/__pycache__/", "/.venv/", "/venv/", "/.tox/",
                    "/site-packages/", "/pods/", "/.next/", "/.nuxt/",
                    "/coverage/", "/htmlcov/", "/.gradle/", "/deriveddata/",
                    "/.terraform/", "/target/debug/", "/target/release/",
                    # C++ / game-engine vendor & build-output folders
                    "/thirdparty/", "/third_party/", "/intermediate/",
                    "/binaries/", "/extern/", "/external/")

# Generated/minified files — neither source nor tests; they skew the counts
GENERATED_FILE_SUFFIXES = (".min.js", ".min.css", ".bundle.js", ".chunk.js",
                           ".map", ".pb.go", "_pb2.py", "_pb2_grpc.py",
                           ".g.dart", ".freezed.dart", ".generated.ts",
                           ".d.ts",
                           # C++: protobuf, Unreal reflection headers, lex/yacc
                           ".pb.cc", ".pb.h", ".generated.h", ".generated.cpp",
                           ".tab.c", ".tab.h", ".yy.c")

# Generated C++ filename *prefixes* (checked against the basename, not the
# full path) — Qt's meta-object compiler and UI compiler output
GENERATED_FILE_PREFIXES = ("moc_", "ui_", "qrc_")

# Extension -> language (for local repos)
EXT_LANG = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java",
    ".kt": "Kotlin", ".go": "Go", ".rb": "Ruby", ".rs": "Rust",
    ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".cs": "C#",
    ".php": "PHP", ".swift": "Swift", ".m": "Objective-C",
    ".scala": "Scala", ".ex": "Elixir", ".exs": "Elixir", ".dart": "Dart",
    ".sh": "Shell", ".lua": "Lua", ".r": "R", ".pl": "Perl",
    ".vue": "Vue", ".svelte": "Svelte", ".html": "HTML", ".css": "CSS",
}

# ---------------------------------------------------------------------------
# CI/CD detection (NEW) — which config files indicate which CI system
# ---------------------------------------------------------------------------

CI_SYSTEMS = [
    ("GitLab CI",           [r"^\.gitlab-ci\.ya?ml$", r"^\.gitlab/ci/.+\.ya?ml$"]),
    ("GitHub Actions",      [r"^\.github/workflows/.+\.ya?ml$"]),
    ("Jenkins",             [r"(^|/)Jenkinsfile([^/]*)$"]),
    ("CircleCI",            [r"^\.circleci/config\.ya?ml$"]),
    ("Travis CI",           [r"^\.travis\.ya?ml$"]),
    ("Azure Pipelines",     [r"^azure-pipelines[^/]*\.ya?ml$", r"^\.azure-pipelines/.+\.ya?ml$"]),
    ("Bitbucket Pipelines", [r"^bitbucket-pipelines\.ya?ml$"]),
    ("Drone CI",            [r"^\.drone\.ya?ml$"]),
    ("AppVeyor",            [r"^\.?appveyor\.ya?ml$"]),
    ("Buildkite",           [r"^\.buildkite/.+\.ya?ml$"]),
    ("TeamCity",            [r"^\.teamcity/"]),
    ("Google Cloud Build",  [r"^cloudbuild\.ya?ml$"]),
    ("Woodpecker CI",       [r"^\.woodpecker\.ya?ml$", r"^\.woodpecker/.+\.ya?ml$"]),
    ("Tekton",              [r"^\.tekton/.+\.ya?ml$"]),
    ("Bamboo",              [r"^bamboo-specs/"]),
]

GITLAB_CI_RESERVED = {"stages", "variables", "include", "default", "workflow",
                      "image", "services", "before_script", "after_script",
                      "cache", "pages", "types"}


def detect_ci_configs(paths):
    """Find CI config files in a list of file paths.
    Returns: {system_name: [paths...]}"""
    found = {}
    for p in paths:
        norm = (p or "").replace("\\", "/").lstrip("/")
        for system, pats in CI_SYSTEMS:
            if any(re.search(pat, norm, re.IGNORECASE) for pat in pats):
                found.setdefault(system, []).append(norm)
                break
    return found


def analyze_ci_config(system, content):
    """Approximate count of jobs/stages inside a CI config file (regex-based,
    no YAML parser dependency). Returns: {jobs, stages}"""
    jobs, stages = 0, 0
    if not content:
        return {"jobs": 0, "stages": 0}
    try:
        if system == "GitLab CI":
            # top-level keys that are not reserved = jobs
            top_keys = re.findall(r"^([A-Za-z_.][\w.\- ]*):", content, re.MULTILINE)
            jobs = len([k for k in top_keys
                        if k.strip().lower() not in GITLAB_CI_RESERVED
                        and not k.startswith(".")])          # .hidden = templates
            m = re.search(r"^stages:\s*\n((?:\s*-\s*.+\n?)+)", content, re.MULTILINE)
            if m:
                stages = len(re.findall(r"^\s*-\s*\S", m.group(1), re.MULTILINE))
            inline = re.search(r"^stages:\s*\[(.*?)\]", content, re.MULTILINE)
            if inline:
                stages = len([s for s in inline.group(1).split(",") if s.strip()])
        elif system == "GitHub Actions":
            # the whole indented block under 'jobs:'; its 2-space keys = jobs
            m = re.search(r"^jobs:[ \t]*\n((?:(?:[ \t]+[^\n]*)?\n)+)",
                          content, re.MULTILINE)
            block = m.group(1) if m else ""
            jobs = len(re.findall(r"^  ([\w\-]+):", block, re.MULTILINE))
            stages = 1 if jobs else 0
        elif system == "Jenkins":
            jobs = len(re.findall(r"\bstage\s*[\('\"]", content))
            stages = jobs
        else:
            # generic YAML: count 'steps'/'jobs' entries
            jobs = len(re.findall(r"^\s*-\s*(name|step|task|script)\s*:",
                                  content, re.MULTILINE))
    except Exception:
        pass
    return {"jobs": jobs, "stages": stages}


@functools.lru_cache(maxsize=2048)
def _compiled(pattern, flags):
    """Cache compiled regexes explicitly rather than relying on re's
    internal cache — the pattern lists above (BOT_PATTERNS, TEST_CASE_
    PATTERNS, LLM_SIGNATURES, SECRET_PATTERNS, ...) run across many files
    x many repos, and this keeps every distinct (pattern, flags) pair
    compiled exactly once for the life of the process."""
    return re.compile(pattern, flags)


def matches_any(text, patterns, flags=re.IGNORECASE):
    t = text or ""
    return any(_compiled(p, flags).search(t) for p in patterns)


def count_matches(text, patterns, flags=0):
    """Sum of match counts across a list of patterns (precompiled)."""
    t = text or ""
    return sum(len(_compiled(p, flags).findall(t)) for p in patterns)


def is_bot(username: str) -> bool:
    return matches_any(username, BOT_PATTERNS)


def is_vendor_path(path: str) -> bool:
    p = "/" + (path or "").replace("\\", "/").lower() + "/"
    return any(h in p for h in VENDOR_DIR_HINTS)


def is_test_support_file(path: str) -> bool:
    """Support file inside a test folder (fixture/helper/config) — NOT a test."""
    p = "/" + (path or "").replace("\\", "/").lower()
    return matches_any(p, TEST_SUPPORT_PATTERNS)


def is_test_path(path: str) -> bool:
    p = "/" + (path or "").replace("\\", "/").lower()
    if is_vendor_path(path):
        return False
    if is_test_support_file(path):
        return False
    # test/tests/spec/etc. directory anywhere in the path (substring match —
    # subsumes the top-level case too; names like "testimonials" or
    # "test_data_loader.py" don't match since TEST_DIR_HINTS entries are
    # slash-delimited full segments)
    if any(h in p for h in TEST_DIR_HINTS):
        return True
    return matches_any(p, TEST_FILE_PATTERNS, flags=re.IGNORECASE)


_TEST_AFFIX_RE = re.compile(
    r"^(tests?|specs?)[_\-.]+|[_\-.]+(tests?|specs?|it)$", re.IGNORECASE)


def _file_subject_stem(path: str) -> str:
    """Basename with extension(s) and test/spec affixes stripped — used to
    pair a test file with the source file it most likely tests, by name
    (e.g. 'test_foo.py' / 'foo_test.py' / 'Foo.test.ts' / 'FooTest.java'
    all reduce to the stem 'foo', matching source file 'foo.py')."""
    base = (path or "").rsplit("/", 1)[-1]
    base = re.sub(r"\.(test|spec)\.[A-Za-z0-9]+$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\.[A-Za-z0-9]+$", "", base)
    prev = None
    while prev != base:
        prev = base
        base = _TEST_AFFIX_RE.sub("", base)
    return base.lower()


def is_code_file(path: str) -> bool:
    p = (path or "").lower()
    if is_vendor_path(path):
        return False
    if p.endswith(GENERATED_FILE_SUFFIXES):
        return False
    basename = p.rsplit("/", 1)[-1]
    if basename.startswith(GENERATED_FILE_PREFIXES):
        return False
    return any(p.endswith(ext) for ext in CODE_EXTENSIONS)


def analyze_test_content(content: str) -> dict:
    """
    Genuineness analysis of a test file's content.
    verdict: 'genuine' | 'suspicious' | 'not_a_test'
    """
    content = content[:2_000_000]   # cap regex work on pathological files
    cases = count_matches(content, TEST_CASE_PATTERNS)
    assertions = count_matches(content, ASSERTION_PATTERNS)
    trivial = count_matches(content, TRIVIAL_ASSERTION_PATTERNS)
    skipped = count_matches(content, SKIP_PATTERNS)

    cleaned = content
    for p in TRIVIAL_ASSERTION_PATTERNS:
        cleaned = _compiled(p, 0).sub("", cleaned)
    real_assertions = count_matches(cleaned, ASSERTION_PATTERNS)

    if cases == 0:
        verdict = "not_a_test"
    elif real_assertions == 0:
        verdict = "suspicious"
    elif skipped >= cases:
        verdict = "suspicious"
    else:
        verdict = "genuine"
    return {"cases": cases, "assertions": assertions, "trivial": trivial,
            "skipped": skipped, "verdict": verdict}


# ---------------------------------------------------------------------------
# HTTP base client (used by both GitLab and GitHub)
# ---------------------------------------------------------------------------

def _retry_after_seconds(r, default=30):
    """Parse Retry-After safely (it may be seconds OR an HTTP date)."""
    v = r.headers.get("Retry-After", "")
    try:
        return max(1, int(v))
    except (TypeError, ValueError):
        return default


class HttpBase:
    def __init__(self, api_base, headers, workers=8):
        if not HAS_REQUESTS:
            raise SystemExit("ERROR: install this first ->  pip install requests")
        self.api = api_base.rstrip("/")
        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=workers * 2,
                              pool_maxsize=workers * 2, max_retries=2)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update(headers)

    def _rate_limit_wait(self, r):
        """How long to wait on a 429/403 rate limit. None = not a rate limit."""
        raise NotImplementedError

    def get(self, path, params=None):
        url = path if path.startswith("http") else self.api + path
        # Network errors and rate-limit waits are different failure modes
        # with independent budgets — a call stuck behind rate limiting
        # could otherwise burn through all its retries just waiting, then
        # get treated identically to a genuine 404 by callers.
        net_attempt = 0
        rate_limit_waits = 0
        while True:
            try:
                r = self.session.get(url, params=params, timeout=60)
            except requests.RequestException as e:
                if net_attempt >= 5:
                    print(f"  [warn] network error, giving up on {url}: {e}")
                    return None
                time.sleep(min(2 ** net_attempt, 30))
                net_attempt += 1
                continue
            wait = self._rate_limit_wait(r)
            if wait is not None:
                if rate_limit_waits >= 20:
                    print(f"  [warn] still rate-limited after "
                          f"{rate_limit_waits} waits, giving up on {url} "
                          "(this is NOT a 404 — the resource may still "
                          "exist, it just couldn't be fetched)")
                    return None
                print(f"  [rate limit] {wait}s wait...")
                time.sleep(wait)
                rate_limit_waits += 1
                continue
            if r.status_code in (401, 403):
                raise SystemExit(
                    "ERROR: Access denied (401/403). Check the token — "
                    "the scope must be correct, or the repo is private.")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r


# ---------------------------------------------------------------------------
# Real code-line counting (ported from loc.py's character-level scanner)
#
# Both loc_estimate paths below used to do `content.count("\n")` — a raw
# physical-line count that includes comments, blank lines and docstrings.
# That is not "lines of code", and it disagreed with loc.py (the dedicated,
# audited LOC tool) on every file with a nonzero comment ratio. This block
# ports loc.py's per-language comment/string state machine so both tools
# agree on what counts as a line of code: a physical line is CODE only if
# it still has a non-whitespace character left after block/line comments
# and non-code string continuations are stripped out.
# ---------------------------------------------------------------------------

_LOC_C_STYLE = {"line": ["//"], "block": [("/*", "*/")], "strings": ['"', "'", "`"]}
_LOC_HASH = {"line": ["#"], "block": [], "strings": ['"', "'"]}

# Keyed by extension, covering exactly the languages in CODE_EXTENSIONS above.
LOC_LANGUAGES = {
    ".py":  {"line": ["#"], "block": [], "strings": ['"', "'"], "doc": True},
    ".js": _LOC_C_STYLE, ".jsx": _LOC_C_STYLE,
    ".ts": _LOC_C_STYLE, ".tsx": _LOC_C_STYLE,
    ".java": _LOC_C_STYLE,
    ".kt": _LOC_C_STYLE,
    ".go": _LOC_C_STYLE,
    ".rb": {"line": ["#"], "block": [("=begin", "=end")], "strings": ['"', "'"]},
    ".rs": {"line": ["///", "//!", "//"], "block": [("/*", "*/")], "strings": ['"']},
    ".c": _LOC_C_STYLE, ".h": _LOC_C_STYLE,
    ".cpp": _LOC_C_STYLE, ".cc": _LOC_C_STYLE,
    ".cs": {"line": ["///", "//"], "block": [("/*", "*/")], "strings": ['"', "'"]},
    ".php": {"line": ["//", "#"], "block": [("/*", "*/")], "strings": ['"', "'"]},
    ".swift": _LOC_C_STYLE,
    ".m": _LOC_C_STYLE,
    ".scala": _LOC_C_STYLE,
    ".ex": {"line": ["#"], "block": [], "strings": ['"'], "doc": True},
    ".exs": {"line": ["#"], "block": [], "strings": ['"'], "doc": True},
    ".dart": _LOC_C_STYLE,
    ".sh": _LOC_HASH,
    ".lua": {"line": ["--"], "block": [("--[[", "]]")], "strings": ['"', "'"]},
    ".r": _LOC_HASH,
    ".pl": _LOC_HASH,
    ".vue": {"line": ["//"], "block": [("<!--", "-->"), ("/*", "*/")], "strings": ['"', "'"]},
    ".svelte": {"line": ["//"], "block": [("<!--", "-->"), ("/*", "*/")], "strings": ['"', "'"]},
    ".blade.php": {"line": ["//", "#"], "block": [("/*", "*/")], "strings": ['"', "'"]},
}
_LOC_DEFAULT_SPEC = {"line": [], "block": [], "strings": ['"']}


def _loc_spec_for(path):
    p = (path or "").lower()
    if p.endswith(".blade.php"):
        return LOC_LANGUAGES[".blade.php"]
    _, ext = os.path.splitext(p)
    return LOC_LANGUAGES.get(ext, _LOC_DEFAULT_SPEC)


class _LocState:
    """Carries block-comment / multi-line-string state across physical
    lines of the SAME file. A fresh instance must be used per file."""
    __slots__ = ("block_close", "block_is_doc", "string_delim", "string_is_doc")

    def __init__(self):
        self.block_close = None
        self.block_is_doc = False
        self.string_delim = None
        self.string_is_doc = False


def _is_code_line(line, spec, state):
    """True if this physical line still has real code after stripping
    comments and non-payload string delimiters. Mutates `state` for
    multi-line block comments / strings that continue past this line.
    This is loc.py's `scan_line` state machine, trimmed to just the
    code/not-code decision (no sub-category or audit metadata needed here).
    """
    block_pairs = spec.get("block", [])
    quotes = spec.get("strings", [])
    line_markers = sorted(spec.get("line", []), key=len, reverse=True)
    is_doc_lang = spec.get("doc", False)

    code_chars = []
    i, n = 0, len(line)
    while i < n:
        if state.block_close:
            idx = line.find(state.block_close, i)
            if idx == -1:
                break
            i = idx + len(state.block_close)
            state.block_close = None
            state.block_is_doc = False
            continue

        if state.string_delim:
            if not state.string_is_doc:
                code_chars.append("x")   # string payload counts as CODE
            idx = line.find(state.string_delim, i)
            while idx > 0 and line[idx - 1] == "\\":
                idx = line.find(state.string_delim, idx + 1)
            if idx == -1:
                break
            i = idx + len(state.string_delim)
            state.string_delim = None
            state.string_is_doc = False
            continue

        ch = line[i]
        if ch in " \t":
            i += 1
            continue
        rest = line[i:]

        marker = next((m for m in line_markers if rest.startswith(m)), None)
        if marker:
            break   # rest of the line is a line comment

        pair = next((p for p in block_pairs if rest.startswith(p[0])), None)
        if pair:
            this_is_doc = (rest.startswith(pair[0] + "*")
                           or rest.startswith(pair[0] + "!"))
            i += len(pair[0])
            end = line.find(pair[1], i)
            if end == -1:
                state.block_close = pair[1]
                state.block_is_doc = this_is_doc
                break
            i = end + len(pair[1])
            continue

        triple = next((q * 3 for q in quotes if rest.startswith(q * 3)), None)
        if triple:
            is_doc = is_doc_lang and not code_chars   # docstring only if nothing precedes it
            if not is_doc:
                code_chars.append("x")
            i += 3
            end = line.find(triple, i)
            if end == -1:
                state.string_delim = triple
                state.string_is_doc = is_doc
                break
            i = end + 3
            continue

        quote = next((q for q in quotes if rest.startswith(q)), None)
        if quote:
            code_chars.append(quote)
            i += 1
            end = line.find(quote, i)
            while end > 0 and line[end - 1] == "\\":
                end = line.find(quote, end + 1)
            if end == -1:
                state.string_delim = quote
                state.string_is_doc = False
                break
            code_chars.append(line[i:end])
            i = end + 1
            continue

        code_chars.append(ch)
        i += 1

    return bool("".join(code_chars).strip())


def _real_code_lines(content, path):
    """Real CODE-line count for one file's content: comments, blank lines
    and docstrings excluded, using the same per-language scanner as
    loc.py. Falls back to counting non-blank lines for extensions with no
    registered comment/string spec (e.g. .json, .md), matching loc.py's
    NONE_/text-file behaviour of "no comment syntax => every non-blank
    line is code"."""
    spec = _loc_spec_for(path)
    state = _LocState()
    n = 0
    for line in content.splitlines():
        if _is_code_line(line, spec, state):
            n += 1
    return n


def _sampled_real_loc(prov, info, code_paths, sample_cap=300):
    """Real per-file CODE-line counts via the API, on a bounded sample,
    extrapolated to the full code-file list.

    Replaces the old `size_bytes / 35` guess, which conflated total repo
    size (binaries, textures, audio, full compressed git history) with
    actual lines of code, and could be off by orders of magnitude on
    asset-heavy repos. Per-file counting itself is done by
    `_real_code_lines`, which excludes comments/blank lines/docstrings —
    a raw `content.count("\\n")` counts every physical line including
    those, which is not "lines of code".

    Falls back to the byte-based guess only if every sampled fetch fails
    (e.g. no read access to file contents) so the field never comes back
    empty when we at least know the repo size.
    """
    if not code_paths:
        return ""
    if len(code_paths) <= sample_cap:
        sample = code_paths
    else:
        # evenly spaced sample across the whole file list, not just the
        # first N (avoids skew from directory ordering)
        step = len(code_paths) / sample_cap
        sample = [code_paths[int(i * step)] for i in range(sample_cap)]

    def count_lines(path):
        content = prov.file_content(info, path)
        if content is None:
            return None
        if not content:
            return 0
        return _real_code_lines(content, path)

    total, counted = 0, 0
    workers = getattr(prov, "workers", 8)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(count_lines, p) for p in sample]
        for fut in as_completed(futures):
            try:
                n = fut.result()
            except Exception:
                n = None
            if n is not None:
                total += n
                counted += 1

    if counted == 0:
        # every fetch failed — fall back to the old repo-size guess rather
        # than reporting nothing
        b = info.get("size_bytes", 0)
        return int(b / 35) if b else ""

    if len(code_paths) > counted:
        total = int(total * len(code_paths) / counted)
    return total


# ---------------------------------------------------------------------------
# GitLab provider
# ---------------------------------------------------------------------------

def enc(project_path):
    """group/subgroup/repo -> URL-encoded ID (numeric IDs pass through as-is)."""
    s = str(project_path)
    return s if s.isdigit() else quote(s, safe="")


class GitLabProvider(HttpBase):
    kind = "gitlab"
    mr_word = "MRs"

    def __init__(self, base_url="https://gitlab.com", token=None, workers=8):
        headers = {"User-Agent": "codebase-analyzer"}
        if token:
            headers["PRIVATE-TOKEN"] = token
        self.token = token  # kept for authenticated `git clone` (remote coverage)
        self.workers = workers
        super().__init__(base_url.rstrip("/") + "/api/v4", headers, workers)

    def _rate_limit_wait(self, r):
        if r.status_code == 429:
            return _retry_after_seconds(r, default=30)
        return None

    def paginate(self, path, params=None, limit=None):
        params = dict(params or {})
        params.setdefault("per_page", 100)
        params.setdefault("page", 1)
        results = []
        while True:
            try:
                r = self.get(path, params=params)
            except SystemExit:
                raise
            except Exception as e:
                print(f"  [warn] pagination stopped early: {e}")
                break
            if r is None:
                break
            try:
                data = r.json()
            except ValueError:
                break
            if not isinstance(data, list) or not data:
                break
            results.extend(data)
            if len(results) and len(results) % 1000 == 0:
                print(f"    ...{len(results)} items fetched")
            if limit and len(results) >= limit:
                return results[:limit]
            nxt = r.headers.get("X-Next-Page", "")
            if not nxt:
                break
            params["page"] = nxt
        return results

    # --- normalized interface ---

    def list_group_projects(self, group):
        gp = self.paginate(f"/groups/{enc(group)}/projects",
                           params={"include_subgroups": "true",
                                   "archived": "false"})
        return [p["id"] for p in gp]

    def project_info(self, project_id):
        pid = enc(project_id)
        r = self.get(f"/projects/{pid}", params={"statistics": "true"})
        if r is None:
            return None
        proj = r.json()
        stats = proj.get("statistics") or {}
        commits = stats.get("commit_count", "")
        if commits == "":
            rc = self.get(f"/projects/{pid}/repository/commits",
                          params={"per_page": 1})
            if rc is not None:
                total = rc.headers.get("X-Total")
                commits = int(total) if total and total.isdigit() else ""
        return {
            "id": pid,
            "name": proj.get("path_with_namespace", str(project_id)),
            "visibility": proj.get("visibility", ""),
            "created_at": (proj.get("created_at") or "")[:10],
            "last_activity": (proj.get("last_activity_at") or "")[:10],
            "default_branch": proj.get("default_branch") or "main",
            "commits": commits,
            "size_bytes": stats.get("repository_size", 0) or 0,
            "web_url": proj.get("web_url", ""),
        }

    def languages(self, info):
        lr = self.get(f"/projects/{info['id']}/languages")
        return lr.json() if lr else {}

    def contributors(self, info):
        contribs = self.paginate(
            f"/projects/{info['id']}/repository/contributors")
        return [{"name": c.get("name", ""), "id": c.get("email", "")}
                for c in contribs]

    def commit_dates(self, info):
        """(first_commit_date, last_commit_date) on the default branch.

        Note: this is NOT the same as info['created_at'], which is the date
        the *project* was created on GitLab. For imported/migrated repos the
        first commit can predate project creation by years.
        """
        p = {"per_page": 1, "ref_name": info["default_branch"]}
        r = self.get(f"/projects/{info['id']}/repository/commits", params=p)
        if r is None or not r.json():
            return "", ""
        last = (r.json()[0].get("committed_date") or "")[:10]
        # with per_page=1, total items == total pages; last page = oldest commit
        total = r.headers.get("X-Total")
        pages = int(total) if total and total.isdigit() else 0
        if not pages:
            # GitLab omits X-Total on some large/self-hosted instances for
            # performance — fall back to the Link header (same rel="last"
            # convention GitHub uses) before trusting info["commits"], which
            # can itself be stale/estimated and previously caused this to
            # silently report first_commit == last_commit on repos with a
            # long history.
            m = re.search(r'[?&]page=(\d+)>;\s*rel="last"',
                          r.headers.get("Link", ""))
            pages = (int(m.group(1)) if m
                     else (info["commits"] if isinstance(info["commits"], int)
                           else 0))
        if pages <= 1:
            return last, last
        r2 = self.get(f"/projects/{info['id']}/repository/commits",
                      params={**p, "page": pages})
        d2 = r2.json() if r2 is not None else []
        first = (d2[0].get("committed_date") or "")[:10] if d2 else ""
        return first, last

    def commit_log(self, info, limit):
        """Recent commits: [{author, email, message}] — for LLM detection."""
        commits = self.paginate(
            f"/projects/{info['id']}/repository/commits",
            params={"ref_name": info["default_branch"]},
            limit=limit or None)
        return [{"author": c.get("author_name", ""),
                 "email": c.get("author_email", ""),
                 "message": c.get("message") or c.get("title", ""),
                 "sha": c.get("id", "")}   # exact commit — for LLM location
                for c in commits]

    def merge_requests(self, info, limit):
        mrs = self.paginate(f"/projects/{info['id']}/merge_requests",
                            params={"state": "all", "order_by": "created_at",
                                    "sort": "desc"},
                            limit=limit or None)
        out = []
        for m in mrs:
            out.append({
                "number": m["iid"],
                "title": m.get("title", ""),
                "description": m.get("description") or "",
                "author": (m.get("author") or {}).get("username", ""),
                "merged": m.get("state") == "merged",
                "notes": m.get("user_notes_count", 0),
                "url": m.get("web_url", ""),   # exact MR location
            })
        return out

    def mr_analysis(self, info, mr):
        """Return: {notes, n_files, loc, touches_tests, loc_known}"""
        n_files, loc, touches_tests = 0, 0, False
        path = f"/projects/{info['id']}/merge_requests/{mr['number']}/diffs"
        per_page = 100
        MAX_DIFF_PAGES = 20   # 2000 files ought to be enough for anyone
        dr = self.get(path, params={"per_page": per_page, "page": 1})
        loc_known = dr is not None
        diffs = []
        page = 1
        # Paginate past the first 100 files (a MR bigger than that — e.g. a
        # lockfile-heavy dependency bump — used to silently undercount loc).
        while dr is not None:
            page_diffs = dr.json()
            diffs.extend(page_diffs)
            if len(page_diffs) < per_page or page >= MAX_DIFF_PAGES:
                break
            page += 1
            dr = self.get(path, params={"per_page": per_page, "page": page})
        n_files = len(diffs)
        for d in diffs:
            if is_test_path(d.get("new_path") or d.get("old_path") or ""):
                touches_tests = True
            diff_text = d.get("diff", "") or ""
            loc += sum(1 for line in diff_text.splitlines()
                       if (line.startswith("+") or line.startswith("-"))
                       and not line.startswith(("+++", "---")))
        return {"notes": mr.get("notes", 0), "n_files": n_files,
                "loc": loc, "touches_tests": touches_tests,
                "loc_known": loc_known}

    def tree(self, info):
        pid, ref = info["id"], info["default_branch"]
        tree = self.paginate(f"/projects/{pid}/repository/tree",
                             params={"recursive": "true", "ref": ref})
        if not tree:
            print("    [warn] tree came back empty, retrying with HEAD ref...")
            tree = self.paginate(f"/projects/{pid}/repository/tree",
                                 params={"recursive": "true"})
        return [t["path"] for t in tree if t.get("type") == "blob"]

    def file_content(self, info, path):
        fr = self.get(
            f"/projects/{info['id']}/repository/files/{quote(path, safe='')}/raw",
            params={"ref": info["default_branch"]})
        return fr.text if fr is not None else None

    def loc_estimate(self, info, code_paths, sample_cap=300):
        """Real line count from a sampled set of files via the API
        (extrapolated) — not a repo-size guess. See _sampled_real_loc."""
        return _sampled_real_loc(self, info, code_paths, sample_cap=sample_cap)

    def ci_stats(self, info):
        """GitLab pipelines: total, recent success rate, duration, coverage."""
        pid = info["id"]
        out = {"pipelines_total": "", "success_rate": "",
               "avg_duration_min": "", "coverage_pct": ""}
        r = self.get(f"/projects/{pid}/pipelines", params={"per_page": 100})
        if r is None:
            return out
        pipelines = r.json()
        total = r.headers.get("X-Total")
        out["pipelines_total"] = (int(total) if total and total.isdigit()
                                  else len(pipelines))
        finished = [p for p in pipelines
                    if p.get("status") in ("success", "failed")]
        if finished:
            succ = len([p for p in finished if p["status"] == "success"])
            out["success_rate"] = round(100 * succ / len(finished), 1)
        # Duration + coverage from the latest successful pipelines — fetched
        # concurrently instead of one blocking call at a time (this was the
        # only sequential per-item fetch loop left; everywhere else in the
        # script already parallelizes with a ThreadPoolExecutor).
        durations = []
        successful = [p for p in pipelines[:10] if p.get("status") == "success"]
        workers = min(getattr(self, "workers", 8), len(successful)) or 1
        if successful:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                details = list(pool.map(
                    lambda p: self.get(f"/projects/{pid}/pipelines/{p['id']}"),
                    successful))
            for pd_ in details:
                if pd_ is None:
                    continue
                det = pd_.json()
                if det.get("duration"):
                    durations.append(det["duration"])
                cov = det.get("coverage")
                if cov and out["coverage_pct"] == "":
                    try:
                        out["coverage_pct"] = round(float(cov), 1)
                    except (TypeError, ValueError):
                        pass
        if durations:
            out["avg_duration_min"] = round(sum(durations) / len(durations) / 60, 1)
        return out


# ---------------------------------------------------------------------------
# GitHub provider
# ---------------------------------------------------------------------------

class GitHubProvider(HttpBase):
    kind = "github"
    mr_word = "PRs"

    def __init__(self, base_url="https://api.github.com", token=None, workers=8):
        headers = {"User-Agent": "codebase-analyzer",
                   "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.token = token  # kept for authenticated `git clone` (remote coverage)
        self.workers = workers
        super().__init__(base_url, headers, workers)

    def _rate_limit_wait(self, r):
        if r.status_code in (403, 429):
            if r.headers.get("Retry-After"):
                return _retry_after_seconds(r, default=60)
            if r.headers.get("X-RateLimit-Remaining") == "0":
                try:
                    reset = int(r.headers.get("X-RateLimit-Reset", 0))
                except (TypeError, ValueError):
                    reset = 0
                wait = max(5, reset - int(time.time()) + 2)
                return min(wait, 3600)
        return None

    def paginate(self, path, params=None, limit=None):
        params = dict(params or {})
        params.setdefault("per_page", 100)
        params.setdefault("page", 1)
        results = []
        while True:
            try:
                r = self.get(path, params=params)
            except SystemExit:
                raise
            except Exception as e:
                print(f"  [warn] pagination stopped early: {e}")
                break
            if r is None:
                break
            try:
                data = r.json()
            except ValueError:
                break
            if not isinstance(data, list) or not data:
                break
            results.extend(data)
            if len(results) and len(results) % 1000 == 0:
                print(f"    ...{len(results)} items fetched")
            if limit and len(results) >= limit:
                return results[:limit]
            if len(data) < int(params["per_page"]):
                break
            params["page"] = int(params["page"]) + 1
        return results

    # --- normalized interface ---

    def list_group_projects(self, org):
        repos = self.paginate(f"/orgs/{org}/repos", params={"type": "all"})
        if not repos:  # maybe it's a user account, not an org
            repos = self.paginate(f"/users/{org}/repos")
        return [r["full_name"] for r in repos if not r.get("archived")]

    def project_info(self, project_id):
        r = self.get(f"/repos/{project_id}")
        if r is None:
            return None
        proj = r.json()
        full = proj.get("full_name", str(project_id))
        # Commit count: per_page=1, then read the last page number from the Link header
        commits = ""
        rc = self.get(f"/repos/{full}/commits", params={"per_page": 1})
        if rc is not None:
            link = rc.headers.get("Link", "")
            m = re.search(r'[?&]page=(\d+)>;\s*rel="last"', link)
            if m:
                commits = int(m.group(1))
            elif rc.json():
                commits = 1
        return {
            "id": full,
            "name": full,
            "visibility": "private" if proj.get("private") else "public",
            "created_at": (proj.get("created_at") or "")[:10],
            "last_activity": (proj.get("pushed_at")
                              or proj.get("updated_at") or "")[:10],
            "default_branch": proj.get("default_branch") or "main",
            "commits": commits,
            "size_bytes": (proj.get("size", 0) or 0) * 1024,  # size is in KB
            "license_hint": ((proj.get("license") or {}).get("spdx_id")
                             or "").replace("NOASSERTION", ""),
            "web_url": proj.get("html_url", ""),
        }

    def languages(self, info):
        lr = self.get(f"/repos/{info['id']}/languages")
        return lr.json() if lr else {}

    def contributors(self, info):
        # anon=true includes contributors who committed with an email that
        # isn't linked to a GitHub account — without this, large/old repos
        # (lots of pre-GitHub-account commits) get badly undercounted
        # compared to local mode, which counts every unique author in the
        # git log regardless of GitHub-account linkage.
        contribs = self.paginate(f"/repos/{info['id']}/contributors",
                                 params={"anon": "true"})
        return [{"name": c.get("login") or c.get("name", ""),
                 "id": c.get("login") or c.get("email", "")}
                for c in contribs]

    def commit_dates(self, info):
        """(first_commit_date, last_commit_date) on the default branch.

        Note: this is NOT the same as info['created_at'] (repo creation on
        GitHub) or info['last_activity'] (pushed_at, which also fires for
        non-commit pushes such as tags or branch deletes).
        """
        r = self.get(f"/repos/{info['id']}/commits", params={"per_page": 1})
        if r is None or not r.json():
            return "", ""

        def _d(c):
            return (((c.get("commit") or {}).get("committer") or {})
                    .get("date") or "")[:10]

        last = _d(r.json()[0])
        # with per_page=1, the last page number == total commits
        pages = info["commits"] if isinstance(info["commits"], int) else 0
        if not pages:
            m = re.search(r'[?&]page=(\d+)>;\s*rel="last"',
                          r.headers.get("Link", ""))
            pages = int(m.group(1)) if m else 1
        if pages <= 1:
            return last, last
        r2 = self.get(f"/repos/{info['id']}/commits",
                      params={"per_page": 1, "page": pages})
        d2 = r2.json() if r2 is not None else []
        return (_d(d2[0]) if d2 else ""), last

    def commit_log(self, info, limit):
        """Recent commits: [{author, email, message}] — for LLM detection."""
        commits = self.paginate(f"/repos/{info['id']}/commits",
                                limit=limit or None)
        out = []
        for c in commits:
            cc = c.get("commit") or {}
            author = ((c.get("author") or {}).get("login")
                      or (cc.get("author") or {}).get("name") or "")
            out.append({"author": author,
                        "email": (cc.get("author") or {}).get("email", ""),
                        "message": cc.get("message", ""),
                        "sha": c.get("sha", "")})   # exact commit
        return out

    def merge_requests(self, info, limit):
        prs = self.paginate(f"/repos/{info['id']}/pulls",
                            params={"state": "all", "sort": "created",
                                    "direction": "desc"},
                            limit=limit or None)
        out = []
        for p in prs:
            out.append({
                "number": p["number"],
                "title": p.get("title", ""),
                "description": p.get("body") or "",
                "author": (p.get("user") or {}).get("login", ""),
                "merged": bool(p.get("merged_at")),
                "notes": None,   # not in the list endpoint; only in detail
                "url": p.get("html_url", ""),   # exact PR location
            })
        return out

    def mr_analysis(self, info, mr):
        notes, n_files, loc, touches_tests = 0, 0, 0, False
        # the /files endpoint returns filenames plus additions/deletions.
        # Paginate past the first 100 files (GitHub returns up to 3000 for
        # this endpoint) — capping at page 1 used to silently undercount
        # loc/n_files for large PRs (e.g. a lockfile-heavy dependency bump).
        path = f"/repos/{info['id']}/pulls/{mr['number']}/files"
        per_page = 100
        MAX_FILE_PAGES = 30   # GitHub's own hard cap for this endpoint
        fr = self.get(path, params={"per_page": per_page, "page": 1})
        loc_known = fr is not None
        files = []
        page = 1
        while fr is not None:
            page_files = fr.json()
            files.extend(page_files)
            if len(page_files) < per_page or page >= MAX_FILE_PAGES:
                break
            page += 1
            fr = self.get(path, params={"per_page": per_page, "page": page})
        n_files = len(files)
        for f in files:
            if is_test_path(f.get("filename", "")):
                touches_tests = True
            loc += (f.get("additions", 0) or 0) + (f.get("deletions", 0) or 0)
        # comment count comes from the PR detail endpoint
        dr = self.get(f"/repos/{info['id']}/pulls/{mr['number']}")
        if dr is not None:
            det = dr.json()
            notes = ((det.get("comments", 0) or 0)
                     + (det.get("review_comments", 0) or 0))
        return {"notes": notes, "n_files": n_files,
                "loc": loc, "touches_tests": touches_tests,
                "loc_known": loc_known}

    def _walk_tree_full(self, info, root_sha):
        """Walk the repo tree directory-by-directory (non-recursive
        git/trees calls per folder) — used when the single recursive
        call comes back truncated. GitHub caps the recursive response
        at ~7MB, which large monorepos (e.g. game engines with tens of
        thousands of files) exceed, silently dropping the rest of the
        tree. This walks every folder individually (slower, more API
        calls, but complete) and rebuilds full paths ourselves since
        each non-recursive call only returns paths relative to that
        folder."""
        all_paths = []
        to_visit = [(root_sha, "")]
        workers = getattr(self, "workers", 8)
        while to_visit:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(self.get,
                                f"/repos/{info['id']}/git/trees/{sha}"): prefix
                    for sha, prefix in to_visit
                }
                next_visit = []
                for fut in as_completed(futures):
                    prefix = futures[fut]
                    try:
                        r = fut.result()
                    except Exception:
                        continue
                    if r is None:
                        continue
                    data = r.json()
                    for t in data.get("tree", []):
                        p = f"{prefix}{t['path']}"
                        if t.get("type") == "blob":
                            all_paths.append(p)
                        elif t.get("type") == "tree":
                            next_visit.append((t["sha"], p + "/"))
                to_visit = next_visit
        return all_paths

    def tree(self, info):
        r = self.get(f"/repos/{info['id']}/git/trees/"
                     f"{quote(info['default_branch'], safe='')}",
                     params={"recursive": "1"})
        if r is None:
            return []
        data = r.json()
        if data.get("truncated"):
            print("    [warn] recursive tree truncated (repo too large "
                  "for one call) — walking every directory individually "
                  "to get the complete file list, this takes longer...")
            root_sha = data.get("sha") or info["default_branch"]
            paths = self._walk_tree_full(info, root_sha)
            print(f"    ...full directory walk found {len(paths)} files "
                  f"(vs {len(data.get('tree', []))} from the truncated call)")
            return paths
        return [t["path"] for t in data.get("tree", [])
                if t.get("type") == "blob"]

    def file_content(self, info, path):
        url = (f"{self.api}/repos/{info['id']}/contents/{quote(path)}"
               f"?ref={quote(info['default_branch'], safe='')}")
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=60,
                                     headers={"Accept": "application/vnd.github.raw+json"})
            except requests.RequestException:
                time.sleep(2 ** attempt)
                continue
            wait = self._rate_limit_wait(r)
            if wait is not None:
                time.sleep(wait)
                continue
            if r.status_code != 200:
                return None
            return r.text
        return None

    def loc_estimate(self, info, code_paths, sample_cap=300):
        """Real line count from a sampled set of files via the API
        (extrapolated) — not a repo-size guess. See _sampled_real_loc."""
        return _sampled_real_loc(self, info, code_paths, sample_cap=sample_cap)

    def ci_stats(self, info):
        """GitHub Actions: workflow runs total, success rate, duration."""
        out = {"pipelines_total": "", "success_rate": "",
               "avg_duration_min": "", "coverage_pct": ""}
        r = self.get(f"/repos/{info['id']}/actions/runs",
                     params={"per_page": 100})
        if r is None:
            return out
        data = r.json()
        out["pipelines_total"] = data.get("total_count", "")
        runs = data.get("workflow_runs", [])
        finished = [x for x in runs
                    if x.get("conclusion") in ("success", "failure")]
        if finished:
            succ = len([x for x in finished if x["conclusion"] == "success"])
            out["success_rate"] = round(100 * succ / len(finished), 1)
        durations = []
        for x in runs[:20]:
            try:
                s = datetime.fromisoformat(
                    x["run_started_at"].replace("Z", "+00:00"))
                e = datetime.fromisoformat(
                    x["updated_at"].replace("Z", "+00:00"))
                d = (e - s).total_seconds()
                if 0 < d < 6 * 3600:
                    durations.append(d)
            except (KeyError, TypeError, ValueError):
                continue
        if durations:
            out["avg_duration_min"] = round(sum(durations) / len(durations) / 60, 1)
        # GitHub doesn't natively expose coverage — will stay blank
        return out


# ---------------------------------------------------------------------------
# Local / Offline provider (uses git commands — no internet required)
# ---------------------------------------------------------------------------

class LocalProvider:
    kind = "local"
    mr_word = "MRs/PRs (from git history)"

    def __init__(self, workers=8, mr_mode="auto"):
        self.workers = workers
        self.mr_mode = mr_mode   # auto | strict | merges | off
        self._gitattr_cache = {}   # repo path -> parsed linguist overrides

    def _linguist_overrides(self, root):
        """Parse .gitattributes for linguist-vendored / linguist-generated /
        linguist-documentation / linguist-language directives — this is the
        SAME mechanism GitHub's own Linguist consults first, so honoring it
        gets local-mode language stats much closer to what GitHub reports,
        for any repo where the maintainers have set these overrides."""
        if root in self._gitattr_cache:
            return self._gitattr_cache[root]
        rules = []   # list of (fnmatch_pattern, {"vendored":T/F,"generated":T/F,
                     #                            "documentation":T/F,"language":str})
        fp = os.path.join(root, ".gitattributes")
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    pattern, attrs = parts[0], parts[1:]
                    spec = {}
                    for a in attrs:
                        if a in ("linguist-vendored", "linguist-vendored=true"):
                            spec["vendored"] = True
                        elif a == "linguist-vendored=false":
                            spec["vendored"] = False
                        elif a in ("linguist-generated", "linguist-generated=true"):
                            spec["generated"] = True
                        elif a == "linguist-generated=false":
                            spec["generated"] = False
                        elif a in ("linguist-documentation",
                                   "linguist-documentation=true"):
                            spec["documentation"] = True
                        elif a == "linguist-documentation=false":
                            spec["documentation"] = False
                        elif a.startswith("linguist-language="):
                            spec["language"] = a.split("=", 1)[1]
                    if spec:
                        rules.append((pattern, spec))
        except OSError:
            pass
        self._gitattr_cache[root] = rules
        return rules

    @staticmethod
    def _match_linguist_override(path, rules):
        """Last matching rule wins (same precedence git itself uses)."""
        import fnmatch
        result = {}
        norm = path if path.startswith("/") else "/" + path
        for pattern, spec in rules:
            pat = pattern if pattern.startswith("/") else "*/" + pattern.lstrip("/")
            pat2 = pattern.rstrip("/") + "/*" if pattern.endswith("/") else None
            if fnmatch.fnmatch(norm, pat) or fnmatch.fnmatch(path, pattern) \
               or (pat2 and fnmatch.fnmatch(norm, "*/" + pat2)):
                result.update(spec)
        return result

    def _git(self, repo, *args, check=True):
        try:
            r = subprocess.run(["git", "-C", repo] + list(args),
                               capture_output=True, text=True, timeout=300,
                               errors="replace")
            if check and r.returncode != 0:
                return None
            return r.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def list_group_projects(self, group):
        # in local mode a "group" = a folder containing multiple repos
        out = []
        for entry in sorted(os.listdir(group)):
            p = os.path.join(group, entry)
            if os.path.isdir(os.path.join(p, ".git")):
                out.append(p)
        return out

    def project_info(self, path):
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            print(f"  folder '{path}' not found")
            return None
        has_git = os.path.isdir(os.path.join(path, ".git"))

        if not has_git:
            # ---- PLAIN FOLDER MODE (no git history) ----
            # Code from a zip extract / copy-paste — git-based fields
            # (commits, contributors, MRs) will stay blank, everything else works.
            # LLM detection will use tool configs + code comments.
            print("  [note] '.git' not found — plain-folder mode. "
                  "Commits/contributors/MRs will stay blank; "
                  "LLM detection will use code comments + tool configs.")
            mtimes = []
            for i, p in enumerate(self._walk_files(path)):
                if i >= 5000:
                    break
                try:
                    mtimes.append(os.path.getmtime(os.path.join(path, p)))
                except OSError:
                    pass
            fmt = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d")
            return {
                "id": path, "name": os.path.basename(path),
                "visibility": "local (no git)",
                "created_at": fmt(min(mtimes)) if mtimes else "",
                "last_activity": fmt(max(mtimes)) if mtimes else "",
                "default_branch": "", "commits": "", "size_bytes": 0,
                "no_git": True,
            }

        branch = (self._git(path, "rev-parse", "--abbrev-ref", "HEAD")
                  or "HEAD").strip()
        commits_out = self._git(path, "rev-list", "--count", "HEAD")
        commits = int(commits_out.strip()) if commits_out else ""
        first = self._git(path, "log", "--max-parents=0", "--format=%as")
        created = min(first.split()) if first and first.strip() else ""
        last = (self._git(path, "log", "-1", "--format=%as") or "").strip()
        # Repo name from remote, otherwise folder name
        remote = (self._git(path, "remote", "get-url", "origin",
                            check=False) or "").strip()
        name = os.path.basename(path)
        m = re.search(r"[:/]([^/:]+/[^/]+?)(\.git)?$", remote)
        if m:
            name = m.group(1)
        return {
            "id": path, "name": name, "visibility": "local",
            "created_at": created, "last_activity": last,
            "default_branch": branch, "commits": commits, "size_bytes": 0,
        }

    @staticmethod
    def _walk_files(root, cap=50000):
        """All files in a plain folder (relative paths) — skips vendor/hidden."""
        skip_dirs = {".git", "node_modules", "vendor", "dist", "build",
                     "__pycache__", ".venv", "venv", ".idea", ".vscode",
                     "bower_components", ".tox", ".mypy_cache", "target"}
        out = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fn in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                out.append(rel.replace("\\", "/"))
                if len(out) >= cap:
                    return out
        return out

    def languages(self, info):
        langs = Counter()
        rules = self._linguist_overrides(info["id"])
        for p in self.tree(info):
            pl = p.lower()
            override = self._match_linguist_override(p, rules) if rules else {}
            # .gitattributes overrides win over our own heuristics — this is
            # the same precedence GitHub's Linguist uses
            if override.get("vendored") is True:
                continue
            if override.get("generated") is True:
                continue
            if override.get("documentation") is True:
                continue
            if override.get("vendored") is not False and is_vendor_path(p):
                continue
            # Minified/compiled assets skew the language stats
            # (GitLab's linguist excludes them as well)
            if pl.endswith((".min.js", ".min.css", ".map",
                            ".bundle.js", ".chunk.js")):
                continue
            forced_lang = override.get("language")
            if forced_lang:
                lang = forced_lang
            elif pl.endswith(".blade.php"):
                lang = "Blade"
            else:
                lang = EXT_LANG.get(os.path.splitext(pl)[1])
            if lang:
                fp = os.path.join(info["id"], p)
                try:
                    langs[lang] += os.path.getsize(fp)
                except OSError:
                    pass
        return dict(langs)

    def contributors(self, info):
        if info.get("no_git"):
            return []
        out = self._git(info["id"], "log", "--format=%an%x01%ae") or ""
        seen = {}
        for line in out.splitlines():
            parts = line.split("\x01")
            if len(parts) == 2:
                name, email = parts
                seen.setdefault(email.lower(), name)
        return [{"name": n, "id": e} for e, n in seen.items()]

    def commit_dates(self, info):
        """(first_commit_date, last_commit_date) from the git history.

        `--max-parents=0` finds root commit(s); a repo with merged histories
        can have more than one, so take the earliest. On a shallow clone
        (`clone --depth`) the 'first' commit is only as old as the clone.
        """
        if info.get("no_git"):
            return "", ""
        first = self._git(info["id"], "log", "--max-parents=0", "--format=%as")
        first = min(first.split()) if first and first.strip() else ""
        last = (self._git(info["id"], "log", "-1", "--format=%as") or "").strip()
        return first, last

    def commit_log(self, info, limit):
        """Recent commits: [{author, email, message, sha}] — FULL message
        (including trailers/Co-Authored-By) + full commit hash (`%H`), so the
        exact commit containing an LLM signature can be pinpointed
        (`git show <sha>` jumps straight to that commit)."""
        if info.get("no_git"):
            return []
        args = ["log", "--format=%H%x01%an%x01%ae%x01%B%x02"]
        if limit:
            args.insert(1, f"-{limit}")
        out = self._git(info["id"], *args) or ""
        commits = []
        for chunk in out.split("\x02"):
            chunk = chunk.strip("\n")
            if not chunk.strip():
                continue
            parts = chunk.split("\x01", 3)
            if len(parts) == 4:
                commits.append({"sha": parts[0], "author": parts[1],
                                "email": parts[2], "message": parts[3]})
        return commits

    # --- MR/PR detection from git history ---
    # THE TRUTH IS: a local clone does NOT contain the real MR/PR database —
    # only their traces in commit messages. Therefore:
    #
    #   EXPLICIT references (100% certainly was an MR/PR):
    #     - GitHub merge:  "Merge pull request #123 from ..."
    #     - GitHub squash: subject "... (#123)"
    #     - GitLab merge:  body has "See merge request group/proj!123"
    #                      (GitLab's merge button writes this trailer itself)
    #     - GitLab squash: subject "... (!123)"
    #
    #   PLAIN merge commits ("Merge branch 'x'"):
    #     could be an MR, a dev's local merge, or a release merge —
    #     impossible to say for sure. This was the real cause of over-counting.
    #
    # Modes (--local-mrs):
    #   auto  (default): if explicit refs exist count ONLY those
    #                    (drop plain merges) — otherwise fall back to plain merges
    #   strict         : only explicit refs (most accurate, may under-count)
    #   merges         : explicit + plain merges (the old loose behaviour)
    #   off            : MR fields blank
    # Sync/pull merges are excluded in every mode. Unique numbers deduped.

    _PR_MERGE_RE = re.compile(r"^Merge pull request #(\d+)", re.IGNORECASE)
    _SQUASH_PR_RE = re.compile(r"\(#(\d+)\)\s*$")
    _GITLAB_MR_RE = re.compile(r"See merge request [\w./ -]*!(\d+)",
                               re.IGNORECASE)
    _GITLAB_SQUASH_RE = re.compile(r"\(!(\d+)\)\s*$")
    _SYNC_MERGE_RE = re.compile(
        r"^Merge (remote-tracking branch|tag )"
        r"|^Merge branch '[^']+' (of |into (?!'?(master|main)\b))",
        re.IGNORECASE)

    def _extract_ref(self, subject, body, is_merge):
        m = self._PR_MERGE_RE.search(subject)
        if m:
            return "PR#" + m.group(1)
        g = self._GITLAB_MR_RE.search(subject + "\n" + body)
        if g:
            return "MR!" + g.group(1)
        if not is_merge:
            m = self._SQUASH_PR_RE.search(subject)
            if m:
                return "PR#" + m.group(1)
            g = self._GITLAB_SQUASH_RE.search(subject)
            if g:
                return "MR!" + g.group(1)
        return None

    _MR_REF_PATTERNS = [
        "refs/merge-requests/*/head",
        "refs/remotes/origin/merge-requests/*/head",
        "refs/remotes/origin/merge-requests/*",
        "refs/pull/*/head",
        "refs/remotes/origin/pull/*/head",
        "refs/remotes/origin/pr/*",
    ]

    def _mrs_from_refs(self, info, limit):
        """EXACT MR/PR list — if the user fetched the server's MR refs.
        GitLab keeps each MR head at 'refs/merge-requests/N/head', GitHub
        at 'refs/pull/N/head'. Once fetched, the full MR history becomes
        available offline. Returns None if no refs were found."""
        fmt = ("%(refname)%01%(objectname)%01%(authorname)%01"
               "%(subject)%01%(contents:body)%02")
        out = self._git(info["id"], "for-each-ref", f"--format={fmt}",
                        *self._MR_REF_PATTERNS, check=False)
        if not out or not out.strip():
            return None
        # Which MRs are merged: the ones whose heads are reachable from HEAD
        merged_out = self._git(info["id"], "for-each-ref", "--merged", "HEAD",
                               "--format=%(refname)",
                               *self._MR_REF_PATTERNS, check=False) or ""
        merged_refs = set(merged_out.split())

        mrs = []
        for rec in out.split("\x02"):
            rec = rec.strip("\n")
            if not rec.strip():
                continue
            parts = rec.split("\x01")
            if len(parts) < 4:
                continue
            refname, sha, author, subject = (parts[0].strip(), parts[1],
                                             parts[2], parts[3])
            body = parts[4] if len(parts) > 4 else ""
            if refname.endswith("/merge"):   # skip GitHub's test-merge refs
                continue
            m = re.search(r"(?:merge-requests|pull|pr)/(\d+)", refname)
            iid = int(m.group(1)) if m else 0
            display_id = (f"MR!{iid}" if "merge-requests" in refname
                         else f"PR#{iid}" if iid else f"commit {sha[:10]}")
            mrs.append({"number": sha, "kind": "ref", "iid": iid,
                        "display_id": display_id,
                        "title": subject, "description": body,
                        "author": author,
                        "merged": refname in merged_refs, "notes": 0})
        if not mrs:
            return None
        mrs.sort(key=lambda x: x["iid"], reverse=True)   # newest first
        return mrs[:limit] if limit else mrs

    def merge_requests(self, info, limit):
        if self.mr_mode == "off" or info.get("no_git"):
            return []

        # Try the EXACT source first: fetched MR/PR refs
        ref_mrs = self._mrs_from_refs(info, limit)
        if ref_mrs:
            merged = len([m for m in ref_mrs if m["merged"]])
            print(f"    Found MR/PR refs — EXACT count: {len(ref_mrs)} "
                  f"({merged} merged/contained in HEAD). "
                  f"This is as accurate as the API.")
            return ref_mrs

        fmt = "%H%x01%P%x01%an%x01%s%x01%b%x02"
        out = self._git(info["id"], "log", "--first-parent",
                        f"--format={fmt}") or ""
        explicit, plain, seen = [], [], set()
        for rec in out.split("\x02"):
            rec = rec.strip("\n")
            if not rec.strip():
                continue
            parts = rec.split("\x01")
            if len(parts) < 4:
                continue
            sha, parents, author, subject = (parts[0].strip(), parts[1],
                                             parts[2], parts[3])
            body = parts[4] if len(parts) > 4 else ""
            is_merge = len(parents.split()) >= 2
            if is_merge and self._SYNC_MERGE_RE.search(subject):
                continue   # pull/sync/back-merge — not an MR
            num = self._extract_ref(subject, body, is_merge)
            mr = {"number": sha, "kind": "merge" if is_merge else "squash",
                  "display_id": num or f"commit {sha[:10]}",
                  "title": subject, "description": body, "author": author,
                  "merged": True, "notes": 0}
            if num:
                if num in seen:
                    continue
                seen.add(num)
                explicit.append(mr)
            elif is_merge:
                plain.append(mr)
            # plain single-parent commit without a ref = direct push, skip

        # Choose according to the mode
        if self.mr_mode == "strict":
            mrs = explicit
        elif self.mr_mode == "merges":
            mrs = explicit + plain
        else:  # auto
            mrs = explicit if explicit else plain

        # Transparency: show the user what was counted and what was dropped
        print(f"    Detection: {len(explicit)} explicit MR/PR refs "
              f"(#N / !N / 'See merge request'), "
              f"{len(plain)} plain merge commits")
        print("    [note] Fast-forward/squash merged MRs leave no trace in "
              "git history — this count is a FLOOR, not exact.")
        print("    TIP: if you want exact MR history offline, run this once "
              "in the repo (with network access):")
        print("      GitLab: git fetch origin "
              "\"+refs/merge-requests/*/head:refs/remotes/origin/"
              "merge-requests/*/head\"")
        print("      GitHub: git fetch origin "
              "\"+refs/pull/*/head:refs/remotes/origin/pull/*/head\"")
        print("    — after that this script will analyze all MRs EXACTLY.")
        if self.mr_mode == "auto" and explicit and plain:
            print(f"    -> auto mode: only {len(explicit)} explicit refs "
                  f"counted; {len(plain)} plain merges DROPPED "
                  f"(to count everything use --local-mrs merges)")
        elif self.mr_mode == "auto" and not explicit and plain:
            print(f"    -> no explicit refs found; treated {len(plain)} plain "
                  f"merge commits as an MR proxy (approximate — "
                  f"for exact counts use --provider gitlab/github)")
        for s in [m["title"] for m in mrs[:3]]:
            print(f"       sample: {s[:70]}")

        if limit:
            mrs = mrs[:limit]
        return mrs

    def mr_analysis(self, info, mr):
        n_files, loc, touches_tests = 0, 0, False
        if mr.get("kind") == "ref":
            # Diff the MR head against its merge-base (with HEAD) — that
            # is exactly the change the MR proposed
            mb = self._git(info["id"], "merge-base", "HEAD", mr["number"],
                           check=False)
            base = mb.strip() if mb and mb.strip() else None
            out = (self._git(info["id"], "diff", "--numstat",
                             base, mr["number"], check=False)
                   if base else None)
        else:
            # merge commit: diff against first parent | squash: against its parent
            base = mr["number"] + ("^1" if mr.get("kind") == "merge" else "^")
            out = self._git(info["id"], "diff", "--numstat",
                            base, mr["number"], check=False)
        if out is None or out == "":
            # root commit / detached ref etc. — use the commit's own stat
            out = self._git(info["id"], "show", "--numstat", "--format=",
                            mr["number"], check=False)
        # None means every git command above genuinely failed (bad ref,
        # detached commit, git error) — distinct from "" which means git
        # ran fine and reported zero changes (a real, if rare, empty MR).
        loc_known = out is not None
        if out:
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) != 3:
                    continue
                add, dele, path = parts
                n_files += 1
                if is_test_path(path):
                    touches_tests = True
                try:
                    loc += int(add) + int(dele)
                except ValueError:
                    pass   # binary files show '-' here
        return {"notes": 0, "n_files": n_files, "loc": loc,
                "touches_tests": touches_tests, "loc_known": loc_known}

    def tree(self, info):
        if not hasattr(self, "_tree_cache"):
            self._tree_cache = {}
        if info["id"] not in self._tree_cache:
            if info.get("no_git"):
                self._tree_cache[info["id"]] = self._walk_files(info["id"])
            else:
                out = self._git(info["id"], "ls-files") or ""
                paths = [p for p in out.splitlines() if p.strip()]
                # git exists but ls-files is empty (corrupt/bare?) -> walk fallback
                self._tree_cache[info["id"]] = (paths or
                                                self._walk_files(info["id"]))
        return self._tree_cache[info["id"]]

    # Read at most 5 MB per file — enough for every real source file, and it
    # keeps one giant generated/binary-ish file from blowing up memory.
    _MAX_READ_BYTES = 5_000_000

    def file_content(self, info, path):
        fp = os.path.join(info["id"], path)
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                return f.read(self._MAX_READ_BYTES)
        except OSError:
            return None

    def loc_estimate(self, info, code_paths):
        """ACTUAL CODE-line count for a local repo (not an estimate, not a
        raw physical-line count) — max 20k files.

        Reads every file as text and runs it through the same comment/
        string-aware scanner as loc.py, so comments/blank lines/docstrings
        are excluded and this number agrees with loc.py's on the same
        tree. The old version here did `chunk.count(b"\\n")` on raw bytes,
        which is a total-line count, not a code-line count.
        """
        total = 0
        for p in code_paths[:20000]:
            fp = os.path.join(info["id"], p)
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(self._MAX_READ_BYTES)
            except OSError:
                continue
            total += _real_code_lines(content, p)
        if len(code_paths) > 20000:
            total = int(total * len(code_paths) / 20000)
        return total

    def ci_stats(self, info):
        """Offline there is no pipeline history — we can only count CI config
        commits (a proxy for how actively it is maintained)."""
        out = {"pipelines_total": "", "success_rate": "",
               "avg_duration_min": "", "coverage_pct": ""}
        ci_paths = []
        for system, paths in detect_ci_configs(self.tree(info)).items():
            ci_paths.extend(paths)
        if ci_paths:
            log = self._git(info["id"], "log", "--oneline", "--",
                            *ci_paths[:20], check=False) or ""
            n = len([l for l in log.splitlines() if l.strip()])
            out["ci_commits"] = n
        return out


# ---------------------------------------------------------------------------
# Multi-language real coverage engine (ported from repo_test_auditor.py)
# ---------------------------------------------------------------------------
# Everything below, up to LANG_KEY_MAP, is reused verbatim from
# repo_test_auditor.py's `run_test_suite_status()` and its helpers. It
# actually RUNS each language's native test/coverage tool (pytest-cov,
# jest --coverage, go test -cover, JaCoCo, PHPUnit/Xdebug, SimpleCov,
# dotnet --collect, cargo-tarpaulin-style parsing, etc.) and parses the
# real coverage % out of its native report format. This is what powers
# multi-language coverage for GitLab/GitHub (via clone) and Local repos.

def run_tool(cmd: List, **kwargs) -> subprocess.CompletedProcess:
    """
    Drop-in replacement for subprocess.run() for external tool invocations
    (npm, npx, mvnw.cmd, gradlew.bat, etc.).

    On Windows, batch/script files (.cmd/.bat) are NOT valid PE (Win32)
    executables, so CreateProcess — what subprocess.run() uses under the
    hood with shell=False, even when given the fully resolved path — can't
    launch them directly and fails with:
        OSError: [WinError 193] %1 is not a valid Win32 application
    This affects npm, npx, and any *wrapper.cmd/.bat script, regardless of
    whether the path was resolved via shutil.which() first. The fix is to
    run these through the shell (cmd.exe), which knows how to execute
    batch files. Non-Windows platforms and real .exe/binaries are
    unaffected and behave exactly as a normal subprocess.run() call.

    We can't always trust the extension of cmd[0] to decide this up front:
    on some Windows machines a broken/customized PATHEXT (e.g. containing
    a stray empty entry from a leading/trailing ';') makes shutil.which()
    resolve "npm" to the extensionless POSIX/shebang shim that ships next
    to npm.cmd (meant for WSL/Git Bash) instead of npm.cmd itself. That
    path doesn't end in .cmd/.bat, so the check below can look clean and
    yet still hit WinError 193 when actually invoked. So: try the fast
    path first, and if it fails with exactly that error on Windows, retry
    once through the shell before giving up.
    """
    use_shell = os.name == "nt" and cmd and str(cmd[0]).lower().endswith((".cmd", ".bat"))
    if use_shell:
        kwargs = dict(kwargs)
        kwargs["shell"] = True
    try:
        return subprocess.run(cmd, **kwargs)
    except OSError as e:
        if os.name == "nt" and not use_shell and getattr(e, "winerror", None) == 193:
            retry_kwargs = dict(kwargs)
            retry_kwargs["shell"] = True
            return subprocess.run(cmd, **retry_kwargs)
        raise


IGNORE_DIRS = {
    "node_modules", ".git", "dist", "build", "out", "target", "venv",
    ".venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache",
    "vendor", ".idea", ".vscode", "coverage", ".next", ".nuxt",
    "bin", "obj", ".gradle", ".tox", "egg-info",
    # vendor / compiled / static-asset directories that are NOT
    # first-party application source, even though they may contain
    # .js/.py/etc files (e.g. Laravel's public/ holds compiled +
    # third-party JS, not code the team wrote or should unit test).
    "public", "wwwroot", "static", "third_party", "third-party",
    "external", "libs", "lib-vendor", "vendors",
}

_COVERAGE_NA = {"coverage_percent": None, "coverage_detail": "--coverage not passed", "coverage_setup_missing": None}


def _ensure_npm_deps(d: Path, timeout: int = 300) -> bool:
    """Fresh clones never have node_modules/ (it's gitignored), so without
    this the JS/TS coverage path always failed on any freshly cloned repo.
    Installs deps in-place (npm ci if a lockfile is present and matches,
    else npm install) and returns True if node_modules exists afterwards."""
    npm = resolve_executable("npm")
    use_ci = (d / "package-lock.json").exists()
    cmd = [npm, "ci"] if use_ci else [npm, "install"]
    try:
        proc = run_tool(cmd, cwd=d, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    if proc.returncode != 0 and use_ci:
        # npm ci fails hard if the lockfile is out of sync with
        # package.json — fall back to a plain install in that case.
        try:
            proc = run_tool([npm, "install"], cwd=d, capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=timeout)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False
    return (d / "node_modules").exists()


def _ensure_composer_deps(d: Path, timeout: int = 300) -> bool:
    """Same idea as _ensure_npm_deps but for PHP: a fresh clone never has
    vendor/, so phpunit is never on disk until `composer install` runs."""
    composer = resolve_executable("composer")
    cmd = [composer, "install", "--no-interaction", "--prefer-dist",
           "--no-progress"]
    try:
        run_tool(cmd, cwd=d, capture_output=True, text=True,
                 encoding="utf-8", errors="replace", timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return (d / "vendor").exists()


def _cov_unavailable(detail: str, setup_missing: bool = True) -> Dict:
    """setup_missing=True: the coverage tool/plugin itself isn't installed
    or configured in the target repo (e.g. pytest-cov missing, JaCoCo not
    in pom.xml, cargo-tarpaulin not installed). setup_missing=False: the
    tool ran but we couldn't get/parse a percentage out of its output."""
    return {"coverage_percent": None, "coverage_detail": detail, "coverage_setup_missing": setup_missing}


def _cov_ok(pct: float, detail: Optional[str] = None) -> Dict:
    return {"coverage_percent": round(pct, 1), "coverage_detail": detail, "coverage_setup_missing": False}


def _cov_na_for_not_run(coverage: bool, reason: str) -> Dict:
    """Coverage result for early-exit paths where tests couldn't even be
    run (missing deps/tools/timeout/etc). If --coverage wasn't requested,
    behaves like before. If it WAS requested, explains that coverage
    couldn't be collected because the test run itself never happened —
    instead of misleadingly saying '--coverage not passed'."""
    if not coverage:
        return _COVERAGE_NA
    return _cov_unavailable(f"tests could not run ({reason}), so coverage wasn't collected")


def run_test_suite_status(root: Path, lang_key: str, no_run: bool, coverage: bool = False) -> Dict:
    """
    Actually run the existing test suite for a language and report how many
    tests passed / failed / were skipped. Returns a dict with a 'status'
    key that is one of: 'passed', 'failed', 'no_tests', 'not_run'.

    If coverage=True, also attempts to collect a real coverage percentage
    using each language's native coverage tooling, and adds
    'coverage_percent' (float 0-100, or None) and 'coverage_detail' (str
    explaining why it's None, if applicable) to the returned dict.
    """
    result_default = {"status": "not_run", "passed": None, "failed": None,
                       "skipped": None, "detail": "Skipped (--no-run)", **_cov_na_for_not_run(coverage, "--no-run was passed")}
    if no_run:
        return result_default

    try:
        if lang_key == "js":
            pkg_dirs = find_manifest_dirs(root, ["package.json"])
            if not pkg_dirs:
                return {"status": "not_run", "passed": None, "failed": None,
                        "skipped": None, "detail": "No package.json found"}
            total_passed = total_failed = total_skipped = 0
            total_matched_tests = 0
            any_ran = False
            missing_deps_dirs = []
            zero_match_dirs = []
            parse_fail_details = []
            cov_pcts = []
            cov_details = []
            for d in pkg_dirs:
                if not (d / "node_modules").exists():
                    if not _ensure_npm_deps(d):
                        missing_deps_dirs.append(
                            str(d.relative_to(root)) + " (npm install failed)")
                        continue

                # Angular CLI projects use Karma+Jasmine (via `ng test`),
                # not Jest, and typically don't have jest installed at
                # all. Blindly running `npx jest` there makes npx try to
                # fetch/install jest on the fly, which either hangs
                # waiting on a y/N prompt or just times out — the test
                # suite never actually runs. Detect Angular via
                # angular.json and route to `ng test` instead.
                is_angular = (d / "angular.json").exists()

                if is_angular:
                    ng_cmd = [resolve_executable("npx"), "ng", "test", "--watch=false",
                              "--browsers=ChromeHeadless"]
                    if coverage:
                        ng_cmd += ["--code-coverage"]
                    proc = run_tool(
                        ng_cmd,
                        cwd=d, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                    )
                    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
                    # Karma prints an "Executed X of Y" progress line
                    # repeatedly as tests complete — starting from
                    # "Executed 0 of Y SUCCESS" right after the browser
                    # connects, then incrementing until the final line
                    # where X == Y (all tests accounted for). Using
                    # re.search() (first match) would grab that initial
                    # "0 of Y" line instead of the real final tally, which
                    # silently produces executed=0/passed=0/failed=0 —
                    # misreported as "no tests ran" even though the suite
                    # actually completed. Take the LAST match instead, and
                    # prefer the last one where executed == of_total (the
                    # true final summary) if such a line exists.
                    all_matches = re.findall(r"Executed\s+(\d+)\s+of\s+(\d+)(?:\s*\((\d+)\s*FAILED\))?", combined)
                    if not all_matches:
                        tail = "\n".join(ln.strip() for ln in combined.strip().splitlines() if ln.strip())[-800:]
                        parse_fail_details.append(f"{d.relative_to(root)}: ng test produced no parseable "
                                                   f"'Executed X of Y' summary (exit code {proc.returncode}). "
                                                   f"Last output:\n{tail}")
                        continue
                    final_matches = [mm for mm in all_matches if mm[0] == mm[1]]
                    m = final_matches[-1] if final_matches else all_matches[-1]
                    any_ran = True
                    executed, of_total, failed_n = int(m[0]), int(m[1]), int(m[2] or 0)
                    total_matched_tests += of_total
                    if of_total == 0:
                        zero_match_dirs.append(f"{d.relative_to(root)} (0 tests executed by Karma)")
                    total_failed += failed_n
                    total_passed += (executed - failed_n)
                    if coverage:
                        # karma-coverage / Angular CLI writes per-project
                        # coverage under coverage/<project-name>/ by
                        # default; search for any coverage-summary.json
                        # produced (requires the json-summary reporter to
                        # be configured — not always the case out of the
                        # box).
                        summary_matches = list((d / "coverage").rglob("coverage-summary.json")) \
                            if (d / "coverage").exists() else []
                        if summary_matches:
                            # Multiple coverage-summary.json files can pile up
                            # under coverage/ across config changes or repeated
                            # runs (e.g. a stale one from before coverageReporter.dir
                            # was set, sitting alongside the current one). Always
                            # use the most recently written file, not just
                            # whichever rglob() happens to return first.
                            newest = max(summary_matches, key=lambda p: p.stat().st_mtime)
                            try:
                                summary = json.loads(newest.read_text(encoding="utf-8", errors="ignore"))
                                total = summary.get("total", {})
                                line_pct = total.get("lines", {}).get("pct")
                                if isinstance(line_pct, (int, float)):
                                    cov_pcts.append(line_pct)
                                else:
                                    cov_details.append(
                                        f"{d.relative_to(root)}: found {newest.relative_to(root).as_posix()} "
                                        f"but it has no numeric total.lines.pct field "
                                        f"(keys present: {list(summary.keys())[:5]}). "
                                        f"{'Other coverage-summary.json file(s) also found: ' + ', '.join(str(p.relative_to(root)) for p in summary_matches if p != newest) if len(summary_matches) > 1 else ''}")
                            except (json.JSONDecodeError, OSError):
                                cov_details.append(f"{d.relative_to(root)}: could not parse coverage-summary.json")
                        else:
                            cov_details.append(f"{d.relative_to(root)}: no coverage-summary.json produced "
                                                f"(karma-coverage may need the 'json-summary' reporter configured "
                                                f"in karma.conf.js)")
                    continue

                jest_cmd = [resolve_executable("npx"), "jest", "--silent", "--json"]
                if coverage:
                    jest_cmd += ["--coverage", "--coverageReporters=json-summary"]
                proc = run_tool(
                    jest_cmd,
                    cwd=d, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                )
                stdout = (proc.stdout or "").strip()
                start = stdout.find("{")
                if start == -1:
                    continue
                try:
                    data = json.loads(stdout[start:])
                except json.JSONDecodeError:
                    continue
                any_ran = True
                num_suites = data.get("numTotalTestSuites", 0)
                num_tests = data.get("numTotalTests", 0)
                total_matched_tests += num_tests
                if num_tests == 0:
                    zero_match_dirs.append(f"{d.relative_to(root)} ({num_suites} suite file(s), 0 tests)")
                total_passed += data.get("numPassedTests", 0)
                total_failed += data.get("numFailedTests", 0)
                total_skipped += data.get("numPendingTests", 0)
                if coverage:
                    summary_path = d / "coverage" / "coverage-summary.json"
                    if summary_path.exists():
                        try:
                            summary = json.loads(summary_path.read_text(encoding="utf-8", errors="ignore"))
                            total = summary.get("total", {})
                            line_pct = total.get("lines", {}).get("pct")
                            if isinstance(line_pct, (int, float)):
                                cov_pcts.append(line_pct)
                        except (json.JSONDecodeError, OSError):
                            cov_details.append(f"{d.relative_to(root)}: could not parse coverage-summary.json")
                    else:
                        cov_details.append(f"{d.relative_to(root)}: no coverage-summary.json produced")
            if not any_ran:
                if missing_deps_dirs:
                    detail = ("node_modules missing in: " + ", ".join(missing_deps_dirs) +
                               " — run with --install or `npm install` there first")
                elif parse_fail_details:
                    detail = "; ".join(parse_fail_details)
                else:
                    detail = "Could not parse jest output"
                return {"status": "not_run", "passed": None, "failed": None,
                        "skipped": None, "detail": detail, **_cov_na_for_not_run(coverage, detail)}
            cov_result = _COVERAGE_NA if not coverage else (
                _cov_ok(sum(cov_pcts) / len(cov_pcts), None) if cov_pcts
                else _cov_unavailable("; ".join(cov_details) or "no coverage data produced", setup_missing=False))
            if total_matched_tests == 0:
                # Jest ran fine and found *.spec.js/*.test.js files, but none of
                # them contained anything Jest recognizes as a test case (e.g.
                # they're config-adjacent files like webpack.mix.spec.js, or
                # jest's testMatch/rootDir doesn't line up with these files).
                detail = ("Jest ran successfully but matched 0 test cases in: " +
                          "; ".join(zero_match_dirs) +
                          " — check jest config (testMatch/rootDir) and whether these "
                          "files actually contain it()/test() calls")
                return {"status": "no_tests", "passed": 0, "failed": 0,
                        "skipped": 0, "detail": detail, **cov_result}
            status = "failed" if total_failed > 0 else ("passed" if total_passed > 0 else "no_tests")
            return {"status": status, "passed": total_passed, "failed": total_failed,
                    "skipped": total_skipped, "detail": None, **cov_result}

        if lang_key == "python":
            if shutil.which("pytest") is None:
                return {"status": "not_run", "passed": None, "failed": None,
                        "skipped": None, "detail": "pytest not installed", **_cov_na_for_not_run(coverage, "pytest not installed")}
            proc = run_tool(["pytest", "-q"], cwd=root,
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
            out = proc.stdout + proc.stderr
            passed = _sum_regex(r"(\d+)\s+passed", out)
            failed = _sum_regex(r"(\d+)\s+failed", out)
            errors = _sum_regex(r"(\d+)\s+error", out)
            skipped = _sum_regex(r"(\d+)\s+skipped", out)
            total_fail = failed + errors
            status = "failed" if total_fail > 0 else ("passed" if passed > 0 else "no_tests")
            cov_result = _COVERAGE_NA
            if coverage:
                # Deliberately a SEPARATE pytest invocation from the one
                # above. If pytest-cov isn't installed, --cov makes pytest
                # fail with a usage error on the WHOLE run (not just skip
                # coverage) — combining them would wrongly zero out real
                # test results whenever the coverage plugin is missing.
                cov_proc = run_tool(
                    ["pytest", "-q", "--cov=.", "--cov-report=term-missing"], cwd=root,
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
                cov_out = cov_proc.stdout + cov_proc.stderr
                if "unrecognized arguments" in cov_out and "--cov" in cov_out:
                    cov_result = _cov_unavailable("pytest-cov not installed (pip install pytest-cov)")
                else:
                    m = re.search(r"^TOTAL\s+\d+\s+\d+\s+(?:\d+\s+)?(\d+)%", cov_out, re.MULTILINE)
                    cov_result = _cov_ok(float(m.group(1))) if m else \
                        _cov_unavailable("could not find TOTAL coverage line in pytest-cov output", setup_missing=False)
            return {"status": status, "passed": passed, "failed": total_fail,
                    "skipped": skipped, "detail": None, **cov_result}

        if lang_key == "go":
            if shutil.which("go") is None:
                return {"status": "not_run", "passed": None, "failed": None,
                        "skipped": None, "detail": "go toolchain not installed", **_cov_na_for_not_run(coverage, "go toolchain not installed")}
            go_dirs = find_manifest_dirs(root, ["go.mod"]) or [root]
            total_passed = total_failed = total_skipped = 0
            cov_pcts = []
            for d in go_dirs:
                cmd = [resolve_executable("go"), "test", "./...", "-v"]
                if coverage:
                    cmd.append("-cover")
                proc = run_tool(cmd, cwd=d,
                                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
                out = proc.stdout + proc.stderr
                total_passed += len(re.findall(r"--- PASS:", out))
                total_failed += len(re.findall(r"--- FAIL:", out))
                total_skipped += len(re.findall(r"--- SKIP:", out))
                if coverage:
                    cov_pcts += [float(m) for m in re.findall(r"coverage:\s*([\d.]+)%\s+of statements", out)]
            status = "failed" if total_failed > 0 else ("passed" if total_passed > 0 else "no_tests")
            cov_result = _COVERAGE_NA if not coverage else (
                _cov_ok(sum(cov_pcts) / len(cov_pcts)) if cov_pcts
                else _cov_unavailable("no 'coverage: X% of statements' lines found in `go test -cover` output", setup_missing=False))
            return {"status": status, "passed": total_passed, "failed": total_failed,
                    "skipped": total_skipped, "detail": None, **cov_result}

        if lang_key == "java":
            build_dirs = find_manifest_dirs(root, ["pom.xml", "build.gradle", "build.gradle.kts", "mvnw", "gradlew"])
            if not build_dirs:
                return {"status": "not_run", "passed": None, "failed": None,
                        "skipped": None, "detail": "No Maven/Gradle build file found (searched all subfolders)"}
            total = failures = errors = skipped_total = 0
            any_ran = False
            unrunnable_dirs = []
            for d in build_dirs:
                cmd = find_mvn_command(d)
                if cmd is None:
                    cmd = find_gradle_command(d)
                if cmd is None:
                    unrunnable_dirs.append(diagnose_java_build_dir(root, d))
                    continue
                cmd = cmd + ["test"]
                proc = run_tool(cmd, cwd=d, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
                out = proc.stdout + proc.stderr
                runs = re.findall(
                    r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)", out)
                if runs:
                    any_ran = True
                    total += sum(int(r[0]) for r in runs)
                    failures += sum(int(r[1]) for r in runs)
                    errors += sum(int(r[2]) for r in runs)
                    skipped_total += sum(int(r[3]) for r in runs)
            if not any_ran:
                detail = ("Found build file(s) but could not run/parse: " + "; ".join(unrunnable_dirs)) \
                    if unrunnable_dirs else \
                    "Found build file(s) but could not run/parse (build tool missing or not on PATH)"
                return {"status": "not_run", "passed": None, "failed": None,
                        "skipped": None, "detail": detail, **_cov_na_for_not_run(coverage, detail)}
            passed = total - failures - errors - skipped_total
            status = "failed" if (failures + errors) > 0 else ("passed" if passed > 0 else "no_tests")
            cov_result = _COVERAGE_NA
            if coverage:
                # Requires the JaCoCo plugin already configured in the
                # project's own pom.xml/build.gradle — we only look for the
                # report it would have produced during the `test` run above
                # (or try to generate one), we don't inject the plugin.
                cov_pcts = []
                cov_missing = []
                for d in build_dirs:
                    jacoco_csv = d / "target" / "site" / "jacoco" / "jacoco.csv"
                    jacoco_xml = d / "build" / "reports" / "jacoco" / "test" / "jacocoTestReport.xml"
                    if jacoco_csv.exists():
                        try:
                            lines = jacoco_csv.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]
                            covered = missed = 0
                            for ln in lines:
                                parts = ln.split(",")
                                if len(parts) > 4:
                                    missed += int(parts[3]); covered += int(parts[4])
                            if covered + missed > 0:
                                cov_pcts.append(100.0 * covered / (covered + missed))
                        except (OSError, ValueError, IndexError):
                            cov_missing.append(str(d.relative_to(root)))
                    elif jacoco_xml.exists():
                        try:
                            xml_text = jacoco_xml.read_text(encoding="utf-8", errors="ignore")
                            m = re.search(r'<counter type="LINE" missed="(\d+)" covered="(\d+)"/>\s*</report>', xml_text)
                            if m:
                                missed, covered = int(m.group(1)), int(m.group(2))
                                if covered + missed > 0:
                                    cov_pcts.append(100.0 * covered / (covered + missed))
                        except OSError:
                            cov_missing.append(str(d.relative_to(root)))
                    else:
                        cov_missing.append(str(d.relative_to(root)))
                cov_result = _cov_ok(sum(cov_pcts) / len(cov_pcts)) if cov_pcts else \
                    _cov_unavailable("no JaCoCo report found (JaCoCo plugin must be configured in "
                                      "pom.xml/build.gradle) in: " + ", ".join(cov_missing))
            return {"status": status, "passed": passed, "failed": failures + errors,
                    "skipped": skipped_total, "detail": None, **cov_result}

        if lang_key == "php":
            composer_dirs = find_manifest_dirs(root, ["composer.json"])
            if not composer_dirs:
                return {"status": "not_run", "passed": None, "failed": None,
                        "skipped": None, "detail": "No composer.json found"}
            total_passed = total_failed = total_skipped = 0
            any_ran = False
            missing_deps_dirs = []
            cov_pcts = []
            cov_details = []
            for d in composer_dirs:
                phpunit_bin = d / "vendor" / "bin" / ("phpunit.bat" if os.name == "nt" else "phpunit")
                artisan = d / "artisan"
                if not phpunit_bin.exists() and not artisan.exists():
                    if _ensure_composer_deps(d):
                        phpunit_bin = d / "vendor" / "bin" / (
                            "phpunit.bat" if os.name == "nt" else "phpunit")
                        artisan = d / "artisan"
                    if not phpunit_bin.exists() and not artisan.exists():
                        missing_deps_dirs.append(
                            str(d.relative_to(root)) + " (composer install failed)")
                        continue
                if artisan.exists():
                    cmd = [resolve_executable("php"), "artisan", "test"]
                else:
                    cmd = [str(phpunit_bin)]
                if coverage:
                    cmd.append("--coverage-text")
                proc = run_tool(cmd, cwd=d, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=600)
                out = proc.stdout + proc.stderr
                # PHPUnit: "OK (12 tests, 20 assertions)" or
                # "Tests: 12, Assertions: 20, Failures: 2, Skipped: 1"
                m = re.search(r"Tests:\s*(\d+),\s*Assertions:\s*\d+(?:,\s*Errors:\s*(\d+))?"
                               r"(?:,\s*Failures:\s*(\d+))?(?:,\s*Skipped:\s*(\d+))?", out)
                ok_m = re.search(r"OK\s*\((\d+)\s*tests?,", out)
                if m:
                    any_ran = True
                    t = int(m.group(1))
                    errors_n = int(m.group(2)) if m.group(2) else 0
                    failures_n = int(m.group(3)) if m.group(3) else 0
                    skipped_n = int(m.group(4)) if m.group(4) else 0
                    total_failed += errors_n + failures_n
                    total_skipped += skipped_n
                    total_passed += t - errors_n - failures_n - skipped_n
                elif ok_m:
                    any_ran = True
                    total_passed += int(ok_m.group(1))
                elif "No tests executed" in out or "OK, but" in out:
                    any_ran = True
                if coverage and any_ran:
                    cm = re.search(r"Lines:\s*([\d.]+)%", out)
                    if cm:
                        cov_pcts.append(float(cm.group(1)))
                    elif "Xdebug" in out or "pcov" in out.lower():
                        cov_details.append(f"{d.relative_to(root)}: coverage driver present but no % parsed")
                    else:
                        cov_details.append(f"{d.relative_to(root)}: no Xdebug/PCOV coverage driver available")
            if not any_ran:
                detail = ("vendor/bin/phpunit missing in: " + ", ".join(missing_deps_dirs) +
                           " — run with --install or `composer install` there first") if missing_deps_dirs \
                          else "Could not parse PHPUnit/Pest output"
                return {"status": "not_run", "passed": None, "failed": None,
                        "skipped": None, "detail": detail, **_cov_na_for_not_run(coverage, detail)}
            status = "failed" if total_failed > 0 else ("passed" if total_passed > 0 else "no_tests")
            cov_result = _COVERAGE_NA if not coverage else (
                _cov_ok(sum(cov_pcts) / len(cov_pcts)) if cov_pcts
                else _cov_unavailable("; ".join(cov_details) or "coverage not collected"))
            return {"status": status, "passed": total_passed, "failed": total_failed,
                    "skipped": total_skipped, "detail": None, **cov_result}

        if lang_key == "ruby":
            gem_dirs = find_manifest_dirs(root, ["Gemfile"])
            if not gem_dirs:
                return {"status": "not_run", "passed": None, "failed": None,
                        "skipped": None, "detail": "No Gemfile found"}
            total_passed = total_failed = total_skipped = 0
            any_ran = False
            cov_pcts = []
            cov_details = []
            for d in gem_dirs:
                if shutil.which("bundle") is None:
                    continue
                cmd = [resolve_executable("bundle"), "exec", "rspec"]
                proc = run_tool(cmd, cwd=d, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=600)
                out = proc.stdout + proc.stderr
                # "12 examples, 2 failures, 1 pending"
                m = re.search(r"(\d+)\s+examples?,\s*(\d+)\s+failures?(?:,\s*(\d+)\s+pending)?", out)
                if m:
                    any_ran = True
                    examples = int(m.group(1))
                    failures = int(m.group(2))
                    pending = int(m.group(3)) if m.group(3) else 0
                    total_failed += failures
                    total_skipped += pending
                    total_passed += examples - failures - pending
                if coverage and any_ran:
                    # Requires SimpleCov already set up in spec_helper.rb —
                    # we just read the report it produces, we don't inject it.
                    last_run = d / "coverage" / ".last_run.json"
                    if last_run.exists():
                        try:
                            data = json.loads(last_run.read_text(encoding="utf-8", errors="ignore"))
                            pct = data.get("result", {}).get("line")
                            if isinstance(pct, (int, float)):
                                cov_pcts.append(pct)
                        except (json.JSONDecodeError, OSError):
                            cov_details.append(f"{d.relative_to(root)}: could not parse .last_run.json")
                    else:
                        cov_details.append(f"{d.relative_to(root)}: no coverage/.last_run.json "
                                            f"(SimpleCov not configured in spec_helper.rb)")
            if not any_ran:
                return {"status": "not_run", "passed": None, "failed": None, "skipped": None,
                        "detail": "Could not run rspec (bundle not on PATH, or no output parsed — "
                                   "run with --install or `bundle install` first)", **_cov_na_for_not_run(coverage, "rspec could not run")}
            status = "failed" if total_failed > 0 else ("passed" if total_passed > 0 else "no_tests")
            cov_result = _COVERAGE_NA if not coverage else (
                _cov_ok(sum(cov_pcts) / len(cov_pcts)) if cov_pcts
                else _cov_unavailable("; ".join(cov_details) or "coverage not collected"))
            return {"status": status, "passed": total_passed, "failed": total_failed,
                    "skipped": total_skipped, "detail": None, **cov_result}

        if lang_key == "csharp":
            proj_dirs = []
            for dirpath, dirnames, files_here in os.walk(root):
                dirnames[:] = [dd for dd in dirnames if dd not in IGNORE_DIRS and not dd.startswith(".")]
                if any(fn.endswith(".sln") for fn in files_here) or \
                   any(fn.endswith(".csproj") for fn in files_here):
                    proj_dirs.append(Path(dirpath))
            if not proj_dirs:
                return {"status": "not_run", "passed": None, "failed": None,
                        "skipped": None, "detail": "No .csproj/.sln found"}
            if shutil.which("dotnet") is None:
                return {"status": "not_run", "passed": None, "failed": None,
                        "skipped": None, "detail": "dotnet SDK not installed / not on PATH", **_cov_na_for_not_run(coverage, "dotnet SDK not installed")}
            total_passed = total_failed = total_skipped = 0
            any_ran = False
            cov_pcts = []
            cov_details = []
            for d in proj_dirs:
                cmd = [resolve_executable("dotnet"), "test"]
                cov_out_dir = None
                if coverage:
                    cov_out_dir = d / "TestResults_coverage_tmp"
                    cmd += ["--collect:XPlat Code Coverage", "--results-directory", str(cov_out_dir)]
                proc = run_tool(cmd, cwd=d,
                                       capture_output=True, text=True, encoding="utf-8",
                                       errors="replace", timeout=900)
                out = proc.stdout + proc.stderr
                # "Passed!  - Failed: 0, Passed: 12, Skipped: 1, Total: 13"
                for m in re.finditer(r"Failed:\s*(\d+),\s*Passed:\s*(\d+),\s*Skipped:\s*(\d+),\s*Total:\s*(\d+)", out):
                    any_ran = True
                    total_failed += int(m.group(1))
                    total_passed += int(m.group(2))
                    total_skipped += int(m.group(3))
                if coverage and any_ran and cov_out_dir and cov_out_dir.exists():
                    # coverlet (bundled with dotnet test SDK collectors) writes
                    # coverage.cobertura.xml with a line-rate attribute (0-1).
                    xml_files = list(cov_out_dir.rglob("coverage.cobertura.xml"))
                    if xml_files:
                        try:
                            xml_text = xml_files[0].read_text(encoding="utf-8", errors="ignore")
                            m2 = re.search(r'line-rate="([\d.]+)"', xml_text)
                            if m2:
                                cov_pcts.append(float(m2.group(1)) * 100)
                        except OSError:
                            cov_details.append(f"{d.relative_to(root)}: could not parse coverage.cobertura.xml")
                    else:
                        cov_details.append(f"{d.relative_to(root)}: no coverage.cobertura.xml produced "
                                            f"(coverlet.collector package may not be referenced)")
            if not any_ran:
                return {"status": "not_run", "passed": None, "failed": None, "skipped": None,
                        "detail": "Found .csproj/.sln but could not run/parse `dotnet test` output",
                        **_cov_na_for_not_run(coverage, "dotnet test output could not be parsed")}
            status = "failed" if total_failed > 0 else ("passed" if total_passed > 0 else "no_tests")
            cov_result = _COVERAGE_NA if not coverage else (
                _cov_ok(sum(cov_pcts) / len(cov_pcts)) if cov_pcts
                else _cov_unavailable("; ".join(cov_details) or "coverage not collected"))
            return {"status": status, "passed": total_passed, "failed": total_failed,
                    "skipped": total_skipped, "detail": None, **cov_result}

        if lang_key == "rust":
            cargo_dirs = find_manifest_dirs(root, ["Cargo.toml"])
            if not cargo_dirs:
                return {"status": "not_run", "passed": None, "failed": None,
                        "skipped": None, "detail": "No Cargo.toml found"}
            if shutil.which("cargo") is None:
                return {"status": "not_run", "passed": None, "failed": None,
                        "skipped": None, "detail": "cargo not installed / not on PATH", **_cov_na_for_not_run(coverage, "cargo not installed")}
            total_passed = total_failed = total_skipped = 0
            any_ran = False
            cov_pcts = []
            cov_details = []
            for d in cargo_dirs:
                proc = run_tool([resolve_executable("cargo"), "test"], cwd=d,
                                       capture_output=True, text=True, encoding="utf-8",
                                       errors="replace", timeout=900)
                out = proc.stdout + proc.stderr
                # "test result: ok. 12 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out"
                for m in re.finditer(
                        r"test result:.*?(\d+)\s+passed;\s*(\d+)\s+failed;\s*(\d+)\s+ignored", out):
                    any_ran = True
                    total_passed += int(m.group(1))
                    total_failed += int(m.group(2))
                    total_skipped += int(m.group(3))
                if coverage and any_ran:
                    # Requires cargo-tarpaulin installed separately
                    # (`cargo install cargo-tarpaulin`) — it's not part of
                    # stock cargo, so we invoke it as its own subcommand.
                    tproc = run_tool(
                        [resolve_executable("cargo"), "tarpaulin", "--skip-clean", "--out", "Stdout"],
                        cwd=d, capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=900)
                    tout = tproc.stdout + tproc.stderr
                    if "no such subcommand" in tout.lower() or tproc.returncode != 0 and "tarpaulin" not in tout.lower():
                        cov_details.append(f"{d.relative_to(root)}: cargo-tarpaulin not installed "
                                            f"(cargo install cargo-tarpaulin)")
                    else:
                        cm = re.search(r"(\d+\.\d+)%\s+coverage", tout)
                        if cm:
                            cov_pcts.append(float(cm.group(1)))
                        else:
                            cov_details.append(f"{d.relative_to(root)}: could not parse tarpaulin output")
            if not any_ran:
                return {"status": "not_run", "passed": None, "failed": None, "skipped": None,
                        "detail": "Found Cargo.toml but could not run/parse `cargo test` output",
                        **_cov_na_for_not_run(coverage, "cargo test output could not be parsed")}
            status = "failed" if total_failed > 0 else ("passed" if total_passed > 0 else "no_tests")
            cov_result = _COVERAGE_NA if not coverage else (
                _cov_ok(sum(cov_pcts) / len(cov_pcts)) if cov_pcts
                else _cov_unavailable("; ".join(cov_details) or "coverage not collected"))
            return {"status": status, "passed": total_passed, "failed": total_failed,
                    "skipped": total_skipped, "detail": None, **cov_result}

    except subprocess.TimeoutExpired:
        return {"status": "not_run", "passed": None, "failed": None,
                "skipped": None, "detail": "Timed out", **_cov_na_for_not_run(coverage, "test run timed out")}
    except Exception as e:
        return {"status": "not_run", "passed": None, "failed": None,
                "skipped": None, "detail": f"Error: {e}", **_cov_na_for_not_run(coverage, f"error running tests: {e}")}

    return result_default



def resolve_executable(name: str) -> str:
    """
    Resolve a command name to its real, invocable path. Critical on
    Windows, where npm/npx/mvn/gradle are actually .cmd/.bat shim files —
    run_tool(["npm", ...]) with shell=False fails with WinError 2
    there unless given the fully resolved path (shutil.which() correctly
    checks PATHEXT, including .cmd/.bat, on Windows).

    On Windows we explicitly look for name+".cmd" / name+".bat" first,
    before falling back to a bare shutil.which(name). This sidesteps a
    real-world gotcha: if PATHEXT has a stray empty entry (e.g. from a
    leading/trailing ';', which some installers/users introduce), plain
    shutil.which("npm") can resolve to the extensionless POSIX/shebang
    "npm" shim that Node.js ships alongside npm.cmd (intended for
    WSL/Git Bash) instead of npm.cmd itself. That file isn't a valid
    Win32 executable, so invoking it directly fails with WinError 193.
    Preferring the explicit .cmd/.bat match avoids depending on PATHEXT
    ordering at all. (run_tool() also has a fallback retry for this, but
    resolving correctly here avoids relying on that fallback firing.)
    """
    if os.name == "nt":
        for ext in (".cmd", ".bat", ".exe"):
            found = shutil.which(name + ext)
            if found:
                return found
    found = shutil.which(name)
    return found if found else name


def find_mvn_command(d: Path) -> Optional[List[str]]:
    """Return the invocable Maven command for directory d, preferring the
    project's own wrapper script (mvnw / mvnw.cmd) over a global `mvn`."""
    wrapper = d / ("mvnw.cmd" if os.name == "nt" else "mvnw")
    if wrapper.exists():
        return [str(wrapper)]
    resolved = shutil.which("mvn")
    return [resolved] if resolved else None


def find_gradle_command(d: Path) -> Optional[List[str]]:
    """Return the invocable Gradle command for directory d, preferring the
    project's own wrapper script (gradlew / gradlew.bat) over global `gradle`."""
    wrapper = d / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if wrapper.exists():
        return [str(wrapper)]
    resolved = shutil.which("gradle")
    return [resolved] if resolved else None



def diagnose_java_build_dir(root: Path, d: Path) -> str:
    """
    Explain precisely why no runnable Maven/Gradle command was found in
    directory d, instead of just saying 'build tool missing or not on PATH'.
    Distinguishes: no build file at all, wrapper committed for the wrong
    OS (e.g. only Unix mvnw/gradlew present on Windows, or vice versa),
    and no wrapper + no global mvn/gradle install.
    """
    rel = d.relative_to(root)
    has_pom = (d / "pom.xml").exists()
    has_gradle = (d / "build.gradle").exists() or (d / "build.gradle.kts").exists()
    build_files = [n for n, present in (("pom.xml", has_pom), ("build.gradle*", has_gradle)) if present]

    has_mvnw_unix = (d / "mvnw").exists()
    has_mvnw_win = (d / "mvnw.cmd").exists()
    has_gradlew_unix = (d / "gradlew").exists()
    has_gradlew_win = (d / "gradlew.bat").exists()
    global_mvn = shutil.which("mvn") is not None
    global_gradle = shutil.which("gradle") is not None

    reasons = []
    on_windows = os.name == "nt"
    wrong_platform_wrapper = (
        (on_windows and (has_mvnw_unix or has_gradlew_unix) and not (has_mvnw_win or has_gradlew_win)) or
        (not on_windows and (has_mvnw_win or has_gradlew_win) and not (has_mvnw_unix or has_gradlew_unix))
    )
    if wrong_platform_wrapper:
        reasons.append("repo only committed the wrapper script for the other OS "
                        "(e.g. mvnw/gradlew without the matching .cmd/.bat, or vice versa)")
    if not any([has_mvnw_unix, has_mvnw_win, has_gradlew_unix, has_gradlew_win]):
        if global_mvn or global_gradle:
            reasons.append("no wrapper script committed, and the globally installed "
                            "mvn/gradle could not be resolved for this project")
        else:
            reasons.append("no wrapper script committed and no global mvn/gradle found on PATH")

    detail = f"{rel} (has {', '.join(build_files) if build_files else 'no recognized build file'})"
    if reasons:
        detail += " — " + "; ".join(reasons)
    return detail


def find_manifest_dirs(root: Path, filenames: List[str]) -> List[Path]:
    """Find every directory (excluding IGNORE_DIRS) containing any of the
    given manifest filenames, e.g. package.json, pom.xml, go.mod."""
    dirs = []
    for dirpath, dirnames, files_here in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in files_here:
            if fn in filenames:
                dirs.append(Path(dirpath))
                break
    return dirs

def _sum_regex(pattern: str, text: str) -> int:
    matches = re.findall(pattern, text)
    return sum(int(m) for m in matches) if matches else 0


# ---------------------------------------------------------------------------
# Project analysis (provider-agnostic)
# ---------------------------------------------------------------------------

# GitLab/GitHub /languages API returns human display names (from linguist),
# e.g. "Python", "TypeScript", "Vue", "HTML". Map these onto the lang_key
# values run_test_suite_status() understands. Anything not in this map
# (e.g. C/C++, Kotlin, Swift, Dart, Shell, HTML/CSS) simply has no native
# coverage tooling wired up here — coverage stays blank for those, same as
# it already did for every non-Python language before this change.
LANG_KEY_MAP = {
    "python": "python",
    "javascript": "js", "typescript": "js",
    # Linguist sometimes reports the template/framework flavor as its own
    # "language" instead of the underlying one PHPUnit/Jest actually run
    # against — map those onto the real coverage-tool language too.
    "vue": "js", "jsx": "js", "tsx": "js",
    "java": "java",
    "go": "go", "golang": "go",
    "php": "php", "blade": "php",
    "ruby": "ruby",
    "c#": "csharp", "csharp": "csharp",
    "rust": "rust",
}


def detect_repo_lang_key(root_path):
    """Best-effort lang_key detection for a repo already on disk, used when
    we don't already have a GitLab/GitHub-reported primary_language (or want
    to double check it actually has the matching manifest/build file)."""
    checks = [
        ("python", ["requirements.txt", "setup.py", "pyproject.toml"]),
        ("js", ["package.json"]),
        ("go", ["go.mod"]),
        ("java", ["pom.xml", "build.gradle", "build.gradle.kts"]),
        ("php", ["composer.json"]),
        ("ruby", ["Gemfile"]),
        ("csharp", None),  # detected via *.csproj/*.sln glob below
        ("rust", ["Cargo.toml"]),
    ]
    for lang_key, manifests in checks:
        if manifests is None:
            if list(Path(root_path).rglob("*.csproj")) or list(Path(root_path).rglob("*.sln")):
                return "csharp"
            continue
        if find_manifest_dirs(Path(root_path), manifests):
            return lang_key
    return ""


def measure_multilang_coverage(root_path, primary_language, timeout=600):
    """Run the real, language-native coverage tool against a repo already on
    disk (local checkout or a fresh shallow clone) and return the coverage
    percentage as a float, or '' if it couldn't be measured (unsupported
    language, tool/deps missing, tests didn't run, or no coverage report
    could be parsed). This is the multi-language replacement for the old
    Python-only measure_local_pytest_coverage()."""
    lang_key = LANG_KEY_MAP.get((primary_language or "").strip().lower(), "")
    if not lang_key:
        lang_key = detect_repo_lang_key(root_path)
    if not lang_key:
        return ""
    try:
        res = run_test_suite_status(Path(root_path), lang_key,
                                    no_run=False, coverage=True)
    except Exception as e:
        print(f"    [warn] coverage run failed: {e}")
        return ""
    pct = res.get("coverage_percent")
    if isinstance(pct, (int, float)):
        return pct
    print(f"    [debug] coverage not measured (lang={lang_key}): "
          f"{res.get('coverage_detail', 'no detail available')}")
    return ""


def _clone_with_auth(web_url, token, tmp_dir, timeout=180):
    """Clone without ever putting the token in argv or in the on-disk
    .git/config — a URL-embedded token (the old approach) sits in plain
    argv for the whole clone duration (visible via `ps`/Task Manager to
    any other user on the box) and gets written into .git/config until the
    temp dir is removed. Instead we hand the token to git through
    GIT_ASKPASS, which keeps it out of argv and out of any file that
    outlives the clone. Public repos clone fine even without a token."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    askpass_file = None
    try:
        if token and web_url.startswith("https://"):
            suffix = ".cmd" if os.name == "nt" else ".sh"
            fd, askpass_file = tempfile.mkstemp(prefix="askpass_", suffix=suffix)
            with os.fdopen(fd, "w") as f:
                if os.name == "nt":
                    f.write(f"@echo off\r\necho {token}\r\n")
                else:
                    f.write(f"#!/bin/sh\necho '{token}'\n")
            if os.name != "nt":
                os.chmod(askpass_file, 0o700)
            env["GIT_ASKPASS"] = askpass_file
        return subprocess.run(
            ["git", "clone", "--depth", "1", web_url, tmp_dir],
            capture_output=True, text=True, timeout=timeout, errors="replace",
            env=env)
    finally:
        if askpass_file:
            try:
                os.remove(askpass_file)
            except OSError:
                pass


def measure_remote_pytest_coverage(web_url, kind, token, primary_language="",
                                   timeout=600):
    """Shallow-clone a GitLab/GitHub repo into a throwaway temp dir and run
    the real, language-native coverage tool against it (multi-language —
    see measure_multilang_coverage). Returns '' (blank) if git isn't
    available, the clone fails/times out, the language has no coverage
    tooling wired up, or no coverage could be measured/parsed. The temp
    clone is always deleted afterwards, success or failure."""
    with tempfile.TemporaryDirectory(prefix="repo_cov_") as tmp_dir:
        try:
            r = _clone_with_auth(web_url, token, tmp_dir, timeout=180)
        except subprocess.TimeoutExpired:
            print(f"    [debug] clone timed out after 180s: {web_url}")
            return ""
        except FileNotFoundError:
            print("    [debug] git executable not found — is git installed "
                  "and on PATH?")
            return ""
        if r.returncode != 0:
            # Mask the token if it leaked into stderr before printing.
            safe_stderr = (r.stderr or "").replace(token or "\x00", "***") \
                if token else (r.stderr or "")
            print(f"    [debug] git clone failed (exit {r.returncode}): "
                  f"{safe_stderr.strip()[:300] or 'no stderr output'}")
            return ""
        return measure_multilang_coverage(tmp_dir, primary_language, timeout=timeout)


def analyze_project(prov, project_id, max_mrs, sample_mrs,
                    max_test_files, workers=8, max_commit_scan=0,
                    max_ai_file_scan=0, max_quality_scan=0, max_loc_sample=0,
                    skip_local_coverage=False, skip_remote_coverage=False):
    info = prov.project_info(project_id)
    if info is None:
        print(f"  Project not found: {project_id}")
        return None
    name = info["name"]
    print(f"\n=== {name} ===")

    result = {
        "repo": name,
        "provider": prov.kind,
        "visibility": info["visibility"],
        "created_at": info["created_at"],
        "last_activity": info["last_activity"],
        "default_branch": info["default_branch"],
        "commits": info["commits"],
    }

    # Real first/last commit dates (created_at/last_activity above are the
    # platform's repo-creation / last-push timestamps, which can differ a lot)
    try:
        result["first_commit"], result["last_commit"] = prov.commit_dates(info)
    except SystemExit:
        raise
    except Exception as e:
        print(f"  [warn] commit dates unavailable: {e}")
        result["first_commit"] = result["last_commit"] = ""

    # Languages
    langs = prov.languages(info)
    result["languages"] = langs
    result["primary_language"] = max(langs, key=langs.get) if langs else ""

    # Contributors
    print("  Contributors...")
    contribs = prov.contributors(info)
    result["contributors"] = len(contribs)
    result["human_contributors"] = len(
        [c for c in contribs
         if not is_bot((c.get("name") or "") + " " + (c.get("id") or ""))])

    # MRs / PRs
    print(f"  {prov.mr_word} fetch"
          + (f" (max {max_mrs})..." if max_mrs else " (ALL)..."))
    mrs = prov.merge_requests(info, max_mrs)

    if not mrs and prov.kind == "local":
        # An offline repo has no real MR/PR history — only their traces
        # can be detected from git history. Showing 0 when nothing was found
        # would be wrong — hence blank + a note.
        print("    [note] no MR/PR detected in git history — "
              "MR fields will stay blank. (To also count merge commits use "
              "--local-mrs merges; for exact counts use --provider "
              "gitlab/github)")
        result["total_mrs"] = ""
        result["merged_mrs"] = ""
        result["mrs_note"] = "not detectable from git history"
        for key in ("pct_simple", "pct_standard", "pct_rich",
                    "pct_automated", "pct_other", "avg_loc_per_mr"):
            result[key] = ""
        result["mr_sample_size"] = 0
    else:
        result["total_mrs"] = len(mrs)
        result["merged_mrs"] = len([m for m in mrs if m.get("merged")])
        if prov.kind == "local":
            result["mrs_note"] = ("estimated from git history — "
                                  "for an exact count use the GitLab/GitHub "
                                  "API provider")

    # MR categorization — sample_mrs=0 means ALL will be deep-analyzed
    if mrs:
        _categorize_mrs(prov, info, mrs, sample_mrs, workers, result)

    # Fetch the file tree only once (used by files/CI/tests and LLM detection)
    print("  Repository file tree...")
    all_paths = prov.tree(info)
    content_cache = {}   # avoid fetching a file twice (LLM + quality scan)

    _analyze_files_ci_tests(prov, info, all_paths, max_test_files,
                            workers, result,
                            skip_local_coverage=skip_local_coverage,
                            skip_remote_coverage=skip_remote_coverage,
                            max_loc_sample=max_loc_sample)
    commits = _analyze_llm_usage(prov, info, mrs, all_paths, result,
                                 max_commit_scan, max_ai_file_scan, workers,
                                 content_cache)
    _detect_company_info(prov, info, all_paths, commits, content_cache,
                         result)
    _analyze_training_quality(prov, info, all_paths, result,
                              max_quality_scan, workers, content_cache)
    _analyze_swe_quality(result)
    return result


def _categorize_mrs(prov, info, mrs, sample_mrs, workers, result):
    """Split MRs/PRs into simple/standard/rich/automated (writes into result)."""
    to_analyze = mrs if not sample_mrs else mrs[:sample_mrs]
    print(f"  Categorization ({len(to_analyze)} {prov.mr_word}, "
          f"{workers} parallel)...")
    cats = Counter()
    loc_list = []

    def classify_mr(mr):
        if is_bot(mr.get("author", "")):
            return "automated", 0, False
        title = mr.get("title", "")
        desc = (mr.get("description") or "") + " " + title
        linked = matches_any(desc, ISSUE_LINK_PATTERNS)

        a = prov.mr_analysis(info, mr)
        notes, n_files = a["notes"], a["n_files"]
        loc, touches_tests = a["loc"], a["touches_tests"]
        # loc_known distinguishes "the diff fetch failed" (exclude from the
        # average — an unknown isn't a zero) from "the diff genuinely has
        # zero changed lines" (a real data point, keep it). Providers that
        # don't set it (older/custom ones) default to "known" so behavior
        # doesn't regress.
        loc_known = a.get("loc_known", True)

        substantive = notes >= 3
        simple_title = matches_any(title, SIMPLE_FIX_TITLE_PATTERNS)

        if linked and substantive:
            cat = "rich"
        elif n_files <= 2 and notes == 0 and (simple_title or loc <= 50):
            cat = "simple"
        elif 3 <= n_files <= 10 and (touches_tests or linked):
            cat = "standard"
        elif n_files <= 2:
            cat = "simple"
        elif 3 <= n_files <= 10:
            cat = "standard"
        else:
            cat = "other"
        return cat, loc, loc_known

    done = 0
    pool_workers = workers if prov.kind != "local" else min(workers, 4)
    with ThreadPoolExecutor(max_workers=pool_workers) as pool:
        futures = [pool.submit(classify_mr, mr) for mr in to_analyze]
        for fut in as_completed(futures):
            try:
                cat, loc, loc_known = fut.result()
                cats[cat] += 1
                if loc_known:
                    loc_list.append(loc)
            except Exception as e:
                cats["other"] += 1
                print(f"    [warn] classify fail: {e}")
            done += 1
            if done % 100 == 0:
                print(f"    ...{done}/{len(to_analyze)} done")

    n = sum(cats.values()) or 1
    result["pct_simple"] = round(100 * cats["simple"] / n, 1)
    result["pct_standard"] = round(100 * cats["standard"] / n, 1)
    result["pct_rich"] = round(100 * cats["rich"] / n, 1)
    result["pct_automated"] = round(100 * cats["automated"] / n, 1)
    result["pct_other"] = round(100 * cats["other"] / n, 1)
    result["avg_loc_per_mr"] = (round(sum(loc_list) / len(loc_list), 1)
                                if loc_list else "")
    result["mr_sample_size"] = n


def _analyze_files_ci_tests(prov, info, all_paths, max_test_files,
                            workers, result, skip_local_coverage=False,
                            skip_remote_coverage=False, max_loc_sample=0):
    """File tree, CI/CD analysis, and test genuineness (writes into result)."""
    pool_workers = workers if prov.kind != "local" else min(workers, 4)

    # ---- Files: source + test detection ----
    all_code = [p for p in all_paths if is_code_file(p)]
    test_paths = [p for p in all_code if is_test_path(p)]
    source_paths = [p for p in all_code if not is_test_path(p)]
    result["source_files"] = len(source_paths)
    result["test_files"] = len(test_paths)

    # ---- Untested files (NEW): source files with no matched test ----
    # Two coverage patterns are recognized:
    #  1. Per-file:   foo.ts <-> foo.test.ts / test_foo.py / FooTest.java
    #  2. Per-module: a test file named after its own containing folder
    #     (e.g. resources/agents/agents.test.ts) is common in codebases that
    #     write one test file per module/feature folder rather than one per
    #     source file — every source file in that folder counts as covered,
    #     not just a file that happens to be named "agents.ts".
    test_stems = {_file_subject_stem(tp) for tp in test_paths}
    test_stems.discard("")
    covered_dirs = set()
    for tp in test_paths:
        folder = tp.rsplit("/", 1)[0] if "/" in tp else ""
        folder_name = folder.rsplit("/", 1)[-1].lower() if folder else ""
        if folder_name and _file_subject_stem(tp) == folder_name:
            covered_dirs.add(folder)
    untested = []
    for sp in source_paths:
        if _file_subject_stem(sp) in test_stems:
            continue
        folder = sp.rsplit("/", 1)[0] if "/" in sp else ""
        if folder in covered_dirs:
            continue
        untested.append(sp)
    result["untested_source_files"] = len(untested)
    result["pct_untested_files"] = (
        round(100 * len(untested) / len(source_paths), 1)
        if source_paths else "")

    if prov.kind != "local":
        if max_loc_sample == -1:
            cap = len(all_code) or 1   # unbounded: fetch every file, exact
            print(f"  LoC (fetching ALL {len(all_code)} code files via "
                  f"API — no sampling, this can take a while and use "
                  f"many API calls)...")
        else:
            cap = max_loc_sample if max_loc_sample > 0 else 300
            print(f"  LoC (sampling up to {cap} of {len(all_code)} code "
                  f"files via API)...")
        result["total_loc_estimate"] = prov.loc_estimate(
            info, all_code, sample_cap=cap)
    else:
        result["total_loc_estimate"] = prov.loc_estimate(info, all_code)
    print(f"    {len(all_code)} code files: {len(source_paths)} source, "
          f"{len(test_paths)} test")

    # ---- CI/CD analysis (NEW) ----
    print("  CI/CD analysis...")
    ci_configs = detect_ci_configs(all_paths)
    result["ci_configured"] = "Yes" if ci_configs else "No"
    result["ci_systems"] = sorted(ci_configs.keys())
    result["ci_config_files"] = sum(len(v) for v in ci_configs.values())

    ci_jobs, ci_stages = 0, 0
    for system, paths in ci_configs.items():
        for cp in paths[:10]:          # read at most 10 configs per system
            content = prov.file_content(info, cp)
            if content:
                a = analyze_ci_config(system, content)
                ci_jobs += a["jobs"]
                ci_stages += a["stages"]
    result["ci_jobs_approx"] = ci_jobs if ci_configs else ""
    result["ci_stages_approx"] = ci_stages if ci_configs else ""

    stats = prov.ci_stats(info)
    result["ci_pipelines_total"] = stats.get("pipelines_total", "")
    result["ci_success_rate"] = stats.get("success_rate", "")
    result["ci_avg_duration_min"] = stats.get("avg_duration_min", "")

    # Coverage is kept as three separate, provider-specific fields:
    #   - GitLab: first tries the project's pipeline coverage (API, free —
    #     only works if .gitlab-ci.yml has a `coverage:` regex configured).
    #     If that's blank, falls back to shallow-cloning the repo and
    #     ACTUALLY RUNNING `pytest --cov` against it (real measurement,
    #     same technique as the local-repo path below).
    #   - GitHub: GitHub Actions doesn't expose a coverage number via the
    #     API at all, so this ALWAYS falls back to the same clone + real
    #     `pytest --cov` run.
    #   - Both remote fallbacks can be skipped with --skip-remote-coverage
    #     (they clone the repo and execute its code — Python, JS/TS, Go,
    #     Java, PHP, Ruby, C#, and Rust are supported; other languages have
    #     no native coverage tool wired up and stay blank).
    #   - Local Repo: ACTUALLY MEASURED by running each language's native
    #     coverage tool against the repo on disk (same multi-language
    #     engine as repo_test_auditor.py) — this is the only field that
    #     runs real code, so it only applies when analyzing a local repo
    #     and can be skipped with --skip-local-coverage
    result["coverage_pct_gitlab"] = ""
    result["coverage_pct_github"] = ""
    primary_language = result.get("primary_language", "")
    if prov.kind in ("gitlab", "github"):
        api_cov = stats.get("coverage_pct", "") if prov.kind == "gitlab" else ""
        field = "coverage_pct_gitlab" if prov.kind == "gitlab" else "coverage_pct_github"
        if api_cov != "":
            result[field] = api_cov
        elif skip_remote_coverage:
            result[field] = ""
        else:
            web_url = info.get("web_url", "")
            if not web_url:
                result[field] = ""
            else:
                print(f"    Cloning + running test suite for real "
                      f"coverage % ({prov.kind}, {primary_language or 'unknown language'})...")
                result[field] = measure_remote_pytest_coverage(
                    web_url, prov.kind, getattr(prov, "token", None),
                    primary_language=primary_language)
                if result[field] == "":
                    print("    [note] remote coverage could not be "
                          "measured — clone failed, unsupported language, "
                          "coverage tool/deps missing, no tests found, the "
                          "run timed out, or the coverage report couldn't "
                          "be parsed")
                else:
                    print(f"    {prov.kind.capitalize()} coverage (measured): "
                          f"{result[field]}%")
    if prov.kind == "local":
        if skip_local_coverage:
            result["coverage_pct_local"] = ""
        else:
            print(f"    Running local test suite for real coverage % "
                  f"({primary_language or 'unknown language'})...")
            result["coverage_pct_local"] = measure_multilang_coverage(
                info["id"], primary_language)
            if result["coverage_pct_local"] == "":
                print("    [note] local coverage could not be measured — "
                      "unsupported language, coverage tool/deps missing, "
                      "no tests found, the run timed out, or the coverage "
                      "report couldn't be parsed")
            else:
                print(f"    Local coverage: "
                      f"{result['coverage_pct_local']}%")
    else:
        result["coverage_pct_local"] = ""

    if "ci_commits" in stats:
        result["ci_commits"] = stats["ci_commits"]
    if ci_configs:
        print(f"    CI systems: {', '.join(result['ci_systems'])} "
              f"({result['ci_config_files']} config files, "
              f"~{ci_jobs} jobs)")
        if result["ci_success_rate"] != "":
            print(f"    Recent pipeline success rate: "
                  f"{result['ci_success_rate']}%")
    else:
        print("    No CI/CD config found")

    # ---- Test genuineness analysis (parallel content fetch) ----
    if max_test_files == 0:   # auto: ALL locally, 200 via API
        max_test_files = 10**9 if prov.kind == "local" else 200
    print(f"  Test genuineness check "
          f"({min(len(test_paths), max_test_files)} files)...")
    test_cases = 0
    assertions_total = 0
    genuine_files = 0
    suspicious_files = 0
    misnamed_files = 0
    suspicious_list = []

    def check_test_file(tp):
        content = prov.file_content(info, tp)
        if content is None:
            return tp, None
        return tp, analyze_test_content(content)

    with ThreadPoolExecutor(max_workers=pool_workers) as pool:
        futures = [pool.submit(check_test_file, tp)
                   for tp in test_paths[:max_test_files]]
        for fut in as_completed(futures):
            try:
                tp, tinfo = fut.result()
            except Exception:
                continue
            if tinfo is None:
                continue
            test_cases += tinfo["cases"]
            assertions_total += tinfo["assertions"]
            if tinfo["verdict"] == "genuine":
                genuine_files += 1
            elif tinfo["verdict"] == "suspicious":
                suspicious_files += 1
                suspicious_list.append(
                    {"file": tp, "cases": tinfo["cases"],
                     "assertions": tinfo["assertions"],
                     "trivial": tinfo["trivial"], "skipped": tinfo["skipped"]})
            else:
                misnamed_files += 1

    checked = min(len(test_paths), max_test_files)
    if len(test_paths) > max_test_files and checked:
        scale = len(test_paths) / checked
        test_cases = int(test_cases * scale)
        result["test_cases_note"] = "extrapolated"

    # ---- Content-based correction ----
    # A file living in a test folder that contains NOT A SINGLE test case
    # (misnamed) is really a source/support file. Adjust the counts so that
    # "Test files" only includes actual test files.
    if checked:
        scale = len(test_paths) / checked
        est_misnamed = int(round(misnamed_files * scale))
        result["test_files"] = max(0, len(test_paths) - est_misnamed)
        result["source_files"] = len(source_paths) + est_misnamed
        if est_misnamed:
            print(f"    [adjust] {est_misnamed} files were in test folders but "
                  f"contained no test cases — moved to source")

    result["test_cases"] = test_cases
    result["assertions"] = assertions_total
    result["genuine_test_files"] = genuine_files
    result["suspicious_test_files"] = suspicious_files
    result["misnamed_test_files"] = misnamed_files
    result["pct_test_to_code_ratio"] = (
        round(100 * result["test_files"] / result["source_files"], 1)
        if result["source_files"] else "")
    # % genuine = share of genuine among real test files (genuine+suspicious).
    # Misnamed files used to be in the denominator too — the % came out too low.
    real_tests_checked = genuine_files + suspicious_files
    result["pct_genuine_tests"] = (
        round(100 * genuine_files / real_tests_checked, 1)
        if real_tests_checked else "")
    result["suspicious_tests_detail"] = suspicious_list[:50]
    if suspicious_files:
        print(f"    [!] found {suspicious_files} SUSPICIOUS test files "
              f"(no real assertions / all skipped) — details in the JSON")
    return result


# ---------------------------------------------------------------------------
# AI / LLM usage analysis (NEW)
# ---------------------------------------------------------------------------

def _pct(num, den):
    """Percentage with adaptive precision — show 1/2201 as 0.05, not 0.0."""
    if not den:
        return ""
    p = 100 * num / den
    if num and round(p, 1) == 0.0:
        return max(round(p, 2), 0.01)
    return round(p, 1)


def _analyze_llm_usage(prov, info, mrs, all_paths, result,
                       max_commit_scan, max_ai_file_scan, workers,
                       content_cache=None):
    """Detect AI/LLM usage in the repo (writes into result).

    Sources:
      commits  -> trailers/messages/authors     (main basis for LLM usage %)
      MRs/PRs  -> descriptions/authors          (secondary %)
      tree     -> AI tool config files          (which tools are set up)
      code     -> attribution comments (sample) (extra evidence)

    Returns the fetched commit list so callers (e.g. company detection,
    which also needs commit author emails) can reuse it instead of
    re-fetching — on API providers a second full fetch would double the
    pagination cost.
    """
    if content_cache is None:
        content_cache = {}
    print("  AI/LLM detection...")
    llm_commit_counts = Counter()   # LLM -> number of commits
    llm_mr_counts = Counter()       # LLM -> number of MRs
    evidence = []                   # samples for the detail JSON

    # ---- 1. Commits scan ----
    commits = []
    try:
        commits = prov.commit_log(info, max_commit_scan) or []
    except Exception as e:
        print(f"    [warn] commit scan fail: {e}")
    repo_web_url = (info.get("web_url") or "").rstrip("/")

    def commit_url(sha):
        """Link to the exact commit, if the web_url is known (GitLab/GitHub)."""
        if not sha or not repo_web_url:
            return ""
        if prov.kind == "gitlab":
            return f"{repo_web_url}/-/commit/{sha}"
        if prov.kind == "github":
            return f"{repo_web_url}/commit/{sha}"
        return ""

    ai_commits = 0
    for c in commits:
        hits = detect_llms_in_text(c.get("message", ""))
        bot = detect_llm_author((c.get("author", "") or "")
                                + " " + (c.get("email", "") or ""))
        if bot:
            hits.add(bot)
        if hits:
            ai_commits += 1
            for h in hits:
                llm_commit_counts[h] += 1
            if len(evidence) < 30:
                first_line = (c.get("message", "").splitlines() or [""])[0]
                sha = c.get("sha", "")
                # EXACT LOCATION: commit sha (+ web link when available)
                loc = sha[:12] if sha else ""
                url = commit_url(sha)
                if url:
                    loc = url
                evidence.append({"source": "commit",
                                 "llm": sorted(hits),
                                 "sample": first_line[:100],
                                 "location": loc})
    scanned = len(commits)
    result["llm_commits_scanned"] = scanned
    result["llm_ai_commits"] = ai_commits
    result["llm_pct_commits"] = _pct(ai_commits, scanned)

    # ---- 2. MRs/PRs scan (already fetched — no extra API calls) ----
    ai_mrs = 0
    for m in (mrs or []):
        text = (m.get("title", "") or "") + "\n" + (m.get("description", "") or "")
        hits = detect_llms_in_text(text)
        bot = detect_llm_author(m.get("author", ""))
        if bot:
            hits.add(bot)
        if hits:
            ai_mrs += 1
            for h in hits:
                llm_mr_counts[h] += 1
            if len(evidence) < 50:
                # EXACT LOCATION: web link when available (GitLab/GitHub),
                # otherwise the real MR/PR/commit display id from local mode
                # (never the raw internal git SHA stored in "number")
                loc = m.get("url", "") or m.get("display_id", "")
                evidence.append({"source": "mr/pr",
                                 "llm": sorted(hits),
                                 "sample": (m.get("title", "") or "")[:100],
                                 "location": loc})
    n_mrs = len(mrs or [])
    result["llm_ai_mrs"] = ai_mrs if n_mrs else ""
    result["llm_pct_mrs"] = _pct(ai_mrs, n_mrs)

    # ---- 3. AI tool config files (from the tree — free) ----
    tool_configs = detect_ai_tool_configs(all_paths)
    result["ai_tool_configs"] = sorted(tool_configs.keys())
    result["ai_tool_config_files"] = sum(len(v) for v in tool_configs.values())
    for tool, paths in tool_configs.items():
        evidence.append({"source": "config-file", "llm": [tool],
                         "sample": "; ".join(paths[:3]),
                         "location": "; ".join(paths[:3])})

    # ---- 4. Code comments scan (sample of source files) ----
    if max_ai_file_scan == 0:   # auto
        if prov.kind == "local":
            # Reading from local disk is cheap — scan ALL code files
            max_ai_file_scan = 10**9
        else:
            max_ai_file_scan = 30
    code_paths = [p for p in all_paths if is_code_file(p)]
    llm_code_files = Counter()
    ai_code_files = 0
    files_scanned = 0
    if max_ai_file_scan > 0 and code_paths:
        # spread sample: take files from the start, middle and end
        step = max(1, len(code_paths) // max_ai_file_scan)
        sample = code_paths[::step][:max_ai_file_scan]
        pool_workers = workers if prov.kind != "local" else min(workers, 4)

        def scan_file(p):
            content = _fetch_cached(prov, info, p, content_cache)
            return p, (detect_llms_in_code(content) if content else None)

        with ThreadPoolExecutor(max_workers=pool_workers) as pool:
            futures = [pool.submit(scan_file, p) for p in sample]
            for fut in as_completed(futures):
                try:
                    p, hits = fut.result()
                except Exception:
                    continue
                if hits is None:
                    continue
                files_scanned += 1
                if hits:
                    ai_code_files += 1
                for h in hits:
                    llm_code_files[h] += 1   # file-level count (as before)
                if hits and len(evidence) < 80:
                    # EXACT LOCATION: file path + line number(s), e.g.
                    # "src/utils.py:3" — previously only the file name was
                    # available; now the exact line of the attribution shows too.
                    loc_parts = [f"{p}:{ln}" for name, lines in hits.items()
                                for ln in lines]
                    evidence.append({"source": "code-comment",
                                     "llm": sorted(hits),
                                     "sample": p[:100],
                                     "location": ", ".join(loc_parts[:5])})
    result["llm_code_files"] = ai_code_files
    result["llm_files_scanned"] = files_scanned

    # ---- Combine: which LLM, what % ----
    combined = Counter()
    for name, n in llm_commit_counts.items():
        combined[name] += n * 3        # commit trailer = strongest signal
    for name, n in llm_mr_counts.items():
        combined[name] += n * 2
    for name, n in llm_code_files.items():
        combined[name] += n
    for tool in tool_configs:
        combined[tool] += 1            # config file = tool was used (weak weight)

    result["llm_commit_breakdown"] = dict(llm_commit_counts)
    result["llm_mr_breakdown"] = dict(llm_mr_counts)
    result["llm_combined_score"] = dict(combined)
    result["llm_evidence"] = evidence[:80]

    detected = bool(combined)
    result["llm_detected"] = "Yes" if detected else "No"
    result["primary_llm"] = combined.most_common(1)[0][0] if detected else ""

    # Overall usage % = treat the commit-based % as primary; if no commits
    # use MRs; failing that too (e.g. no-git folder) use the code-file %
    if isinstance(result["llm_pct_commits"], (int, float)) and ai_commits:
        result["llm_usage_pct"] = result["llm_pct_commits"]
        result["llm_usage_basis"] = f"{ai_commits}/{scanned} commits"
    elif isinstance(result["llm_pct_mrs"], (int, float)) and ai_mrs:
        result["llm_usage_pct"] = result["llm_pct_mrs"]
        result["llm_usage_basis"] = f"{ai_mrs}/{n_mrs} MRs/PRs"
    elif ai_code_files and files_scanned:
        result["llm_usage_pct"] = _pct(ai_code_files, files_scanned)
        result["llm_usage_basis"] = (f"{ai_code_files}/{files_scanned} "
                                     f"source files (code comments)")
    elif detected:
        result["llm_usage_pct"] = ""   # only configs found — no % possible
        result["llm_usage_basis"] = "tool configs only"
    elif scanned or files_scanned:
        result["llm_usage_pct"] = 0.0
        basis = []
        if scanned:
            basis.append(f"0/{scanned} commits")
        if files_scanned:
            basis.append(f"0/{files_scanned} files")
        result["llm_usage_basis"] = ", ".join(basis)
    else:
        result["llm_usage_pct"] = ""
        result["llm_usage_basis"] = ""

    # ---- Console summary ----
    if detected:
        tot = sum(combined.values()) or 1
        breakdown = ", ".join(f"{n} {round(100*v/tot)}%"
                              for n, v in combined.most_common(4))
        print(f"    [AI] LLM detected: {result['primary_llm']} (primary)")
        print(f"         Breakdown: {breakdown}")
        if isinstance(result.get("llm_usage_pct"), (int, float)):
            print(f"         Usage: {result['llm_usage_pct']}% "
                  f"({result['llm_usage_basis']})")
        if tool_configs:
            print(f"         Tool configs: {', '.join(sorted(tool_configs))}")
        print("         NOTE: only explicit signatures are counted — "
              "real AI use may be higher (lower bound)")
    else:
        print(f"    No explicit AI/LLM signature found "
              f"({scanned} commits, {n_mrs} MRs, {files_scanned} files "
              f"scanned). Silent AI use cannot be detected.")

    return commits


# ---------------------------------------------------------------------------
# Company/ownership detection (NEW) — heuristic, best-effort:
#   "Built by"  = the development company/agency that actually wrote the code
#   "Built for" = the client/product the repo was built for
#
# Neither is a verified fact — both are inferred from signals already lying
# around in the repo, so every result carries a confidence tier (high/
# medium/low) and an evidence trail. Treat this the same way as the license
# detection elsewhere in this script: a heuristic starting point for a
# human to confirm, not a guarantee.
# ---------------------------------------------------------------------------

PERSONAL_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.in", "yahoo.co.in",
    "yahoo.co.uk", "yahoo.co", "ymail.com", "rocketmail.com",
    "outlook.com", "outlook.co.in", "hotmail.com", "hotmail.co.in",
    "hotmail.co.uk", "live.com", "live.in", "icloud.com", "msn.com",
    "me.com", "protonmail.com", "proton.me", "aol.com", "yandex.com",
    "yandex.ru", "mail.com", "mail.ru", "gmx.com", "rediffmail.com",
    "zoho.com", "zohomail.com", "qq.com", "163.com", "126.com",
    "fastmail.com", "users.noreply.github.com",
}

_COPYRIGHT_RE = re.compile(
    r"copyright\s*(?:\(c\)|©)?\s*\d{4}(?:\s*[-–,]\s*\d{2,4})?\s+"
    r"([A-Z][\w&.,'\- ]{1,60}?)(?=[.\n,]|\s+all rights)",
    re.IGNORECASE)

_ANDROID_APPID_RE = re.compile(r'applicationId\s*=?\s*["\']([a-zA-Z0-9_.]+)["\']')
_IOS_PBXPROJ_RE = re.compile(r'PRODUCT_BUNDLE_IDENTIFIER\s*=\s*([a-zA-Z0-9_.\$\(\)]+);')
_IOS_PLIST_RE = re.compile(r'<key>CFBundleIdentifier</key>\s*<string>([^<]+)</string>')

# Reverse-domain segments that never identify a company (com.<x>.app etc.)
_GENERIC_BUNDLE_SEGMENTS = {
    "com", "org", "net", "io", "app", "android", "ios", "debug", "release",
    "dev", "staging", "prod", "production", "example", "test", "www",
}

_GENERIC_PROJECT_NAME_WORDS = {
    "app", "api", "backend", "frontend", "server", "web", "client",
    "project", "repo", "website", "cms", "admin", "portal", "platform",
    "service", "core", "main", "src", "test", "demo", "poc",
}


def _domain_to_company_name(domain):
    base = domain.split(".")[0]
    return base.upper() if len(base) <= 4 else base.title()


def _clean_project_name(raw):
    """Turn a repo/package slug into a readable client-name candidate —
    agencies commonly suffix repo names with the tech stack
    (bryan-crm_nodejs, iyba-api_Laravel), which isn't part of the name."""
    if not raw:
        return ""
    name = raw.rsplit("/", 1)[-1]
    name = re.sub(r"\.git$", "", name, flags=re.IGNORECASE)
    name = re.sub(
        r"[-_](nodejs|node|reactjs|react-native|reactnative|react|angular|"
        r"vuejs|vue|laravel|php|django|flask|python|android|ios|flutter|"
        r"dart|api|backend|frontend|web|app|mobile|server|admin|cms|"
        r"dashboard)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[-_]+", " ", name).strip()
    return name.title() if name.islower() else name


def _extract_bundle_company_segment(bundle_id):
    parts = [p for p in re.split(r"[.\$\(\):]+", bundle_id) if p]
    candidates = [p for p in parts
                 if p.lower() not in _GENERIC_BUNDLE_SEGMENTS and not p.isdigit()]
    return candidates[0] if candidates else ""


def _company_from_commit_emails(commits):
    """Dominant non-personal email domain among commit authors — usually
    the development company/agency that actually wrote the code."""
    domain_counts = Counter()
    total_with_email = 0
    for c in commits:
        email = (c.get("email") or "").strip().lower()
        if "@" not in email:
            continue
        total_with_email += 1
        domain = email.rsplit("@", 1)[-1]
        if not domain or domain in PERSONAL_EMAIL_DOMAINS or "noreply" in domain:
            continue
        domain_counts[domain] += 1
    if not domain_counts or not total_with_email:
        return None
    domain, count = domain_counts.most_common(1)[0]
    return {"domain": domain, "commits": count, "total": total_with_email,
            "pct": round(100 * count / total_with_email, 1)}


def _company_from_manifest(prov, info, all_paths, cache):
    for mf in ("package.json", "composer.json"):
        if mf not in all_paths:
            continue
        raw = _fetch_cached(prov, info, mf, cache) or ""
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        author = data.get("author") or data.get("authors")
        if isinstance(author, list) and author:
            author = author[0]
        name = ""
        if isinstance(author, dict):
            name = author.get("name") or author.get("company") or ""
        elif isinstance(author, str):
            name = re.sub(r"\s*<[^>]*>\s*", "", author).strip()
        name = name or data.get("organization") or data.get("company") or ""
        if name:
            return {"name": name.strip(), "source": mf}
    return None


def _company_from_license_file(prov, info, all_paths, cache):
    lic_files = [p for p in all_paths
                if LICENSE_FILE_RE.search(p) and p.count("/") == 0]
    for lp in lic_files[:2]:
        text = _fetch_cached(prov, info, lp, cache) or ""
        m = _COPYRIGHT_RE.search(text)
        if m:
            name = m.group(1).strip().rstrip(".,")
            if name.lower() not in ("the author", "authors", "contributors",
                                    "author"):
                return {"name": name, "source": lp}
    return None


def _client_from_bundle_id(prov, info, all_paths, cache):
    """Android applicationId / iOS bundle identifier — the app's unique
    reverse-domain id usually encodes the client/product, not the agency."""
    gradle_paths = [p for p in all_paths
                    if p.lower().endswith(("build.gradle", "build.gradle.kts"))]
    # app-module gradle files (not root/library modules) carry applicationId
    gradle_paths.sort(key=lambda p: 0 if "/app/" in p.replace("\\", "/").lower()
                      else 1)
    for gp in gradle_paths[:5]:
        content = _fetch_cached(prov, info, gp, cache) or ""
        m = _ANDROID_APPID_RE.search(content)
        if m:
            seg = _extract_bundle_company_segment(m.group(1))
            if seg:
                return {"name": seg, "source": gp, "bundle_id": m.group(1)}

    ios_paths = [p for p in all_paths
                if p.lower().endswith((".pbxproj", "info.plist"))]
    for ip in ios_paths[:5]:
        content = _fetch_cached(prov, info, ip, cache) or ""
        m = _IOS_PBXPROJ_RE.search(content) or _IOS_PLIST_RE.search(content)
        if m:
            seg = _extract_bundle_company_segment(m.group(1))
            if seg:
                return {"name": seg, "source": ip, "bundle_id": m.group(1)}
    return None


def _client_from_package_name(prov, info, all_paths, cache):
    if "package.json" not in all_paths:
        return None
    raw = _fetch_cached(prov, info, "package.json", cache) or ""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    name = (data.get("name") or "").strip()
    cleaned = re.sub(r"^@[\w.-]+/", "", name)   # strip npm scope
    key = cleaned.lower().replace("-", "").replace("_", "")
    if cleaned and key not in _GENERIC_PROJECT_NAME_WORDS:
        return {"name": _clean_project_name(cleaned), "source": "package.json"}
    return None


def _org_from_repo_full_name(info):
    """GitHub/GitLab owner or organization, from an 'owner/repo' style
    project name (works for the GitHub/GitLab providers, and for local
    clones where a git remote could be resolved). This is the single most
    reliable 'who built this' signal when the repo is hosted under a
    company/org account rather than copied to a personal one — it doesn't
    depend on the developer having filled in a manifest author field or
    used a company email, both of which are frequently missing/personal."""
    full = (info.get("name") or "").strip()
    if "/" not in full:
        return None
    owner = full.split("/", 1)[0].strip()
    if not owner or owner.lower() in _GENERIC_PROJECT_NAME_WORDS:
        return None
    return {"name": owner, "source": "VCS owner/organization"}


_COMPANY_SUFFIX_RE = re.compile(
    r"\b([A-Z][\w&.,'\- ]{2,70}?\s(?:Limited|Ltd\.?|Pvt\.?\s*Ltd\.?|Inc\.?|"
    r"LLC|Corporation|Corp\.?|Technologies|Solutions|Services|Systems))\b")
_COMPANY_FOR_RE = re.compile(
    r"\bfor\s+\*{0,2}([A-Z][\w&.,'\-() ]{2,80}?)\*{0,2}"
    r"(?=[.,\n]|\s+[-–]|\s+built|\s+is\b)")

# README preambles are also where "built by <agency>" / "developed by
# <agency>" shows up — catches the dev-side attribution too.
_COMPANY_BUILTBY_RE = re.compile(
    r"\b(?:built|developed|created|maintained)\s+by\s+"
    r"\*{0,2}([A-Z][\w&.,'\-() ]{2,80}?)\*{0,2}(?=[.,\n]|\s+[-–])")


def _company_from_readme(prov, info, all_paths, cache):
    """Best-effort client/company name from the README's opening text —
    catches phrasing like 'built for Air India Engineering Services
    Limited (AIESL)' that manifest/bundle-id heuristics never see.
    Returns: {"built_for": {...}|None, "built_by": {...}|None}"""
    readme_paths = [p for p in all_paths
                    if p.lower() in ("readme.md", "readme.rst",
                                     "readme.txt", "readme")]
    out = {"built_for": None, "built_by": None}
    for rp in readme_paths[:1]:
        text = _fetch_cached(prov, info, rp, cache) or ""
        head = text[:4000]
        by_m = _COMPANY_BUILTBY_RE.search(head)
        if by_m:
            out["built_by"] = {"name": by_m.group(1).strip().rstrip(".,"),
                               "source": rp}
        for_m = _COMPANY_FOR_RE.search(head) or _COMPANY_SUFFIX_RE.search(head)
        if for_m:
            name = for_m.group(1).strip().rstrip(".,")
            if len(name) <= 80:
                out["built_for"] = {"name": name, "source": rp}
        break
    return out


def _detect_company_info(prov, info, all_paths, commits, cache, result):
    """Heuristic 'who built this' / 'who was it built for' detection
    (writes built_by_company/built_for_company + confidence + evidence
    into result). Best-effort — always shown with evidence so it can be
    sanity-checked, never presented as verified fact."""
    print("  Company/ownership detection...")

    # ---- Built by: the development company/agency ----
    vcs_owner_hit = _org_from_repo_full_name(info)
    manifest_hit = _company_from_manifest(prov, info, all_paths, cache)
    license_hit = _company_from_license_file(prov, info, all_paths, cache)
    email_hit = _company_from_commit_emails(commits)
    readme_hits = _company_from_readme(prov, info, all_paths, cache)
    readme_by_hit = readme_hits["built_by"]

    built_by_name, built_by_conf, built_by_ev = "", "", []
    if vcs_owner_hit:
        built_by_ev.append(f"{vcs_owner_hit['source']}: "
                           f"\"{vcs_owner_hit['name']}\"")
    if readme_by_hit:
        built_by_ev.append(f"{readme_by_hit['source']}: \"built/developed "
                           f"by {readme_by_hit['name']}\"")
    if manifest_hit:
        built_by_ev.append(f"{manifest_hit['source']}: author/organization "
                           f"= \"{manifest_hit['name']}\"")
    if license_hit:
        built_by_ev.append(f"{license_hit['source']}: copyright holder "
                           f"= \"{license_hit['name']}\"")
    if email_hit:
        built_by_ev.append(
            f"commit emails: {email_hit['commits']}/{email_hit['total']} "
            f"({email_hit['pct']}%) from @{email_hit['domain']}")

    def _norm(s):
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())

    if vcs_owner_hit:
        # the hosting account is direct ground truth for "who built this" —
        # rank it above guesses derived from manifest fields/emails, which
        # are frequently missing or point at a personal address instead.
        built_by_name = vcs_owner_hit["name"]
        corroborated = any(
            hit and (_norm(hit["name"]) in _norm(built_by_name)
                    or _norm(built_by_name) in _norm(hit["name"]))
            for hit in (readme_by_hit, manifest_hit, license_hit))
        if not corroborated and email_hit:
            corroborated = email_hit["domain"].split(".")[0].lower() in \
                built_by_name.lower().replace(" ", "")
        built_by_conf = "high" if corroborated else "medium"
    elif readme_by_hit:
        built_by_name = readme_by_hit["name"]
        built_by_conf = "medium"
    elif manifest_hit or license_hit:
        built_by_name = (manifest_hit or license_hit)["name"]
        # a matching email domain corroborates the manifest/license name
        if email_hit and email_hit["domain"].split(".")[0].lower() in \
                built_by_name.lower().replace(" ", ""):
            built_by_conf = "high"
        else:
            built_by_conf = "medium"
    elif email_hit and email_hit["pct"] >= 40:
        built_by_name = _domain_to_company_name(email_hit["domain"])
        built_by_conf = "high" if email_hit["pct"] >= 70 else "medium"
    elif email_hit:
        built_by_name = _domain_to_company_name(email_hit["domain"])
        built_by_conf = "low"

    result["built_by_company"] = built_by_name
    result["built_by_confidence"] = built_by_conf
    result["built_by_evidence"] = built_by_ev

    # ---- Built for: the client ----
    bundle_hit = _client_from_bundle_id(prov, info, all_paths, cache)
    readme_for_hit = readme_hits["built_for"]
    pkg_hit = _client_from_package_name(prov, info, all_paths, cache)
    repo_name_candidate = _clean_project_name(info.get("name", ""))

    built_for_ev = []
    if bundle_hit:
        built_for_ev.append(f"{bundle_hit['source']}: bundle id "
                            f"\"{bundle_hit['bundle_id']}\"")
    if readme_for_hit:
        built_for_ev.append(f"{readme_for_hit['source']}: \"built for "
                            f"{readme_for_hit['name']}\"")
    if pkg_hit:
        built_for_ev.append(f"{pkg_hit['source']}: name field")
    if repo_name_candidate:
        built_for_ev.append(f"repo/folder name: \"{info.get('name', '')}\"")

    def _is_same_as_built_by(name):
        """A candidate that just re-identifies the dev company itself
        isn't evidence of client work — e.g. the agency's own product."""
        if not built_by_name or not name:
            return False
        a = re.sub(r"[^a-z0-9]", "", name.lower())
        b = re.sub(r"[^a-z0-9]", "", built_by_name.lower())
        return bool(a) and bool(b) and (a in b or b in a)

    built_for_name, built_for_conf = "", ""
    if bundle_hit and not _is_same_as_built_by(bundle_hit["name"]):
        seg = bundle_hit["name"]
        built_for_name = seg.title() if seg.islower() else seg
        built_for_conf = "high"
    elif readme_for_hit and not _is_same_as_built_by(readme_for_hit["name"]):
        built_for_name = readme_for_hit["name"]
        built_for_conf = "medium"
    elif pkg_hit and not _is_same_as_built_by(pkg_hit["name"]):
        built_for_name = pkg_hit["name"]
        built_for_conf = "medium"
    elif repo_name_candidate and not _is_same_as_built_by(repo_name_candidate):
        built_for_name = repo_name_candidate
        built_for_conf = "low"
    else:
        # every candidate pointed back at the dev company itself — likely
        # an internal/product repo, not client work
        built_for_name = built_by_name or repo_name_candidate
        built_for_conf = "low" if built_for_name else ""

    result["built_for_company"] = built_for_name
    result["built_for_confidence"] = built_for_conf
    result["built_for_evidence"] = built_for_ev

    if built_by_name or built_for_name:
        print(f"    Built by: {built_by_name or '(unknown)'} "
              f"[{built_by_conf or 'n/a'} confidence]  |  "
              f"Built for: {built_for_name or '(unknown)'} "
              f"[{built_for_conf or 'n/a'} confidence]")
    else:
        print("    No company signals found (no manifest author, no "
              "license copyright line, no non-personal commit emails)")


# ---------------------------------------------------------------------------
# Training-data quality analysis (NEW)
# ---------------------------------------------------------------------------

# Cap content pulled through quality/secret/dedup scans. LocalProvider
# already caps its own reads at this size (_MAX_READ_BYTES); the API
# providers (GitLab/GitHub) had no such cap, so a large generated/bundled
# file that slipped past GENERATED_FILE_SUFFIXES would be pulled in full
# and run through every regex-heavy scan unbounded.
_MAX_SCAN_CONTENT_BYTES = 5_000_000


def _fetch_cached(prov, info, path, cache):
    if path not in cache:
        content = prov.file_content(info, path)
        if content is not None and len(content) > _MAX_SCAN_CONTENT_BYTES:
            content = content[:_MAX_SCAN_CONTENT_BYTES]
        cache[path] = content
    return cache[path]


def _analyze_training_quality(prov, info, all_paths, result,
                              max_scan, workers, cache):
    """Post-training data-quality factors (writes into result):
    license, syntax validity, quality metrics, dedup, secrets/PII,
    eval contamination, composite score + suitability grade."""
    print("  Training-quality analysis...")

    # ---- 1. License detection ----
    license_name = info.get("license_hint") or ""
    lic_files = [p for p in all_paths
                 if LICENSE_FILE_RE.search(p) and p.count("/") == 0]
    if not license_name:
        for lp in lic_files[:2]:
            license_name = classify_license(_fetch_cached(prov, info, lp,
                                                          cache))
            if license_name:
                break
    if not license_name:
        # manifest fallback: package.json / pyproject / Cargo.toml
        for mf in ("package.json", "pyproject.toml", "Cargo.toml",
                   "composer.json", "setup.py"):
            if mf not in all_paths:
                continue
            c = _fetch_cached(prov, info, mf, cache) or ""
            m = re.search(r"""["']?license["']?\s*[:=]\s*["']([^"']{2,40})["']""",
                          c, re.IGNORECASE)
            if m:
                license_name = m.group(1).strip()
                break
    if license_name:
        risk = LICENSE_RISK.get(license_name, "unknown")
    elif lic_files:
        license_name, risk = "custom/unclassified", "unknown"
    else:
        license_name, risk = "NONE", "no-license (all rights reserved)"
    result["license"] = license_name
    result["license_risk"] = risk

    # ---- 2-6. In one pass: quality + dedup + secrets + contamination ----
    if max_scan == 0:   # auto
        # ALL code files locally; a sample via API (calls are costly)
        max_scan = 10**9 if prov.kind == "local" else 50
    code_paths = [p for p in all_paths if is_code_file(p)]
    step = max(1, len(code_paths) // max_scan) if code_paths else 1
    sample = code_paths[::step][:max_scan]
    pool_workers = workers if prov.kind != "local" else min(workers, 4)

    tot = Counter()
    sum_avg_len = 0.0
    hashes = Counter()
    secrets_found = []
    contam_files = []
    syntax_valid, syntax_checked = 0, 0
    files_scanned = 0

    def scan_one(p):
        content = _fetch_cached(prov, info, p, cache)
        if content is None:
            return None
        q = scan_file_quality(p, content)
        s, emails = scan_secrets_and_pii(content, p)
        return p, q, s, emails

    with ThreadPoolExecutor(max_workers=pool_workers) as pool:
        futures = [pool.submit(scan_one, p) for p in sample]
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception:
                continue
            if r is None:
                continue
            p, q, s, emails = r
            files_scanned += 1
            for k in ("lines", "code_lines", "long_lines", "comment_lines",
                      "blank_lines", "funcs", "classes"):
                tot[k] += q[k]
            sum_avg_len += q["avg_len"]
            tot["docstrings"] += 1 if q["has_docstring"] else 0
            tot["py_files"] += 1 if p.endswith(".py") else 0
            tot["emails"] += emails
            if q["hash"]:
                hashes[q["hash"]] += 1
            if q["syntax_valid"] is not None:
                syntax_checked += 1
                syntax_valid += 1 if q["syntax_valid"] else 0
            if q["eval_contam"]:
                contam_files.append(p)
            secrets_found.extend(s)

    dup_files = sum(c - 1 for c in hashes.values() if c > 1)
    dup_pct = round(100 * dup_files / files_scanned, 1) if files_scanned else ""
    comment_ratio = (round(100 * tot["comment_lines"] / tot["lines"], 1)
                     if tot["lines"] else "")
    blank_ratio = (round(100 * tot["blank_lines"] / tot["lines"], 1)
                  if tot["lines"] else "")
    avg_line_len = (round(sum_avg_len / files_scanned, 1)
                    if files_scanned else "")
    pct_long = (round(100 * tot["long_lines"] / tot["lines"], 1)
                if tot["lines"] else "")
    avg_func_len = (round(tot["code_lines"] / tot["funcs"], 1)
                    if tot["funcs"] else "")
    syntax_pct = (round(100 * syntax_valid / syntax_checked, 1)
                  if syntax_checked else "")
    docstring_pct = (round(100 * tot["docstrings"] / tot["py_files"], 1)
                     if tot["py_files"] else "")
    # Function/class counts are only exact when every code file was scanned
    # (local mode default). When a sample was taken (API mode), scale the
    # sample's counts up by the same ratio as sampled:total files — same
    # extrapolation approach used elsewhere in this function (test_cases,
    # total_comment_lines) rather than reporting a silently-partial count.
    extrap_scale = (len(code_paths) / files_scanned) if files_scanned else 1
    total_functions = (round(tot["funcs"] * extrap_scale)
                       if files_scanned else "")
    total_classes = (round(tot["classes"] * extrap_scale)
                     if files_scanned else "")

    result["quality_files_scanned"] = files_scanned
    result["total_functions"] = total_functions
    result["total_classes"] = total_classes
    # comment_ratio_pct / blank_ratio_pct below are % of scanned files.
    # They get extrapolated onto the repo-wide "Total LoC (est.)" further
    # down in analyze_project(), once that total is known, to produce
    # "Total comment lines" / "Total blank lines".
    result["blank_ratio_pct"] = blank_ratio
    loc_basis = ("exact (all files)"
                 if prov.kind == "local" and max_scan >= 10**9
                 else f"sample ({files_scanned} of {len(code_paths)} files)")
    total_loc = result.get("total_loc_estimate")
    result["total_comment_lines"] = (
        round(total_loc * comment_ratio / 100)
        if isinstance(total_loc, (int, float))
        and isinstance(comment_ratio, (int, float)) else "")
    result["total_blank_lines"] = (
        round(total_loc * blank_ratio / 100)
        if isinstance(total_loc, (int, float))
        and isinstance(blank_ratio, (int, float)) else "")
    result["syntax_valid_pct"] = syntax_pct
    result["avg_line_length"] = avg_line_len
    result["pct_long_lines"] = pct_long
    result["comment_ratio_pct"] = comment_ratio
    result["docstring_pct"] = docstring_pct
    result["avg_func_length"] = avg_func_len
    result["duplicate_files"] = dup_files
    result["duplicate_pct"] = dup_pct
    result["secrets_found"] = len(secrets_found)
    result["secrets_detail"] = secrets_found[:30]   # MASKED — never plain
    result["pii_emails"] = tot["emails"]
    result["eval_contamination_files"] = len(contam_files)
    result["eval_contamination_detail"] = contam_files[:20]

    # ---- 7. Composite score + Training suitability ----
    score = 100.0
    reasons = []
    if syntax_checked and syntax_valid < syntax_checked:
        bad = 100 * (1 - syntax_valid / syntax_checked)
        score -= min(40, bad * 0.5)
        reasons.append(f"{round(bad)}% Python files syntax-invalid")
    if isinstance(pct_long, (int, float)) and pct_long > 30:
        score -= 10
        reasons.append("very long lines (generated/obfuscated pattern)")
    if isinstance(comment_ratio, (int, float)):
        if comment_ratio < 2:
            score -= 10
            reasons.append("almost zero comments")
        elif comment_ratio > 60:
            score -= 5
            reasons.append("comment-heavy (auto-doc/generated pattern)")
    if isinstance(dup_pct, (int, float)) and dup_pct:
        score -= min(30, dup_pct)
        reasons.append(f"{dup_pct}% duplicate files")
    if secrets_found:
        score -= 15
        reasons.append(f"{len(secrets_found)} secrets/keys found")
    if isinstance(avg_func_len, (int, float)) and avg_func_len > 80:
        score -= 10
        reasons.append("very long functions (avg >80 lines)")
    if not result.get("test_files"):
        score -= 10
        reasons.append("no tests")
    elif (isinstance(result.get("pct_genuine_tests"), (int, float))
          and result["pct_genuine_tests"] < 50):
        score -= 10
        reasons.append("more than half the tests are suspicious")
    if contam_files:
        score -= 20
        reasons.append(f"eval-benchmark code in {len(contam_files)} files")
    score = max(0.0, round(score, 1))
    result["quality_score"] = score

    grade = ("A" if score >= 80 else "B" if score >= 60
             else "C" if score >= 40 else "D")
    # License cap: copyleft/no-license is risky for training use
    if risk.startswith("no-license"):
        if grade in ("A", "B"):
            grade = "C"
        reasons.append("no license — training use is risky")
    elif risk == "copyleft":
        if grade == "A":
            grade = "B"
        reasons.append(f"copyleft license ({license_name})")
    result["training_suitability"] = grade
    result["quality_reasons"] = reasons

    # ---- Console ----
    print(f"    License: {license_name} ({risk})  [heuristic — not legal "
          f"advice]")
    print(f"    Quality: score {score}/100 -> suitability {grade} "
          f"({files_scanned} files scanned)")
    print(f"    LOC breakdown [{loc_basis}]: "
          f"{tot['lines']} total lines -> {tot['code_lines']} code, "
          f"{tot['comment_lines']} comment ({comment_ratio}%), "
          f"{tot['blank_lines']} blank ({blank_ratio}%)")
    if isinstance(syntax_pct, (int, float)):
        print(f"    Syntax valid (Python): {syntax_pct}%")
    if secrets_found:
        by_type = Counter(s["type"] for s in secrets_found)
        print("    [!] SECRETS: " + ", ".join(f"{t} x{c}"
                                               for t, c in by_type.items())
              + " (MASKED in the detail JSON)")
    if contam_files:
        print(f"    [!] EVAL CONTAMINATION: HumanEval/MBPP signatures in "
              f"{len(contam_files)} files")
    if reasons and not secrets_found and not contam_files:
        print(f"    Notes: {'; '.join(reasons[:3])}")


def _analyze_swe_quality(result):
    """Heuristic 'Quality of SWE' signal — an estimate of the engineering
    team's skill/discipline behind the code (CI discipline, review depth,
    test genuineness, function size, comment habits, duplication, secret
    hygiene), as distinct from `quality_score` above (which grades the CODE
    itself for LLM-training suitability, not the people who wrote it).

    Built entirely from fields already computed earlier in this same
    analysis (_categorize_mrs, _analyze_files_ci_tests,
    _analyze_training_quality) — no extra file scanning or API calls, so
    this is effectively free to compute.

    Writes into result:
      swe_quality_score   (0-100)
      swe_quality_level   ("Weak" | "Mixed" | "Solid" | "Strong")
      swe_quality_reasons (list[str] — contributing signals, for the console
                            / detail JSON; not included in the CSV row)
    """
    def num(key):
        v = result.get(key)
        return v if isinstance(v, (int, float)) else None

    score = 50.0
    reasons = []

    ci = result.get("ci_configured")
    if ci == "Yes":
        score += 10
        reasons.append("CI/CD configured")
    elif ci == "No":
        score -= 5
        reasons.append("no CI/CD")

    pct_rich = num("pct_rich")
    pct_simple = num("pct_simple")
    pct_automated = num("pct_automated")
    if pct_rich is not None:
        if pct_rich >= 30:
            score += 10
            reasons.append(f"{pct_rich}% rich/reviewed PRs")
        elif pct_rich < 5:
            score -= 5
            reasons.append("almost no rich/reviewed PRs")
    if pct_simple is not None and pct_simple >= 70:
        score -= 10
        reasons.append(f"{pct_simple}% trivial/simple PRs")
    if pct_automated is not None and pct_automated >= 50:
        score -= 10
        reasons.append(f"{pct_automated}% automated/bot PRs")

    genuine = num("pct_genuine_tests")
    if not result.get("test_files"):
        score -= 15
        reasons.append("no tests")
    elif genuine is not None:
        if genuine >= 80:
            score += 15
            reasons.append(f"{genuine}% genuine tests")
        elif genuine < 50:
            score -= 10
            reasons.append(f"only {genuine}% of tests look genuine")

    afl = num("avg_func_length")
    if afl is not None:
        if afl <= 30:
            score += 10
            reasons.append(f"short, well-factored functions (avg {afl} lines)")
        elif afl > 80:
            score -= 10
            reasons.append(f"very long functions (avg {afl} lines)")

    cr = num("comment_ratio_pct")
    if cr is not None:
        if 5 <= cr <= 30:
            score += 5
            reasons.append(f"healthy comment ratio ({cr}%)")
        elif cr < 2:
            score -= 5
            reasons.append("almost no comments")

    dup = num("duplicate_pct")
    if dup is not None:
        if dup >= 15:
            score -= 10
            reasons.append(f"{dup}% duplicate files")
        elif dup <= 3:
            score += 5
            reasons.append("low code duplication")

    sv = num("syntax_valid_pct")
    if sv is not None and sv < 100:
        score -= 10
        reasons.append(f"{sv}% syntax-valid Python (some invalid files)")

    secrets = result.get("secrets_found") or 0
    if secrets:
        score -= 15
        reasons.append(f"{secrets} hardcoded secret(s) found")
    else:
        score += 5

    pll = num("pct_long_lines")
    if pll is not None and pll > 30:
        score -= 5
        reasons.append(f"{pll}% very long lines")

    score = max(0.0, min(100.0, round(score, 1)))
    level = ("Strong" if score >= 75 else "Solid" if score >= 55
             else "Mixed" if score >= 35 else "Weak")

    result["swe_quality_score"] = score
    result["swe_quality_level"] = level
    result["swe_quality_reasons"] = reasons

    print(f"    Quality of SWE (heuristic): {level} ({score}/100)"
          + (" — " + "; ".join(reasons[:3]) if reasons else ""))


# ---------------------------------------------------------------------------
# Aggregation + CSV
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "Project/Group name", "Provider",
    "Built By", "Built For",
    "Established year",
    "First commit date", "Last commit date", "Years active",
    "Last activity", "# of contributors", "Quality of SWE",
    "Primary coding language",
    "Language breakdown", "Total LoC (est.)", "Total comment lines",
    "Total blank lines",
    "# of Repos", "# of MRs/PRs",
    "# of Merged", "Avg LoC per MR", "% Simple fixes",
    "% Standard feature work", "% Rich tasks", "Other %", "Automated %",
    "# of Commits",
    "CI/CD configured", "CI systems", "CI config files", "CI jobs (approx)",
    "# of Pipelines/Runs", "Pipeline success rate %",
    "Avg pipeline duration (min)",
    "Unit test coverage % of GitLab", "Unit test coverage % of GitHub",
    "Unit test coverage % of Local Repo",
    "Source files", "Test files", "Genuine test files",
    "Suspicious test files", "% Genuine tests", "Test cases (approx)",
    "Assertions", "# of Functions", "# of Classes",
    "% Test-to-Code Ratio", "% Untested Files",
    "AI/LLM detected", "Primary LLM", "LLM usage %", "LLM usage basis",
    "LLM breakdown", "AI commits", "Commits scanned (LLM)",
    "AI MRs/PRs", "AI tool configs",
    "License", "License risk", "Syntax valid % (py)", "Avg line length",
    "Long lines %", "Comment ratio %", "Docstring % (py)",
    "Avg function length", "Duplicate files %", "Secrets found",
    "PII emails", "Eval contamination files", "Quality score",
    "Training suitability",
    "Code availability",
]


def aggregate(results, name):
    agg = {"name": name, "repos": len(results)}
    agg["provider"] = "/".join(sorted({r.get("provider", "") for r in results}))
    for f in ("total_loc_estimate", "commits", "total_mrs", "merged_mrs",
              "contributors", "source_files", "test_files", "test_cases",
              "assertions", "genuine_test_files", "suspicious_test_files",
              "ci_config_files", "ci_jobs_approx", "ci_pipelines_total",
              "llm_commits_scanned", "llm_ai_commits", "llm_ai_mrs",
              "llm_code_files", "llm_files_scanned",
              "quality_files_scanned", "duplicate_files", "secrets_found",
              "pii_emails", "eval_contamination_files",
              "total_comment_lines", "total_blank_lines",
              "total_functions", "total_classes", "untested_source_files"):
        vals = [r[f] for r in results if isinstance(r.get(f), (int, float))]
        agg[f] = sum(vals) if vals else ""

    # % Test-to-Code Ratio / % Untested Files — recomputed from the summed
    # totals (not averaged per-repo percentages), same approach as
    # pct_genuine_tests below.
    agg["pct_test_to_code_ratio"] = (
        round(100 * agg["test_files"] / agg["source_files"], 1)
        if agg.get("source_files") else "")
    agg["pct_untested_files"] = (
        round(100 * agg["untested_source_files"] / agg["source_files"], 1)
        if agg.get("source_files") else "")

    # ---- AI/LLM aggregate ----
    llm_score = Counter()
    for r in results:
        for llm_name, v in (r.get("llm_combined_score") or {}).items():
            llm_score[llm_name] += v
    agg["llm_detected"] = "Yes" if llm_score else "No"
    agg["primary_llm"] = llm_score.most_common(1)[0][0] if llm_score else ""
    tot_score = sum(llm_score.values()) or 1
    agg["llm_breakdown"] = "; ".join(
        f"{n} {round(100*v/tot_score)}%" for n, v in llm_score.most_common(5))
    scanned = agg.get("llm_commits_scanned")
    ai_c = agg.get("llm_ai_commits")
    if isinstance(scanned, int) and scanned and isinstance(ai_c, int):
        agg["llm_usage_pct"] = _pct(ai_c, scanned)
        agg["llm_usage_basis"] = f"{ai_c}/{scanned} commits"
    else:
        agg["llm_usage_pct"] = ""
        agg["llm_usage_basis"] = ""
    if (agg["llm_usage_pct"] in ("", 0, 0.0)) and llm_score:
        # nothing found in commits but something found elsewhere
        total_mrs_scanned = sum(r.get("mr_sample_size", 0) or 0
                                for r in results)
        ai_m = agg.get("llm_ai_mrs")
        ai_f = agg.get("llm_code_files")
        f_scanned = agg.get("llm_files_scanned")
        if isinstance(ai_m, int) and ai_m and total_mrs_scanned:
            agg["llm_usage_pct"] = round(100 * ai_m / total_mrs_scanned, 1)
            agg["llm_usage_basis"] = f"{ai_m}/{total_mrs_scanned} MRs/PRs"
        elif (isinstance(ai_f, int) and ai_f
              and isinstance(f_scanned, int) and f_scanned):
            agg["llm_usage_pct"] = round(100 * ai_f / f_scanned, 1)
            agg["llm_usage_basis"] = (f"{ai_f}/{f_scanned} source files "
                                      f"(code comments)")
        elif agg["llm_usage_pct"] in ("",):
            agg["llm_usage_basis"] = "tool configs only"
    elif agg["llm_usage_pct"] == "" and not llm_score:
        # Nothing detected — show 0% of what was scanned (not blank)
        f_scanned = agg.get("llm_files_scanned")
        if isinstance(f_scanned, int) and f_scanned:
            agg["llm_usage_pct"] = 0.0
            agg["llm_usage_basis"] = f"0/{f_scanned} source files"
    ai_tools = set()
    for r in results:
        ai_tools.update(r.get("ai_tool_configs") or [])
    agg["ai_tool_configs"] = "; ".join(sorted(ai_tools))

    # ---- Company/ownership aggregate ----
    # "Built by" is usually the same across every repo in one run (one
    # agency's codebases); "Built for" varies per repo (different clients)
    # — both just get every distinct non-blank value seen, joined, so a
    # multi-repo summary row doesn't silently pick just one.
    built_by = sorted({r.get("built_by_company", "") for r in results
                       if r.get("built_by_company")})
    built_for = sorted({r.get("built_for_company", "") for r in results
                        if r.get("built_for_company")})
    agg["built_by_company"] = "; ".join(built_by)
    agg["built_for_company"] = "; ".join(built_for)
    conf_order = {"high": 3, "medium": 2, "low": 1}
    by_confs = [r.get("built_by_confidence", "") for r in results
               if r.get("built_by_confidence")]
    for_confs = [r.get("built_for_confidence", "") for r in results
                if r.get("built_for_confidence")]
    agg["built_by_confidence"] = (min(by_confs, key=lambda c: conf_order.get(c, 0))
                                  if by_confs else "")
    agg["built_for_confidence"] = (min(for_confs, key=lambda c: conf_order.get(c, 0))
                                   if for_confs else "")

    checked = [(r.get("genuine_test_files", 0) or 0)
               + (r.get("suspicious_test_files", 0) or 0) for r in results]
    total_checked = sum(checked)
    agg["pct_genuine_tests"] = (
        round(100 * (agg["genuine_test_files"] or 0) / total_checked, 1)
        if total_checked else "")

    # CI/CD aggregate
    agg["ci_configured"] = ("Yes" if any(r.get("ci_configured") == "Yes"
                                         for r in results) else "No")
    systems = set()
    for r in results:
        systems.update(r.get("ci_systems") or [])
    agg["ci_systems"] = "; ".join(sorted(systems))
    rates = [r["ci_success_rate"] for r in results
             if isinstance(r.get("ci_success_rate"), (int, float))]
    agg["ci_success_rate"] = round(sum(rates) / len(rates), 1) if rates else ""
    durs = [r["ci_avg_duration_min"] for r in results
            if isinstance(r.get("ci_avg_duration_min"), (int, float))]
    agg["ci_avg_duration_min"] = round(sum(durs) / len(durs), 1) if durs else ""

    # ---- Training-quality aggregate ----
    licenses = sorted({r.get("license", "") for r in results
                       if r.get("license")})
    agg["license"] = "; ".join(licenses)
    risk_order = ["permissive", "weak-copyleft", "unknown", "copyleft",
                  "no-license (all rights reserved)"]
    risks = [r.get("license_risk", "") for r in results if r.get("license_risk")]
    agg["license_risk"] = (max(risks, key=lambda x: risk_order.index(x)
                               if x in risk_order else 2) if risks else "")
    def _wavg(key):
        pairs = [(r[key], r.get("quality_files_scanned", 0) or 0)
                 for r in results if isinstance(r.get(key), (int, float))]
        tw = sum(w for _, w in pairs)
        return round(sum(v * w for v, w in pairs) / tw, 1) if tw else ""
    agg["syntax_valid_pct"] = _wavg("syntax_valid_pct")
    agg["avg_line_length"] = _wavg("avg_line_length")
    agg["pct_long_lines"] = _wavg("pct_long_lines")
    agg["comment_ratio_pct"] = _wavg("comment_ratio_pct")
    agg["docstring_pct"] = _wavg("docstring_pct")
    agg["avg_func_length"] = _wavg("avg_func_length")
    agg["quality_score"] = _wavg("quality_score")
    dupf, dups = agg.get("duplicate_files"), agg.get("quality_files_scanned")
    agg["duplicate_pct"] = (round(100 * dupf / dups, 1)
                            if isinstance(dupf, int) and isinstance(dups, int)
                            and dups else "")
    grades = [r.get("training_suitability", "") for r in results
              if r.get("training_suitability")]
    agg["training_suitability"] = (max(grades) if grades else "")  # worst (A<B<C<D)

    swe_scores = [r["swe_quality_score"] for r in results
                  if isinstance(r.get("swe_quality_score"), (int, float))]
    agg["swe_quality_score"] = (round(sum(swe_scores) / len(swe_scores), 1)
                                if swe_scores else "")
    s = agg["swe_quality_score"]
    agg["swe_quality_level"] = (
        "Strong" if isinstance(s, (int, float)) and s >= 75
        else "Solid" if isinstance(s, (int, float)) and s >= 55
        else "Mixed" if isinstance(s, (int, float)) and s >= 35
        else "Weak" if isinstance(s, (int, float)) else "")

    lang_total = Counter()
    for r in results:
        for lang, v in (r.get("languages") or {}).items():
            lang_total[lang] += v
    agg["primary_language"] = lang_total.most_common(1)[0][0] if lang_total else ""
    tot = sum(lang_total.values()) or 1
    agg["lang_breakdown"] = "; ".join(
        f"{l} {round(100*v/tot)}%" for l, v in lang_total.most_common(5))

    total_sample = sum(r.get("mr_sample_size", 0) or 0 for r in results)
    if total_sample:
        for key in ("pct_simple", "pct_standard", "pct_rich",
                    "pct_automated", "pct_other"):
            w = sum((r.get(key) or 0) * (r.get("mr_sample_size") or 0)
                    for r in results if isinstance(r.get(key), (int, float)))
            agg[key] = round(w / total_sample, 1)
        locs = [r["avg_loc_per_mr"] for r in results
                if isinstance(r.get("avg_loc_per_mr"), (int, float))]
        agg["avg_loc_per_mr"] = round(sum(locs) / len(locs), 1) if locs else ""
    else:
        for key in ("pct_simple", "pct_standard", "pct_rich", "pct_automated",
                    "pct_other", "avg_loc_per_mr"):
            agg[key] = ""

    dates = [r["created_at"] for r in results if r.get("created_at")]
    lasts = [r["last_activity"] for r in results if r.get("last_activity")]
    agg["established"] = min(dates)[:4] if dates else ""
    agg["last_activity"] = max(lasts) if lasts else ""

    # Real commit dates (ISO YYYY-MM-DD sorts chronologically as a string)
    fc = [r["first_commit"] for r in results if r.get("first_commit")]
    lc = [r["last_commit"] for r in results if r.get("last_commit")]
    agg["first_commit"] = min(fc) if fc else ""
    agg["last_commit"] = max(lc) if lc else ""

    # Prefer the real first commit for "years active"; fall back to the
    # platform's repo-creation date when commit history isn't available.
    since = agg["first_commit"][:4] or agg["established"]
    try:
        agg["years_active"] = (datetime.now().year - int(since)
                               if since else "")
    except ValueError:
        agg["years_active"] = ""

    def _avg_coverage(field):
        covs = [r[field] for r in results
                if isinstance(r.get(field), (int, float))]
        return round(sum(covs) / len(covs), 1) if covs else ""

    agg["coverage_gitlab"] = _avg_coverage("coverage_pct_gitlab")
    agg["coverage_github"] = _avg_coverage("coverage_pct_github")
    agg["coverage_local"] = _avg_coverage("coverage_pct_local")

    vis = {r.get("visibility", "") for r in results}
    prov = results[0].get("provider", "") if results else ""
    label = {"gitlab": "GitLab", "github": "GitHub", "local": "Local"}.get(
        prov, prov)
    if vis <= {"local"}:
        agg["availability"] = "Local/offline repo"
    elif vis <= {"public"}:
        agg["availability"] = f"Public ({label})"
    elif "private" in vis:
        agg["availability"] = "Private (access needed)"
    else:
        agg["availability"] = "/".join(sorted(v for v in vis if v)) or ""
    return agg


def to_row(a):
    return {
        "Project/Group name": a["name"],
        "Provider": a.get("provider", ""),
        "Built By": a.get("built_by_company", ""),
        "Built For": a.get("built_for_company", ""),
        "Established year": a["established"],
        "First commit date": a.get("first_commit", ""),
        "Last commit date": a.get("last_commit", ""),
        "Years active": a["years_active"],
        "Last activity": a["last_activity"],
        "# of contributors": a["contributors"],
        "Quality of SWE": (
            f"{a['swe_quality_level']} ({a['swe_quality_score']}/100)"
            if a.get("swe_quality_level") else ""),
        "Primary coding language": a["primary_language"],
        "Language breakdown": a["lang_breakdown"],
        "Total LoC (est.)": a["total_loc_estimate"],
        "Total comment lines": a.get("total_comment_lines", ""),
        "Total blank lines": a.get("total_blank_lines", ""),
        "# of Repos": a["repos"],
        "# of MRs/PRs": a["total_mrs"],
        "# of Merged": a["merged_mrs"],
        "Avg LoC per MR": a["avg_loc_per_mr"],
        "% Simple fixes": a["pct_simple"],
        "% Standard feature work": a["pct_standard"],
        "% Rich tasks": a["pct_rich"],
        "Other %": a["pct_other"],
        "Automated %": a["pct_automated"],
        "# of Commits": a["commits"],
        "CI/CD configured": a["ci_configured"],
        "CI systems": a["ci_systems"],
        "CI config files": a["ci_config_files"],
        "CI jobs (approx)": a["ci_jobs_approx"],
        "# of Pipelines/Runs": a["ci_pipelines_total"],
        "Pipeline success rate %": a["ci_success_rate"],
        "Avg pipeline duration (min)": a["ci_avg_duration_min"],
        "Unit test coverage % of GitLab": a.get("coverage_gitlab", ""),
        "Unit test coverage % of GitHub": a.get("coverage_github", ""),
        "Unit test coverage % of Local Repo": a.get("coverage_local", ""),
        "Source files": a["source_files"],
        "Test files": a["test_files"],
        "Genuine test files": a["genuine_test_files"],
        "Suspicious test files": a["suspicious_test_files"],
        "% Genuine tests": a["pct_genuine_tests"],
        "Test cases (approx)": a["test_cases"],
        "Assertions": a["assertions"],
        "# of Functions": a.get("total_functions", ""),
        "# of Classes": a.get("total_classes", ""),
        "% Test-to-Code Ratio": a.get("pct_test_to_code_ratio", ""),
        "% Untested Files": a.get("pct_untested_files", ""),
        "AI/LLM detected": a.get("llm_detected", ""),
        "Primary LLM": a.get("primary_llm", ""),
        "LLM usage %": a.get("llm_usage_pct", ""),
        "LLM usage basis": a.get("llm_usage_basis", ""),
        "LLM breakdown": a.get("llm_breakdown", ""),
        "AI commits": a.get("llm_ai_commits", ""),
        "Commits scanned (LLM)": a.get("llm_commits_scanned", ""),
        "AI MRs/PRs": a.get("llm_ai_mrs", ""),
        "AI tool configs": a.get("ai_tool_configs", ""),
        "License": a.get("license", ""),
        "License risk": a.get("license_risk", ""),
        "Syntax valid % (py)": a.get("syntax_valid_pct", ""),
        "Avg line length": a.get("avg_line_length", ""),
        "Long lines %": a.get("pct_long_lines", ""),
        "Comment ratio %": a.get("comment_ratio_pct", ""),
        "Docstring % (py)": a.get("docstring_pct", ""),
        "Avg function length": a.get("avg_func_length", ""),
        "Duplicate files %": a.get("duplicate_pct", ""),
        "Secrets found": a.get("secrets_found", ""),
        "PII emails": a.get("pii_emails", ""),
        "Eval contamination files": a.get("eval_contamination_files", ""),
        "Quality score": a.get("quality_score", ""),
        "Training suitability": a.get("training_suitability", ""),
        "Code availability": a["availability"],
    }


# ---------------------------------------------------------------------------
# Safe file writing (so data isn't lost on Windows if the file is open in Excel)
# ---------------------------------------------------------------------------

def safe_open_for_write(path, encoding="utf-8"):
    # create the parent directory if the user gave a path that doesn't exist yet
    parent = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError:
        pass
    try:
        return open(path, "w", newline="", encoding=encoding), path
    except OSError:
        base, ext = os.path.splitext(path)
        alt = f"{base}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        print(f"  [warn] could not write '{path}' (maybe it's open in Excel) —")
        print(f"         saving to '{alt}' instead.")
        return open(alt, "w", newline="", encoding=encoding), alt


# ---------------------------------------------------------------------------
# Provider selection / auto-detect
# ---------------------------------------------------------------------------

def pick_provider(args):
    if args.provider != "auto":
        return args.provider
    if args.path:
        return "local"
    # if all given projects are existing directories, treat as local
    if args.project and all(os.path.isdir(p) for p in args.project):
        return "local"
    if args.org:
        return "github"
    if args.group:
        return "gitlab"
    tok = args.token or ""
    if tok.startswith(("ghp_", "gho_", "ghu_", "github_pat_")):
        return "github"
    if tok.startswith("glpat-"):
        return "gitlab"
    if args.github_url != "https://api.github.com":
        return "github"
    return "gitlab"   # backward compatible default


def main():
    # Never crash on characters the console can't encode (e.g. Windows with
    # output redirected to a cp1252 file) — degrade to '?' instead.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

    ap = argparse.ArgumentParser(
        description="Universal codebase analyzer — GitLab, GitHub, or local repo")
    ap.add_argument("--provider", choices=["auto", "gitlab", "github", "local"],
                    default="auto",
                    help="Which source to use (default: auto-detect)")
    ap.add_argument("--project", action="append", default=[],
                    help="GitLab: group/repo or numeric ID | "
                         "GitHub: owner/repo | Local: repo folder path. "
                         "Can be given multiple times.")
    ap.add_argument("--path", action="append", default=[],
                    help="Path to a local repo (offline mode). "
                         "Can be given multiple times.")
    ap.add_argument("--project-file", action="append", default=[],
                    help="Text file with one repo per line (GitLab: "
                         "group/repo, GitHub: owner/repo, Local: folder "
                         "path). Blank lines and lines starting with # are "
                         "ignored. Can be given multiple times.")
    ap.add_argument("--group", help="GitLab group — all of its projects "
                                    "(in local mode: a folder containing repos)")
    ap.add_argument("--org", help="GitHub organization or user — all repos")
    ap.add_argument("--token",
                    default=os.environ.get("GITLAB_TOKEN")
                    or os.environ.get("GITHUB_TOKEN"),
                    help="Access token. Or set the GITLAB_TOKEN / "
                         "GITHUB_TOKEN env var. (Not needed in local mode)")
    ap.add_argument("--gitlab-url", default="https://gitlab.com",
                    help="Self-hosted GitLab URL (default: https://gitlab.com)")
    ap.add_argument("--github-url", default="https://api.github.com",
                    help="GitHub Enterprise API URL "
                         "(default: https://api.github.com)")
    ap.add_argument("--name", default="", help="Company/project name to use in the report")
    ap.add_argument("--max-mrs", type=int, default=0,
                    help="MR/PR fetch limit (0 = all, default)")
    ap.add_argument("--sample-mrs", type=int, default=0,
                    help="Deep-analysis limit (0 = all fetched, default)")
    ap.add_argument("--max-test-files", type=int, default=0,
                    help="How many test files to count test cases in "
                         "(default 0 = auto: ALL locally, 200 via API)")
    ap.add_argument("--max-commit-scan", type=int, default=0,
                    help="How many recent commits to scan for LLM signatures "
                         "(default 0 = ALL commits; on very large repos with "
                         "API providers set a limit to save time, "
                         "e.g. --max-commit-scan 5000)")
    ap.add_argument("--max-quality-scan", type=int, default=0,
                    help="How many source files to run the quality/secrets/"
                         "dedup scan on (0 = auto: local 1000, API 50)")
    ap.add_argument("--max-ai-file-scan", type=int, default=0,
                    help="How many source files to search for AI-attribution "
                         "comments in (0 = auto: local 300, API 30; "
                         "-1 = skip)")
    ap.add_argument("--max-loc-sample", type=int, default=0,
                    help="GitLab/GitHub mode only: how many code files to "
                         "fetch and real-count for the LoC estimate. "
                         "0 = auto (samples 300 files, extrapolated). "
                         "-1 = fetch EVERY code file (exact count, same "
                         "as local mode — no need to guess a big number, "
                         "but on repos with thousands of files this means "
                         "that many API calls: slow, and may hit rate "
                         "limits). N = sample exactly N files. Local mode "
                         "always counts every file directly regardless of "
                         "this flag.")
    ap.add_argument("--workers", type=int, default=8,
                    help="Parallel requests (default 8)")
    ap.add_argument("--local-mrs", choices=["auto", "strict", "merges", "off"],
                    default="auto",
                    help="MR/PR detection for local repos: auto = prefer "
                         "explicit #N/!N refs (default) | strict = only "
                         "explicit refs | merges = also all merge commits | "
                         "off = MR fields blank")
    ap.add_argument("--enable-code-execution", action="store_true",
                    help="REQUIRED to measure real test coverage %%. Off by "
                         "default because it means running the analyzed "
                         "repo's own code: installing its dependencies "
                         "(npm/pip/composer/etc.) and running its test "
                         "suite. For local repos that's the checkout on "
                         "disk; for GitLab/GitHub repos it also means "
                         "shallow-cloning the repo first. Only pass this "
                         "for repos you trust enough to execute.")
    ap.add_argument("--skip-local-coverage", action="store_true",
                    help="Local mode only: skip actually running the repo's "
                         "test suite to measure real coverage %% even if "
                         "--enable-code-execution is set")
    ap.add_argument("--skip-remote-coverage", action="store_true",
                    help="GitLab/GitHub mode: when the API/pipeline doesn't "
                         "already expose a coverage %%, skip shallow-cloning "
                         "the repo and running its test suite to measure "
                         "real coverage, even if --enable-code-execution is "
                         "set")
    ap.add_argument("--output", default="repo_report.csv")
    args = ap.parse_args()

    if not (args.project or args.group or args.org or args.path
            or args.project_file):
        ap.error("one of --project / --path / --project-file / --group / "
                 "--org is required")

    if args.workers < 1:
        ap.error("--workers must be >= 1")
    for flag, val in (("--max-mrs", args.max_mrs),
                      ("--sample-mrs", args.sample_mrs),
                      ("--max-test-files", args.max_test_files),
                      ("--max-commit-scan", args.max_commit_scan),
                      ("--max-quality-scan", args.max_quality_scan)):
        if val < 0:
            ap.error(f"{flag} must be >= 0 (0 = no limit)")
    if args.max_ai_file_scan < -1:
        ap.error("--max-ai-file-scan must be >= -1 (-1 = skip, 0 = auto)")
    if args.max_loc_sample < -1:
        ap.error("--max-loc-sample must be >= -1 (-1 = every file, 0 = auto)")

    # Load repos listed in --project-file(s): one repo per line, '#' = comment
    file_projects = []
    for fpath in args.project_file:
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        file_projects.append(line)
        except OSError as e:
            ap.error(f"could not read --project-file '{fpath}': {e}")
    if args.project_file:
        print(f"Loaded {len(file_projects)} repo(s) from "
              f"{len(args.project_file)} file(s)")
        # Merge into args.project so provider auto-detection (which only
        # inspects args.project) also sees these repos.
        args.project = list(args.project) + file_projects

    skip_local_coverage = args.skip_local_coverage or not args.enable_code_execution
    skip_remote_coverage = args.skip_remote_coverage or not args.enable_code_execution
    if args.enable_code_execution:
        print("[WARNING] --enable-code-execution is on: this run will "
              "install dependencies and execute the analyzed repo's own "
              "code to measure real test coverage. Only do this for repos "
              "you trust.")
    elif not (args.skip_local_coverage and args.skip_remote_coverage):
        print("[note] coverage measurement needs --enable-code-execution "
              "(it runs the analyzed repo's own code) — coverage_pct "
              "fields will stay blank this run.")

    provider_name = pick_provider(args)
    print(f"Provider: {provider_name}")

    # Catch mismatches early with a clear message instead of failing deep
    # inside project_info() with a generic "not found".
    if provider_name != "local" and args.path:
        ap.error(f"--path implies local mode but --provider {provider_name} "
                 "was explicitly requested — drop --provider or use "
                 "--provider local")
    if provider_name == "local" and args.project:
        bad = [p for p in args.project if not os.path.isdir(p)]
        if bad:
            ap.error("--provider local requires --project values to be "
                     f"existing folder paths; not found: {', '.join(bad)}")
    if provider_name in ("gitlab", "github"):
        url = args.gitlab_url if provider_name == "gitlab" else args.github_url
        if not re.match(r"^https?://[^\s/]+", url):
            ap.error(f"--{provider_name}-url '{url}' doesn't look like a "
                     "valid URL (expected e.g. https://host)")

    if provider_name == "gitlab":
        prov = GitLabProvider(args.gitlab_url, args.token,
                              workers=args.workers)
    elif provider_name == "github":
        prov = GitHubProvider(args.github_url, args.token,
                              workers=args.workers)
    else:
        prov = LocalProvider(workers=args.workers, mr_mode=args.local_mrs)

    projects = list(args.project) + list(args.path)
    group = args.group or (args.org if provider_name == "github" else None)
    if group:
        print(f"Listing projects of '{group}'...")
        gp = prov.list_group_projects(group)
        projects += gp
        print(f"  found {len(gp)} projects")

    results = []
    detail = os.path.splitext(args.output)[0] + "_detail.json"
    for p in projects:
        try:
            r = analyze_project(prov, p, args.max_mrs, args.sample_mrs,
                                args.max_test_files, workers=args.workers,
                                max_commit_scan=args.max_commit_scan,
                                max_ai_file_scan=args.max_ai_file_scan,
                                max_quality_scan=args.max_quality_scan,
                                max_loc_sample=args.max_loc_sample,
                                skip_local_coverage=skip_local_coverage,
                                skip_remote_coverage=skip_remote_coverage)
            if r:
                results.append(r)
                # Save detail after every project — crash-safe
                try:
                    fh, detail = safe_open_for_write(detail)
                    with fh:
                        json.dump(results, fh, indent=2, default=str)
                except Exception as e:
                    print(f"  [warn] detail JSON save failed: {e}")
        except SystemExit:
            raise
        except KeyboardInterrupt:
            print("\n[interrupted] Stopping — writing the report for the "
                  f"{len(results)} project(s) finished so far...")
            break
        except Exception as e:
            print(f"  [error] {p}: {e}")

    if not results:
        print("No results found.")
        sys.exit(1)

    name = args.name or args.group or args.org or results[0]["repo"]
    agg = aggregate(results, name)

    # Console summary FIRST
    print("\n" + "=" * 62)
    print(f"SUMMARY — {name}")
    print("=" * 62)
    for k, v in to_row(agg).items():
        print(f"  {k:28s}: {v}")

    csv_path = args.output
    try:
        # utf-8-sig (BOM) so Excel renders non-ASCII correctly on Windows
        fh, csv_path = safe_open_for_write(args.output, encoding="utf-8-sig")
        with fh:
            w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            w.writeheader()
            w.writerow(to_row(agg))
            if len(results) > 1:
                for r in results:
                    w.writerow(to_row(aggregate([r], r["repo"])))
    except Exception as e:
        print(f"\n[error] could not save the CSV: {e}")
        print(f"The data is safe in the '{detail}' JSON — a CSV can be built from it.")
        csv_path = "(not saved)"

    print(f"\nCSV report : {csv_path}")
    print(f"Detail JSON: {detail}")


if __name__ == "__main__":
    main()
