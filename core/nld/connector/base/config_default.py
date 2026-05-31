from .config import (
    ConnectionConfig,
    ConnectionConfigs,
)

DEFAULT_TOML_FILE_CONTENT = """# Connections configurations

#[connections.snow_dummy]
#name = "snow_dummy"
#type = "snowflake"
#default_profile = {}
#
#[connections.snow_dummy.profiles.local]
#account = "dummy.eu-west-3.aws"
#user = "OPENDATA_USER"
#password = "OPENDATA_PASSWORD"
"""


def get_default() -> ConnectionConfigs:
    return ConnectionConfigs(
        configs={
            "snow_dummy": ConnectionConfig(
                name="snow_dummy",
                type="snowflake",
                default_profile={},
                profiles={
                    "local": {
                        "account": "dummy.eu-west-3.aws",
                        "user": "OPENDATA_USER",
                        "password": "OPENDATA_PASSWORD",
                    }
                },
                custom_connector=None,
            )
        }
    )
