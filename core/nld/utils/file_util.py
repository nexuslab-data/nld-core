import fileinput
import hashlib
import os
import re
import shutil

from nld.pydantic import NldNamespace


def join_paths(*paths: str) -> str:
    """Safely joins multiple path segments with proper "/" handling.

    This function normalizes path separators by:
    - Stripping trailing slashes from all segments except the last
    - Using "/" as the separator (consistent with URL-style paths and
      cloud storage)
    - Handling empty strings gracefully

    Args:
        *paths: Variable number of path segments to join.

    Returns:
        The joined path with normalized separators.

    Examples:
        >>> join_paths("root/", "folder", "subfolder/")
        'root/folder/subfolder/'

        >>> join_paths("root", "/folder/", "/subfolder")
        'root/folder/subfolder'

        >>> join_paths("root/path/", "/state")
        'root/path/state'
    """
    if not paths:
        return ""

    # Filter out empty strings
    non_empty_paths = [p for p in paths if p]

    if not non_empty_paths:
        return ""

    # Process each segment
    processed_segments = []
    for _i, path in enumerate(non_empty_paths):
        # Strip leading and trailing slashes for intermediate segments
        segment = path.strip("/")
        if segment:  # Only add non-empty segments
            processed_segments.append(segment)

    # Join with "/"
    result = "/".join(processed_segments)

    # Preserve leading slash if the first path had one
    if non_empty_paths[0].startswith("/"):
        result = "/" + result

    # Preserve trailing slash if the last path had one
    if non_empty_paths[-1].endswith("/"):
        result = result + "/"

    return result


def clean_folder_path(path: str) -> str:
    return path if path.endswith("/") else f"{path}/"


def get_list_of_files_in_cur_folder(dir_path: str, pattern: str) -> list[str]:
    """Get list of all files in the current folder.

    Args:
        dir_path: The directory path to look into.
        pattern: The pattern of the files to look for.

    Returns:
        The list of file complete paths.
    """
    cur_file_list = os.listdir(dir_path)
    file_list = list()
    # Iterate over all the entries
    for entry in cur_file_list:
        # Create full path
        full_path = os.path.join(dir_path, entry)
        if not os.path.isdir(full_path):
            if pattern is not None:
                # Checks if the pattern is matching the file
                if re.search(re.compile(pattern), entry) is not None:
                    file_list.append(full_path)
            else:
                file_list.append(full_path)
    return file_list


def get_list_of_files(dir_path: str) -> list[str]:
    """Get list of all files in the directory tree recursively.

    Args:
        dir_path: The directory path to look into.

    Returns:
        The list of file complete paths.
    """
    # create a list of file and sub directories
    # names in the given directory
    cur_file_list = os.listdir(dir_path)
    file_list: list[str] = []
    # Iterate over all the entries
    for entry in cur_file_list:
        # Create full path
        full_path = os.path.join(dir_path, entry)
        # If entry is a directory then get the list of files in this directory
        if os.path.isdir(full_path):
            file_list = file_list + get_list_of_files(full_path)
        else:
            file_list.append(full_path)
    return file_list


