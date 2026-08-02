# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

`scrap` is currently an empty scaffold repository. The only tracked file is `README.md`, which contains just the title `# scrap`. There is no source code, build tooling, package manifest, test suite, or CI configuration yet.

Because there is no established structure, workflow, or convention to document, this file intentionally stays minimal. **Update this file as soon as real content is added** — see the checklist below.

## When this repo gains real content

The next time meaningful code, docs, or tooling land here, refresh this file to cover:

- **Structure**: top-level layout and what each major directory/module is for.
- **Setup**: how to install dependencies and any required environment/config.
- **Build/run**: the commands to build and run the project locally.
- **Test**: how to run the test suite (and a single test, if applicable).
- **Lint/format**: any linters, formatters, or type checkers in use, and how to invoke them.
- **Conventions**: naming, file organization, or architectural patterns specific to this repo.
- **Branching/PR workflow**: if this repo adopts conventions beyond standard git flow.

## Working here today

- There's nothing to build, run, or test yet — verify before assuming standard scaffolding (e.g. `package.json`, `pyproject.toml`) exists; it currently does not.
- Prefer extending `README.md` with a real project description once the purpose of the repo is decided.
