# Coda Chess Engine — Makefile
# Supports: manual builds, OpenBench integration, PGO builds
#
# Usage:
#   make                  Build with native CPU optimizations
#   make EXE=coda-v2      Build with custom output name
#   make pgo              PGO-optimized build (only helps v5 on main branch — see note below)
#   make openbench        OpenBench-compatible build target
#   make net              Download the production NNUE net
#   make clean            Remove build artifacts

# Configuration
EXE := coda
NET_URL := $(shell cat net.txt 2>/dev/null)
# EVALFILE: defaults to the filename from net.txt (e.g. net-v5-768pw-w7-e800s800-filtered-lowestlr.nnue)
# OB overrides this with an absolute path to the network file.
EVALFILE := $(if $(NET_URL),$(notdir $(NET_URL)),net.nnue)
MIN_RUST_VERSION := 1.70.0

# Platform detection
ifeq ($(OS),Windows_NT)
    NAME := $(EXE).exe
    RM := del /q
else
    NAME := $(EXE)
    RM := rm -f
endif

# Rust flags
export RUSTFLAGS := -Ctarget-cpu=native

# Default: PGO build on this branch (experiment/pgo-openbench-default).
# OpenBench invokes `make -j EXE=<out>` which builds the first target; making
# `rule` an alias to `pgo` is the only way to route OB through PGO today
# (OB's makefile_command in Client/utils.py is hardcoded — no make_target
# field). On main, `rule` stays plain so local dev builds stay fast.
rule: pgo

# OpenBench build — same as default on this branch.
openbench: pgo

# PGO build (profile-guided optimization).
#
# Status (2026-05-17): WORKS AGAIN with codegen-units = 16.
#   Plain release:  ~370K NPS bench
#   PGO:            ~400K NPS bench  (+8-9%)
#
# History (2026-04-17, with codegen-units = 1):
#   v5 on main:          +3-5% NPS. Worked.
#   v9 on threat branch: -10 to -12% NPS regression. Broken.
#
# What changed: 2026-05-17 SMP investigation moved release profile from
# `codegen-units = 1` to `codegen-units = 16`. The v9-era PGO regression
# was full LTO + cgu=1 + 50 MB embedded net overwhelming LLVM's PGO-LTO
# pass — over-inlining small functions (push_threats_for_piece and
# friends) into delta-generation hot paths, bloating them and hurting
# icache behaviour. cgu=16 splits the work and lets PGO make local
# decisions per unit, restoring its win. See
# docs/smp_scaling_investigation_2026-05-17.md.
#
# Requires: rustup component add llvm-tools-preview; cargo install cargo-pgo
TARGET_TUPLE := $(shell rustc --print host-tuple 2>/dev/null)
pgo: check-rust net
	CODA_EVALFILE=$(abspath $(EVALFILE)) cargo pgo instrument build -- --features embedded-net
	LLVM_PROFILE_FILE=target/pgo-profiles/coda_%m_%p.profraw ./target/$(TARGET_TUPLE)/release/coda bench 13
	CODA_EVALFILE=$(abspath $(EVALFILE)) cargo pgo optimize build -- --features embedded-net
	cp target/$(TARGET_TUPLE)/release/coda $(NAME)

# Download production NNUE net (uses actual filename from net.txt, not generic net.nnue)
net:
	@if [ ! -f "$(EVALFILE)" ] && [ -n "$(NET_URL)" ]; then \
		echo "Downloading NNUE net from $(NET_URL)..."; \
		curl -sL "$(NET_URL)" -o "$(EVALFILE)"; \
		echo "Downloaded $(EVALFILE)"; \
	elif [ -f "$(EVALFILE)" ]; then \
		echo "$(EVALFILE) already exists"; \
	else \
		echo "Warning: no net.txt found and no $(EVALFILE) present"; \
	fi

# Check Rust toolchain version
check-rust:
	@command -v cargo >/dev/null 2>&1 || { echo "Error: cargo not found. Install Rust from https://rustup.rs"; exit 1; }
	@RUST_VERSION=$$(rustc --version | sed 's/rustc \([0-9]*\.[0-9]*\.[0-9]*\).*/\1/'); \
	MIN="$(MIN_RUST_VERSION)"; \
	if [ "$$(printf '%s\n' "$$MIN" "$$RUST_VERSION" | sort -V | head -n1)" != "$$MIN" ]; then \
		echo "Error: Rust $$RUST_VERSION is too old. Need >= $$MIN. Run: rustup update"; \
		exit 1; \
	fi

clean:
	cargo clean
	$(RM) $(NAME)

.PHONY: rule openbench pgo net check-rust clean
