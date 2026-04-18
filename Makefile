SHELL := /usr/bin/env bash

PACMAN ?= pacman
YAY ?= yay
UV ?= uv
UV_CACHE_DIR ?= .uv-cache

PACMAN_PACKAGES := python uv sudo systemd arch-install-scripts base-devel git
AUR_PACKAGES :=

.PHONY: help deps pacman-deps aur-deps sync install uninstall test smoke smoke-dry-run check

help:
	@printf '%s\n' 'arch-env development targets'
	@printf '%s\n' ''
	@printf '%s\n' '  make deps         Install Arch system deps and sync Python deps'
	@printf '%s\n' '  make pacman-deps  Install required packages with pacman'
	@printf '%s\n' '  make aur-deps     Install optional AUR packages with yay'
	@printf '%s\n' '  make sync         Sync Python dependencies with uv'
	@printf '%s\n' '  make install      Install ae/arch-env into the user PATH with uv'
	@printf '%s\n' '  make reinstall    Reinstall ae/arch-env after source changes'
	@printf '%s\n' '  make uninstall    Remove the uv tool install'
	@printf '%s\n' '  make test         Run the test suite'
	@printf '%s\n' '  make smoke        Run the real package-manager smoke test'
	@printf '%s\n' '  make smoke-dry-run Print smoke-test commands without running them'
	@printf '%s\n' ''
	@printf '%s\n' 'Override package lists if needed:'
	@printf '%s\n' '  make deps PACMAN_PACKAGES="python uv sudo systemd arch-install-scripts base-devel git"'
	@printf '%s\n' '  make aur-deps AUR_PACKAGES="some-aur-package"'

deps: pacman-deps aur-deps sync

pacman-deps:
	@command -v $(PACMAN) >/dev/null 2>&1 || { printf '%s\n' 'pacman is required on Arch Linux.' >&2; exit 1; }
	sudo $(PACMAN) -S --needed $(PACMAN_PACKAGES)

aur-deps:
	@if [ -z "$(strip $(AUR_PACKAGES))" ]; then \
		printf '%s\n' 'No AUR packages configured.'; \
	elif command -v $(YAY) >/dev/null 2>&1; then \
		$(YAY) -S --needed $(AUR_PACKAGES); \
	else \
		printf '%s\n' 'yay is required to install AUR_PACKAGES.' >&2; \
		exit 1; \
	fi

sync:
	@command -v $(UV) >/dev/null 2>&1 || { printf '%s\n' 'uv is required. Run make pacman-deps first.' >&2; exit 1; }
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) sync

install:
	@command -v $(UV) >/dev/null 2>&1 || { printf '%s\n' 'uv is required. Run make deps first.' >&2; exit 1; }
	$(UV) tool install --force --reinstall .
	@printf '%s\n' 'Installed ae and arch-env with uv.'
	@printf '%s\n' 'Ensure the uv tool bin directory is on PATH, usually ~/.local/bin.'

uninstall:
	@command -v $(UV) >/dev/null 2>&1 || { printf '%s\n' 'uv is required.' >&2; exit 1; }
	$(UV) tool uninstall arch-env

test:
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) run python -m unittest discover -s tests

smoke:
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) run python scripts/smoke_dev_package_managers.py

smoke-dry-run:
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) run python scripts/smoke_dev_package_managers.py --dry-run

reinstall: install

check: test smoke-dry-run
