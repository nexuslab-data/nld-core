import os

import requests

from nld.logging import StandardInfoEvent, log_event_default


def download_file(url: str | bytes, output_path: str) -> None:
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)

        log_event_default(
            StandardInfoEvent(
                f"File downloaded successfully and saved to {output_path}"
            )
        )
    except requests.exceptions.RequestException as e:
        print(f"Failed to download file: {e}")
