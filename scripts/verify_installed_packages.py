"""Verify metadata, imports, and entry points from an installed WhyDiff release set."""

from importlib import import_module
from importlib.metadata import distribution, entry_points

PACKAGES = {
    "whydiff-core": "whydiff",
    "whydiff-cli": "whydiff_cli",
    "whydiff-mcp": "whydiff_mcp",
}
SCRIPTS = {"whydiff", "whydiff-mcp"}


def main() -> None:
    for package, module in PACKAGES.items():
        metadata = distribution(package).metadata
        requires_python = metadata.get("Requires-Python")
        if requires_python != ">=3.10":
            raise RuntimeError(f"{package} advertises Requires-Python {requires_python!r}")
        import_module(module)

    installed_scripts = {
        entry_point.name: entry_point for entry_point in entry_points(group="console_scripts")
    }
    missing_scripts = SCRIPTS - installed_scripts.keys()
    if missing_scripts:
        raise RuntimeError(f"missing console entry points: {sorted(missing_scripts)}")
    for script in SCRIPTS:
        installed_scripts[script].load()


if __name__ == "__main__":
    main()
