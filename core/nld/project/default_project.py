import os

from nld.project.project import Project

DEFAULT_PROJECT_YAML_FILE_CONTENT = """# Project Configuration
name: 'dummy' # Project Name to be changed
version: '0.0.1'
"""


def get_default(root_folder_path: str) -> Project:
    return Project(
        root_folder_path=root_folder_path,
        name=os.path.basename(root_folder_path),
        version="0.0.1",
    )