def get_files_grouped_by_subdirectory(
    root_path: str,
    pattern: str | None = None,
) -> dict[str, list[str]]:
    """
    Recursively get files from directory tree, grouped by subdirectory namespace.

    Args:
        root_path: Root directory to search in
        pattern: Optional regex pattern to filter file names

    Returns:
        Dictionary mapping namespace (relative path) to list of file paths.
        Files in root directory are under "." namespace.
        Files in subdirectories use path separators as namespace separators.

    Example:
        Given structure:
            /root/
                file1.yml
                sub1/
                    file2.yml
                sub1/sub2/
                    file3.yml

        Returns:
            {
                ".": ["/root/file1.yml"],
                "sub1": ["/root/sub1/file2.yml"],
                "sub1.sub2": ["/root/sub1/sub2/file3.yml"],
            }
    """
    result: dict[str, list[str]] = {}

    compiled_pattern = re.compile(pattern) if pattern else None

    def _scan_directory(current_path: str, relative_path: str) -> None:
        """Recursively scan directory and populate result dictionary."""
        if not os.path.exists(current_path):
            return

        namespace = (
            str(NldNamespace.from_path(relative_path))
            if relative_path
            else NldNamespace.ROOT_VALUE
        )
        files_in_namespace: list[str] = []

        try:
            entries = os.listdir(current_path)
        except PermissionError:
            return

        for entry in entries:
            full_path = os.path.join(current_path, entry)

            if os.path.isdir(full_path):
                new_relative = (
                    os.path.join(relative_path, entry) if relative_path else entry
                )
                _scan_directory(current_path=full_path, relative_path=new_relative)
            elif os.path.isfile(full_path):
                if compiled_pattern is None or compiled_pattern.search(entry):
                    files_in_namespace.append(full_path)

        if files_in_namespace:
            result[namespace] = files_in_namespace

    _scan_directory(current_path=root_path, relative_path="")

    return result


def get_list_of_files_in_relative_path(
    dir_name: str, relative_path: str = "."
) -> list[str]:
    # create a list of file and sub directories
    # names in the given directory
    list_of_files = os.listdir(dir_name)
    all_files: list[str] = []
    # Iterate over all the entries
    for entry in list_of_files:
        # Create full path
        full_path = os.path.join(dir_name, entry)
        current_relative_path = os.path.join(relative_path, entry)
        # If entry is a directory then get the list of files in this directory
        if os.path.isdir(full_path):
            all_files = all_files + get_list_of_files_in_relative_path(
                full_path, current_relative_path
            )
        else:
            all_files.append(current_relative_path)

    return all_files


def get_list_of_directories_in_relative_path(
    dir_name: str, relative_path: str = "."
) -> list[str]:
    # create a list of file and sub directories
    # names in the given directory
    list_of_files = os.listdir(dir_name)
    all_directories = list()
    # Iterate over all the entries
    for entry in list_of_files:
        # Create full path
        full_path = os.path.join(dir_name, entry)
        current_relative_path = os.path.join(relative_path, entry)
        # If entry is a directory then get the list of files in this directory
        if os.path.isdir(full_path):
            all_directories.append(current_relative_path)
            all_directories = (
                all_directories
                + get_list_of_directories_in_relative_path(
                    full_path, current_relative_path
                )
            )
    return all_directories


def get_list_of_directories(dir_name: str) -> list[str]:
    """Get list of all files in the directory tree recursively.

    Args:
        dir_name: The directory absolute path to look into.

    Returns:
        A list containing all the folders found in the directory provided.
    """
    # create a list of file and sub directories
    # names in the given directory
    list_of_files = os.listdir(dir_name)
    directory_list = list()
    # Iterate over all the entries
    for entry in list_of_files:
        # Create full path
        full_path = os.path.join(dir_name, entry)
        # If entry is a directory then get the list of files in this directory
        if os.path.isdir(full_path):
            directory_list.append(full_path)
            directory_list = directory_list + get_list_of_directories(full_path)
    return directory_list


def remove_all_files_in_directory(dir_name: str) -> None:
    list_of_files = get_list_of_files_in_relative_path(dir_name)
    for file_relative_path in list_of_files:
        os.remove(os.path.join(dir_name, file_relative_path))


def get_file_base_name_wo_extension(file_path: str) -> str:
    """Get the base name of a file.

    Args:
        file_path: The file complete path.

    Returns:
        The base name of the file without the extension.
    """
    split_file_name = os.path.basename(file_path).split(".")
    split_file_name.pop(len(split_file_name) - 1)
    return ".".join(split_file_name)


