import glob
import os

DEPLOYMENTS_FOLDER = ".deployments"
FLOWS_SUBFOLDER = "flows"


def get_deployments_folder_path(
    entities_root_folder_path: str,
) -> str:
    """Return the path to the flow deployments folder."""
    return os.path.join(
        entities_root_folder_path,
        DEPLOYMENTS_FOLDER,
        FLOWS_SUBFOLDER,
    )


def discover_manifests(
    entities_root_folder_path: str,
) -> list[str]:
    """Discover deployment manifest YAML files in .deployments/flows/.

    Returns a sorted list of absolute paths to manifest files.
    Sorting is alphabetical which equals timestamp order given
    the naming convention.
    """
    deploy_dir = get_deployments_folder_path(
        entities_root_folder_path=entities_root_folder_path,
    )

    if not os.path.isdir(deploy_dir):
        return []

    pattern = os.path.join(deploy_dir, "*.yaml")
    manifests = glob.glob(pattern)

    return sorted(manifests)
