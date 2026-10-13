import os

RECIPE = "build.sh"


def case_type(package_dir: str) -> str:
    """"recipe" for a build-recipe case (a build.sh run on the build host, any
    build system), "rpm" for a package with a .spec file (OBS or osc build)."""
    try:
        names = os.listdir(package_dir)
    except OSError:
        return "rpm"
    if RECIPE in names and not any(n.endswith(".spec") for n in names):
        return "recipe"
    return "rpm"


def case_environment(package_dir: str):
    """Name of the build environment a recipe case declares in manifest.json."""
    import json
    try:
        with open(os.path.join(package_dir, "manifest.json")) as f:
            return (json.load(f).get("environment") or None)
    except (OSError, ValueError):
        return None