def unpack_archive(
    archive_file_path: str,
    extraction_folder: str,
    remove_archive_after_unpack: bool = False,
    extraction_inside_current_folder: bool = False,
) -> str:
    """Unpacks an archive in a folder with the same base name.

    Unpacks the archive in a folder located in the extraction folder provided.

    Args:
        archive_file_path: The archive complete path.
        extraction_folder: The folder to extraction the archive into.
        remove_archive_after_unpack: A flag to force the deletion of the
            archive after the unpack.
        extraction_inside_current_folder: A flag to extract inside the
            current folder, instead of in a dedicated folder.

    Returns:
        The complete path of the extracted archive.
    """
    if extraction_inside_current_folder:
        archive_extraction_folder = os.path.dirname(archive_file_path)
    else:
        archive_file_base_name = get_file_base_name_wo_extension(archive_file_path)
        archive_extraction_folder = os.path.join(
            extraction_folder, archive_file_base_name
        )
        os.makedirs(archive_extraction_folder, exist_ok=False)
    shutil.unpack_archive(archive_file_path, archive_extraction_folder)
    if remove_archive_after_unpack:
        os.remove(archive_file_path)
    return archive_extraction_folder


def make_archive_from_folder(
    archive_generation_folder_path: str,
    folder_to_archive: str,
    remove_folder_after_pack: bool = False,
) -> str:
    """Makes an archive from the folder provided.

    Creates the archive into the generation folder path provided.

    Args:
        archive_generation_folder_path: The folder path to generate the
            archive into.
        folder_to_archive: The folder to archive.
        remove_folder_after_pack: A flag to force the deletion of the packed
            folder after archive is created.

    Returns:
        The complete path of the generated archive.
    """
    folder_to_archive_complete_path = os.path.join(
        archive_generation_folder_path, folder_to_archive
    )
    generated_archive_path = shutil.make_archive(
        archive_generation_folder_path, "zip", folder_to_archive_complete_path
    )
    if remove_folder_after_pack:
        shutil.rmtree(folder_to_archive_complete_path)
    return generated_archive_path


def hash(file_path: str) -> str:
    """Returns the standard hash of a file.

    Args:
        file_path: The file path.

    Returns:
        The file hash.
    """
    with open(file_path, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest()
    return h.upper()


def replace_text_in_file(file_path: str, original_str: str, new_str: str) -> None:
    """Replace a text inside an existing file.

    Args:
        file_path: The file path.
        original_str: The original string.
        new_str: The new string.
    """
    with fileinput.FileInput(file_path, inplace=True) as file:
        for line in file:
            print(line.replace(original_str, new_str))


def replace_strings_in_file(file_path: str, replacement_dict: dict[str, str]) -> None:
    """Replace one to multiple string inside an existing file.

    Args:
        file_path: The file path.
        replacement_dict: The replacement dictionary linking an original
            string to the new string that it should be replaced with.
    """
    # Read in the file
    with open(file_path) as file:
        filedata = file.read()

    # Replace the target string
    for original_value, new_value in replacement_dict.items():
        filedata = filedata.replace(original_value, new_value)

    # Write the file out again
    with open(file_path, "w") as file:
        file.write(filedata)


def is_text_in_file(file_path: str, str_to_find: str) -> bool:
    with open(file_path) as file_reader:
        if str_to_find in file_reader.read():
            return True
    return False


def merge_files(merge_file_path: str, files_to_merge: list[str]) -> None:
    with open(merge_file_path, "w") as outfile:
        for file in files_to_merge:
            with open(file) as infile:
                outfile.write(infile.read())


def create_empty_file(file_path: str) -> None:
    open(file_path, "a").close()


def load_file_into_dict(file_path: str) -> dict[str, str]:
    """Loads the content of a file into a dictionary.

    The key is the file name (without the extension) and the value is the
    complete content of the file.

    Args:
        file_path: The path to the file.

    Returns:
        A dictionary with the file name (without extension) as key and the
        file content as value.
    """
    key, _ext = os.path.splitext(os.path.basename(file_path))

    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    return {key: content}
