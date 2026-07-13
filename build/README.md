# Build Output

Local and CI release builds place final PrintBridge Client packages in this directory.

Generated installers, portable archives, DMGs, checksums, release notes, compiler reports, and logs are intentionally ignored by Git. This file keeps the output directory present in a fresh checkout.

Temporary compiler output and caches continue to use the operating system's temporary directory and are removed after each build.

To save packages elsewhere, use `-SelectOutputDir` on Windows or `--select-output-dir` on macOS. Explicit path arguments and `PRINTBRIDGE_RELEASE_DIR` are also supported; see [BUILDING.md](../BUILDING.md).
